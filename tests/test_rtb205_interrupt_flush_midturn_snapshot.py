"""RT-B-205 (redteam, agent/runner.py review): pins the exact SHAPE of the
transcript ``set_task_status`` flushes via ``TaskStore.persist_messages`` on
an ``INTERRUPT_STATES`` transition (RT-B-104).

An interrupt is always raised from INSIDE the per-tool-call loop
(``agent/loop.py``), after that turn's assistant ``toolUse`` message has
already been folded into ``record.messages`` and BEFORE the matching
``toolResult`` is folded. So the transcript this flush captures is
guaranteed to end on a dangling assistant ``toolUse`` with no matching
``toolResult`` — a MID-TURN snapshot, not a turn-boundary one, and NOT
Converse-replayable as-is (the exact shape GH-150's repair helper exists to
close, which nothing calls on this path — see the ``InterruptEvent`` branch,
``agent/runner.py``, and ``TaskStore.persist_messages``'s own RT-B-104
docstring).

This does not regress correctness for the SDK's own in-memory store —
``context_messages()`` filters candidates on ``TERMINAL_STATES``, so an
interrupted task is never selected as a continuation candidate, and the
in-process resume path (``deliver_resume`` → the awaited future) never reads
back through ``persist_messages`` at all. It matters only for an external
durable ``TaskStore`` subclass that treats this flush as its own
resume-after-restart source: that subclass must repair the dangling
``toolUse`` tail itself (mirroring ``repair_dangling_tool_use``) before
handing the snapshot to a model, exactly as documented in
``TaskStore.persist_messages``'s docstring, DESIGN.md §5.2, and
docs/deployment.md.

This test locks the observed shape so the choice (documented mid-turn
snapshot vs. a future change restricting the flush to TERMINAL_STATES) can
never silently drift without a test failure calling it out.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.loop import LoopPolicies, ToolInterrupt
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _EmptyInput(BaseModel):
    pass


_rtb205_tools = ToolSet()


@_rtb205_tools.tool(tier=2, title="Interrupt Tool")
async def rtb205_interrupt_tool(inp: _EmptyInput) -> dict[str, Any]:
    """Always interrupts (non-auth reason → INPUT_REQUIRED)."""
    raise ToolInterrupt(reason="confirmation", message="confirm?")


_RTB205_REGISTRY = ToolRegistry([_rtb205_tools], {})


class _RecordingStore(InMemoryTaskStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.flushes: list[tuple[TaskState, list[Any]]] = []

    def persist_messages(self, record: TaskRecord) -> None:
        self.flushes.append(
            (record.task.status.state, copy.deepcopy(record.messages))
        )


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


@pytest.mark.asyncio
async def test_interrupt_persist_messages_flush_is_a_dangling_tooluse_snapshot() -> None:
    store = _RecordingStore()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("rtb205_interrupt_tool", {}))

    worker_task = asyncio.create_task(
        run_task_worker(
            store=store,
            record=record,
            model=model,
            registry=_RTB205_REGISTRY,
            adapters={},
            skills=None,
            system="test system prompt",
            capabilities=_CAPABILITIES,
            policies=LoopPolicies(),
        )
    )
    try:
        deadline = asyncio.get_running_loop().time() + 5.0
        while record.task.status.state != TaskState.INPUT_REQUIRED:
            assert asyncio.get_running_loop().time() < deadline, (
                f"task never reached input-required, stuck at "
                f"{record.task.status.state!r}"
            )
            await asyncio.sleep(0.01)

        interrupt_flushes = [
            messages for state, messages in store.flushes if state == TaskState.INPUT_REQUIRED
        ]
        assert interrupt_flushes, (
            "expected persist_messages to be flushed on the INPUT_REQUIRED "
            "transition (RT-B-104)"
        )
        snapshot = interrupt_flushes[-1]

        last = snapshot[-1]
        assert last["role"] == "assistant", (
            "RT-B-205: the interrupt-state flush must be a MID-TURN snapshot "
            f"ending on the assistant toolUse fold — got role {last.get('role')!r}"
        )
        tool_use_ids = {
            block["toolUse"]["toolUseId"]
            for block in last.get("content", [])
            if isinstance(block, dict) and "toolUse" in block
        }
        assert tool_use_ids, (
            "RT-B-205: expected at least one dangling toolUseId in the "
            "flushed snapshot's final message"
        )
        # No later message in the flushed snapshot supplies a matching
        # toolResult — this is exactly what makes the snapshot un-replayable
        # as-is against a Converse-API-shaped backend.
        result_ids: set[str] = set()
        for message in snapshot:
            for block in message.get("content", []):
                if isinstance(block, dict) and "toolResult" in block:
                    result_ids.add(block["toolResult"]["toolUseId"])
        assert tool_use_ids.isdisjoint(result_ids), (
            "RT-B-205: expected the dangling toolUseId(s) to have NO "
            "matching toolResult anywhere in the flushed snapshot"
        )
    finally:
        worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker_task
