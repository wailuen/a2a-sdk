"""RT-003 (debug round 4): the read-side re-assertion in
``routes/a2a.py::_create_task_record`` must cover BOTH transcript invariants a
``TaskStore`` writer can break, not just the most recently fixed one.

``bridge_context_messages`` (agent/loop.py) was added so the route re-asserts
"never ends on ``user``" on whatever ``TaskStore.context_messages()`` returns,
because that method is a non-abstract, overridable ABC hook whose whole reason
to exist is external durable subclasses. But the SAME writers can hand back the
other broken shape — a transcript ending on a dangling assistant ``toolUse``
with no matching ``toolResult`` — and that one is the GH-150 shape itself:

- ``TaskStore.persist_messages``'s own docstring (RT-B-205, tasks/store.py)
  documents that the SDK deliberately flushes exactly that shape into durable
  storage on every ``INTERRUPT_STATES`` transition.
- an in-memory repair that failed (``repair_dangling_tool_use_safe`` returning
  False) leaves a TERMINAL record in that same shape.

Either way it would be folded straight into the new task's ``record.messages``
and sent to Bedrock's Converse API, which rejects it outright. The route's own
comment stated the rationale for read-side re-assertion and then implemented
only half of it.

Also pins that the fold rule itself is SHARED with the write side
(``agent/runner.py::repair_dangling_tool_use``) rather than being a second
inline copy that can drift.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any

from agent_sdk.agent import runner as runner_module
from agent_sdk.agent.loop import bridge_context_messages, close_dangling_tool_use
from agent_sdk.models.a2a import Task, TaskState, TaskStatus
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord


def _dangling() -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": [{"text": "go"}]},
        {
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": "call-1", "name": "t", "input": {}}}],
        },
    ]


def _assert_no_dangling_tool_use(messages: list[dict[str, Any]]) -> None:
    """Every assistant toolUse must be answered by a toolResult in the very
    next message — the Converse API contract."""
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        ids = [
            b["toolUse"]["toolUseId"]
            for b in msg.get("content", [])
            if isinstance(b, dict) and isinstance(b.get("toolUse"), dict)
        ]
        if not ids:
            continue
        assert i + 1 < len(messages), f"assistant toolUse {ids} at {i} has no following message"
        nxt = messages[i + 1]
        assert nxt.get("role") == "user", f"toolUse {ids} answered by role={nxt.get('role')!r}"
        answered = [
            b["toolResult"]["toolUseId"]
            for b in nxt.get("content", [])
            if isinstance(b, dict) and isinstance(b.get("toolResult"), dict)
        ]
        assert set(ids) <= set(answered), f"toolUse {ids} unanswered; got {answered}"


def test_bridge_context_messages_closes_a_dangling_tool_use_tail() -> None:
    prior = _dangling()
    bridged = bridge_context_messages(prior)

    _assert_no_dangling_tool_use(bridged)
    assert bridged[2]["role"] == "user"
    assert bridged[2]["content"][0]["toolResult"]["toolUseId"] == "call-1"
    assert bridged[2]["content"][0]["toolResult"]["status"] == "error"
    # and the trailing-user invariant is re-asserted on top of it, in the same
    # order repair_dangling_tool_use uses
    assert bridged[-1]["role"] == "assistant"


def test_bridge_context_messages_synthetic_result_is_sdk_authored() -> None:
    """SI-2: the synthetic toolResult text is a fixed SDK string — never
    derived from model or tool output, since it is replayed back to the model
    and can reach logs."""
    bridged = bridge_context_messages(_dangling())
    text = bridged[2]["content"][0]["toolResult"]["content"][0]["text"]
    assert "result unavailable" in text
    assert "call-1" not in text and "\"t\"" not in text


def test_bridge_context_messages_does_not_mutate_a_dangling_input() -> None:
    prior = _dangling()
    before = [dict(m) for m in prior]
    bridge_context_messages(prior)
    assert prior == before, "the caller's sequence (possibly a tuple) is never mutated"


def test_bridge_context_messages_tolerates_a_tuple_from_a_durable_store() -> None:
    """context_messages() returns a Sequence — a durable subclass may hand
    back an immutable one."""
    bridged = bridge_context_messages(tuple(_dangling()))
    _assert_no_dangling_tool_use(bridged)


def test_store_override_returning_a_dangling_tail_cannot_reach_record_messages() -> None:
    """End-to-end at the seam the route actually uses: a durable-shaped store
    override hands back the GH-150 shape, and what lands in the new task's
    record.messages is repaired."""

    class _DanglingContextStore(InMemoryTaskStore):
        def context_messages(self, context_id, identity=None):  # type: ignore[override]
            return _dangling()

    store = _DanglingContextStore()
    prior = store.context_messages("c1")
    record_messages = list(bridge_context_messages(prior))
    record_messages.append({"role": "user", "content": [{"text": "next turn"}]})

    _assert_no_dangling_tool_use(record_messages)
    # no two consecutive same-role messages either
    roles = [m["role"] for m in record_messages]
    assert all(a != b for a, b in zip(roles, roles[1:])), roles


def test_fold_rule_is_shared_not_duplicated() -> None:
    """RT-003: the write side must reach the SAME implementation, or the two
    copies drift — which is exactly how the read side ended up re-asserting
    only one of the two invariants."""
    runner_src = inspect.getsource(runner_module.repair_dangling_tool_use)
    assert "close_dangling_tool_use(" in runner_src, (
        "repair_dangling_tool_use must delegate the fold to the shared "
        "agent/loop.py::close_dangling_tool_use, not keep its own copy"
    )
    assert '"toolResult": {' not in runner_src, (
        "found an inline toolResult block builder in repair_dangling_tool_use "
        "— the fold rule must have exactly one implementation"
    )


def test_shared_fold_rule_prefers_known_results_over_the_default() -> None:
    """The write side's ``resolved`` map (this turn's completed sibling
    results, under any explicit caller override) must win over the fallback —
    the RT-B-001 guarantee, now expressed through the shared helper."""
    messages = _dangling()
    appended = close_dangling_tool_use(
        messages,
        default_content=[{"text": "fallback"}],
        resolved={"call-1": ([{"text": "the real result"}], "success")},
    )
    assert appended is True
    tr = messages[-1]["content"][0]["toolResult"]
    assert tr["content"] == [{"text": "the real result"}]
    assert tr["status"] == "success"


def test_shared_fold_rule_deep_copies_content_per_block() -> None:
    """RT-B-007/RT-B-206 survives the extraction: several dangling ids falling
    back to the same default must not share list OR dict objects."""
    messages = [
        {"role": "user", "content": [{"text": "go"}]},
        {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": "a", "name": "t", "input": {}}},
                {"toolUse": {"toolUseId": "b", "name": "t", "input": {}}},
            ],
        },
    ]
    default = [{"text": "shared"}]
    close_dangling_tool_use(messages, default_content=default)

    blocks = messages[-1]["content"]
    assert len(blocks) == 2
    first = blocks[0]["toolResult"]["content"]
    second = blocks[1]["toolResult"]["content"]
    assert first is not second and first is not default
    assert first[0] is not second[0] and first[0] is not default[0]
    first[0]["text"] = "mutated"
    assert second[0]["text"] == "shared" and default[0]["text"] == "shared"


def test_shared_fold_rule_is_a_no_op_on_a_healthy_transcript() -> None:
    healthy = [
        {"role": "user", "content": [{"text": "go"}]},
        {"role": "assistant", "content": [{"text": "done"}]},
    ]
    before = [dict(m) for m in healthy]
    assert close_dangling_tool_use(healthy, default_content=[{"text": "x"}]) is False
    assert healthy == before


def test_repair_and_bridge_agree_on_the_same_dangling_transcript() -> None:
    """The two entry points must produce the same SHAPE for the same input —
    that is the point of sharing the rule."""
    task = Task(id=uuid.uuid4().hex, contextId="c1", status=TaskStatus(state=TaskState.WORKING))
    record = TaskRecord(task=task, identity=("api_key", "t"), created_at=0.0, updated_at=0.0)
    record.messages = _dangling()
    runner_module.repair_dangling_tool_use(record, default_content=[{"text": "cancelled"}])

    read_side = bridge_context_messages(_dangling())

    assert [m["role"] for m in record.messages] == [m["role"] for m in read_side]
    _assert_no_dangling_tool_use(record.messages)
    _assert_no_dangling_tool_use(read_side)
