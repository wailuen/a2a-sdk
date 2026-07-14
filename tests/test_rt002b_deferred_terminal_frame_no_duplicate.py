"""Redteam follow-up (RT-002): _run_deferred_background's success-path guard
must not let a post-publish failure trigger a SECOND terminal frame.

Before the fix, the try around the deferred SUCCESS path wrapped not only
build_artifact()/.wire()/the artifacts append, but also the terminal
_set_status(COMPLETED), the final DoneEvent(ok=True) publish, AND
store.close_streams(). If close_streams() raised AFTER the artifact, the
ok=True ToolResultEvent, and the ok=True DoneEvent were already published
(e.g. a persistent TaskStore doing a durable write in close_streams that
fails), the except branch called _fail(), which published a SECOND terminal
DoneEvent(ok=False) + a SECOND ToolResultEvent(ok=False) and flipped the
already-COMPLETED task to FAILED — while the artifact stayed on the record.
That is a double-terminal-frame protocol violation and a FAILED task
retaining an artifact that was, in fact, delivered.

Fix: the success-path try now covers only build_artifact()/.wire()/the
artifacts append. _set_status(COMPLETED) and the terminal publishes/
close_streams run afterward, unguarded — a failure there propagates as an
ordinary background-task exception instead of re-entering the FAILED path.

No unittest.mock/MagicMock — a real InMemoryTaskStore subclass whose
close_streams() raises, driven through the real run_task_worker.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import DoneEvent, ToolResultEvent
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _GoodResult(BaseModel):
    data_type: str = "terminal_frame_result"
    value: str = "ok"


async def _job() -> _GoodResult:
    await asyncio.sleep(0)
    return _GoodResult()


_deferred_tools = ToolSet()


@_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def terminal_frame_tool() -> DeferredResult:
    """Deferred tool whose handle resolves cleanly."""
    return DeferredResult(handle=_job())


_REGISTRY = ToolRegistry([_deferred_tools], {})


class _CloseStreamsExplodes(InMemoryTaskStore):
    """Simulates a persistent-store close_streams() failure AFTER every
    prior publish on the success path already succeeded."""

    def close_streams(self, task_id: str) -> None:
        raise RuntimeError("simulated durable close_streams failure")


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


@pytest.mark.asyncio
async def test_close_streams_failure_after_success_does_not_duplicate_terminal_frame() -> None:
    store = _CloseStreamsExplodes()
    record = _make_record(store)
    task_id = record.task.id
    sub = store.subscribe(task_id)

    model = FakeModelClient().script(tool_call("terminal_frame_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    deadline = asyncio.get_running_loop().time() + 5.0
    while record.task.status.state not in (TaskState.COMPLETED, TaskState.FAILED):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("task never reached a terminal state")
        await asyncio.sleep(0.02)

    assert record.task.status.state == TaskState.COMPLETED, (
        "a close_streams() failure AFTER the real terminal frame was already "
        f"published must not flip the task to FAILED, got {record.task.status.state!r}"
    )
    assert record.task.artifacts, "COMPLETED task must retain its delivered artifact"

    # Retrieve the background task's exception deterministically rather than
    # letting it surface as an "unretrieved task exception" during GC.
    assert record.bg_task is not None
    with pytest.raises(RuntimeError):
        await record.bg_task

    events: list[Any] = []
    while True:
        try:
            item = await asyncio.wait_for(sub.get(), timeout=0.2)
        except asyncio.TimeoutError:
            break
        events.append(item.event)

    done_events = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done_events) == 1, f"expected exactly one DoneEvent, got {done_events}"
    assert done_events[0].ok is True

    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tool_results) == 1, f"expected exactly one ToolResultEvent, got {tool_results}"
    assert tool_results[0].ok is True
