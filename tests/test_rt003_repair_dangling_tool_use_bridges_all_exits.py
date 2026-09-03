"""RT-003 (GH-147 AC3): repair_dangling_tool_use must call bridge_trailing_user
on EVERY exit path, not only after appending a synthetic toolResult.

Unit-level (imports only agent_sdk.agent.runner + agent_sdk.models.a2a /
agent_sdk.tasks.store — no FastAPI app boot), so it is independent of the
route-level cancel flow exercised by tests/test_gh150_cancel_dangling_tooluse.py.

Root cause: the function returned early — before ever reaching its own
``bridge_trailing_user(messages)`` call — whenever the last message wasn't an
assistant toolUse turn:

* ``last.get("role") != "assistant"`` (record.messages ends on a plain
  'user' turn, e.g. cancel while the model is still "thinking" on turn 1, or
  cancel between turns after a completed tool round leaves the toolResult
  fold as the last entry)
* no ``toolUse`` blocks on that assistant message (record.messages ends on
  an assistant turn with nothing to repair, but the caller still needs the
  never-ends-on-'user' guarantee enforced — a no-op here is only correct
  when the transcript doesn't already end on 'user')

``routes/a2a.py``'s ``tasks_cancel`` relies entirely on this helper for the
bridge (its worker's own ``except asyncio.CancelledError: raise`` leaves
record.messages untouched by design — "the canceller owns status + final
frame"), so any early return that skips the bridge leaves a CANCELED
(terminal) task's record.messages ending on 'user', later replayed verbatim
by context_messages() and topped with another 'user' turn on continuation.
"""

from __future__ import annotations

from typing import Any

from agent_sdk.agent.runner import repair_dangling_tool_use
from agent_sdk.models.a2a import Task, TaskState, TaskStatus
from agent_sdk.tasks.store import TaskRecord


def _record(messages: list[dict[str, Any]]) -> TaskRecord:
    task = Task(
        id="t1",
        contextId="c1",
        status=TaskStatus(state=TaskState.CANCELED),
    )
    record = TaskRecord(task=task, identity=("api_key", "test"), created_at=0.0, updated_at=0.0)
    record.messages = messages
    return record


def _default_content() -> list[dict[str, Any]]:
    return [{"text": "cancelled"}]


# ── RT-003 (a): cancel while the model is thinking — no assistant turn yet ─


def test_trailing_plain_user_message_bridged_even_with_no_dangling_tool_use():
    record = _record([{"role": "user", "content": [{"text": "hi"}]}])

    repair_dangling_tool_use(record, default_content=_default_content())

    roles = [m["role"] for m in record.messages]
    assert roles == ["user", "assistant"], roles
    assert roles[-1] != "user"


# ── RT-003 (b): cancel between turns — trailing user is a toolResult fold ─


def test_trailing_user_tool_result_fold_bridged_when_last_message_is_user():
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "tu1", "name": "echo", "input": {}}}
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "tu1",
                            "content": [{"text": "done"}],
                            "status": "success",
                        }
                    }
                ],
            },
        ]
    )

    repair_dangling_tool_use(record, default_content=_default_content())

    roles = [m["role"] for m in record.messages]
    assert roles == ["user", "assistant", "user", "assistant"], roles
    assert roles[-1] != "user"


# ── existing behavior must still hold ──────────────────────────────────────


def test_empty_messages_is_a_noop():
    record = _record([])
    repair_dangling_tool_use(record, default_content=_default_content())
    assert record.messages == []


def test_dangling_assistant_tool_use_gets_synthetic_result_and_bridge():
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "tu1", "name": "echo", "input": {}}}
                ],
            },
        ]
    )

    repair_dangling_tool_use(
        record, default_content=[{"text": "cancelled"}], default_status="error"
    )

    roles = [m["role"] for m in record.messages]
    assert roles == ["user", "assistant", "user", "assistant"], roles
    result_blocks = [
        b["toolResult"] for b in record.messages[2]["content"] if "toolResult" in b
    ]
    assert {b["toolUseId"] for b in result_blocks} == {"tu1"}
    for b in result_blocks:
        assert b["status"] == "error"
        assert b["content"] == [{"text": "cancelled"}]


def test_trailing_assistant_plain_text_with_no_tool_use_is_untouched():
    """The one shape where a no-op is actually correct: the transcript
    already ends on 'assistant' with no dangling toolUse, so there is
    nothing to bridge."""
    record = _record(
        [
            {"role": "user", "content": [{"text": "hi"}]},
            {"role": "assistant", "content": [{"text": "final answer"}]},
        ]
    )

    repair_dangling_tool_use(record, default_content=_default_content())

    roles = [m["role"] for m in record.messages]
    assert roles == ["user", "assistant"], roles
