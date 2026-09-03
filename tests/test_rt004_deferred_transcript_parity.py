"""RT-004: a completed/failed deferred (GH-87) task must never leave
``record.messages`` ending on a dangling assistant ``toolUse`` block.

``run_loop`` folds the assistant ``toolUse`` message (loop.py, per-turn
assistant fold) then, on a deferred handoff, yields ``DeferredEvent`` and
returns — BEFORE the matching ``toolResult`` message would normally be
appended. ``_run_deferred_background`` (runner.py) resolves the handle and
transitions the A2A task to COMPLETED/FAILED, but historically never touched
``record.messages`` at all. Since ``context_messages()`` (tasks/store.py)
replays a terminal task's ``record.messages`` verbatim on the next contextId
turn, a dangling assistant ``toolUse`` with no matching ``toolResult`` breaks
Converse-shaped backends (Bedrock) — the same class of defect GH-150 fixed
for ``tasks_cancel`` via ``_repair_dangling_tool_use``, and a violation of
GH-147's AC-3 (no two consecutive same-role messages / a fully alternating,
Converse-valid transcript).

No unittest.mock.patch / MagicMock. Uses FakeModelClient and the real
run_task_worker + InMemoryTaskStore, exactly like tests/test_gh87_deferred_task.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import run_task_worker, new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

pytestmark = pytest.mark.asyncio

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


def _make_store() -> InMemoryTaskStore:
    return InMemoryTaskStore()


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


async def _run_worker(
    store: InMemoryTaskStore,
    record: Any,
    model: FakeModelClient,
    registry: ToolRegistry,
) -> None:
    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=registry,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )


async def _wait_for_state(
    store: InMemoryTaskStore,
    task_id: str,
    states: tuple[str, ...] = ("completed", "failed"),
    timeout: float = 5.0,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        record = store.get(task_id)
        assert record is not None, "task record evicted during wait"
        state = record.task.status.state
        if state in states:
            return state
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"task stuck in state {state!r} after {timeout}s; expected one of {states}"
            )
        await asyncio.sleep(0.02)


def _assert_no_dangling_tool_use(messages: list[dict[str, Any]]) -> None:
    """Every ``toolUse`` id folded by an assistant message must have a
    matching ``toolResult`` in a LATER message — the Converse alternation
    invariant GH-147's AC-3 requires and GH-150 restores on cancellation."""
    pending: set[str] = set()
    for msg in messages:
        content = msg.get("content") or []
        if msg.get("role") == "assistant":
            for block in content:
                if isinstance(block, dict) and "toolUse" in block:
                    pending.add(block["toolUse"]["toolUseId"])
        else:
            for block in content:
                if isinstance(block, dict) and "toolResult" in block:
                    pending.discard(block["toolResult"]["toolUseId"])
    assert not pending, f"dangling toolUse id(s) with no matching toolResult: {pending}"


def _assert_alternates(messages: list[dict[str, Any]]) -> None:
    """GH-147 AC3: no two consecutive entries in ``messages`` may share a
    ``role`` — the exact shape Bedrock's Converse API rejects outright.
    Stricter than ``_assert_no_dangling_tool_use``: a message ending its own
    toolUse/toolResult pairing cleanly can still violate this (e.g. two
    successive plain 'user' turns), which is exactly the RT-004 gap a
    tail-only ``!= "assistant"`` check missed."""
    for prev, cur in zip(messages, messages[1:]):
        assert prev.get("role") != cur.get("role"), (
            f"two consecutive {cur.get('role')!r} messages: {prev!r} then {cur!r}"
        )


class _DeferredPayload(BaseModel):
    value: str = "deferred-done"


async def _fast_job() -> _DeferredPayload:
    await asyncio.sleep(0)
    return _DeferredPayload(value="deferred-done")


success_tools = ToolSet()
failure_tools = ToolSet()


@success_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def deferred_success_tool() -> DeferredResult:
    """Deferred tool whose handle resolves successfully."""
    return DeferredResult(handle=_fast_job())


@failure_tools.tool(tier=1, long_running=True, tool_timeout_override=0.05)
async def deferred_timeout_tool() -> DeferredResult:
    """Deferred tool whose handle never resolves — forces a timeout."""
    return DeferredResult(handle=asyncio.sleep(9999))


SUCCESS_REGISTRY = ToolRegistry([success_tools], {})
FAILURE_REGISTRY = ToolRegistry([failure_tools], {})


async def test_deferred_success_leaves_no_dangling_tool_use() -> None:
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("deferred_success_tool", {}))

    await _run_worker(store, record, model, SUCCESS_REGISTRY)

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.COMPLETED

    rec = store.get(task_id)
    assert rec is not None
    _assert_no_dangling_tool_use(rec.messages)

    # The matching toolResult must be a real success result, not a placeholder —
    # and must appear as the message immediately after the assistant toolUse
    # fold. RT-004: that toolResult append is itself a 'user' turn, so it is
    # followed by a synthetic assistant bridge turn (GH-147 AC3) — the
    # transcript must never be left ending on 'user'.
    last_three = rec.messages[-3:]
    assert last_three[0]["role"] == "assistant"
    tool_use_id = last_three[0]["content"][-1]["toolUse"]["toolUseId"]
    assert last_three[1]["role"] == "user"
    result_block = last_three[1]["content"][0]["toolResult"]
    assert result_block["toolUseId"] == tool_use_id
    assert result_block["status"] == "success"
    assert last_three[2]["role"] == "assistant"
    _assert_alternates(rec.messages)


async def test_deferred_timeout_leaves_no_dangling_tool_use() -> None:
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("deferred_timeout_tool", {}))

    await _run_worker(store, record, model, FAILURE_REGISTRY)

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.FAILED

    rec = store.get(task_id)
    assert rec is not None
    _assert_no_dangling_tool_use(rec.messages)

    last_three = rec.messages[-3:]
    assert last_three[0]["role"] == "assistant"
    tool_use_id = last_three[0]["content"][-1]["toolUse"]["toolUseId"]
    assert last_three[1]["role"] == "user"
    result_block = last_three[1]["content"][0]["toolResult"]
    assert result_block["toolUseId"] == tool_use_id
    assert result_block["status"] == "error"
    # SI-2: fixed generic string only, never raw exception/asyncio text.
    assert "asyncio" not in result_block["content"][0]["text"]
    assert last_three[2]["role"] == "assistant"
    _assert_alternates(rec.messages)


async def test_deferred_success_transcript_replayable_on_next_context_turn() -> None:
    """End-to-end: context_messages() for the next task on the same contextId
    must not hand back a transcript ending on a dangling assistant toolUse —
    the exact shape Converse-API-shaped backends (Bedrock) reject outright."""
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id
    context_id = record.task.context_id

    model = FakeModelClient().script(tool_call("deferred_success_tool", {}))
    await _run_worker(store, record, model, SUCCESS_REGISTRY)
    await _wait_for_state(store, task_id)

    replayed = store.context_messages(context_id, _IDENTITY)
    assert replayed, "expected non-empty context_messages for a terminal task"
    _assert_no_dangling_tool_use(list(replayed))

    # RT-004: a bare `replayed[-1]["role"] != "assistant"` check locks in the
    # WRONG invariant — the fix makes the stored transcript end on a
    # synthetic 'assistant' bridge turn precisely so contextId continuation
    # is safe. The invariant that actually matters is what routes/a2a.py's
    # _create_task_record does with `replayed`: extend record.messages with
    # it verbatim, then append a new 'user' turn. Mirror that exact append
    # and assert the resulting transcript fully alternates — this is what
    # catches a transcript ending on 'user' (which would collide with the
    # appended 'user' turn), not just an 'assistant' tail.
    continued = list(replayed) + [{"role": "user", "content": [{"text": "turn two"}]}]
    _assert_alternates(continued)
