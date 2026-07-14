"""Redteam follow-up (RT-002), applied consistently to run_task_worker: the
SAME broad-try shape that _run_deferred_background's success path had also
covers run_task_worker's own terminal DoneEvent(ok=True) publish. If that
publish raises AFTER _set_status(COMPLETED) already committed the state
in-memory (e.g. a persistent TaskStore whose publish() does a durable write
that fails), the outer except handler re-enters the FAILED path and
publishes a duplicate, ok=False terminal frame — flipping an already-decided
COMPLETED task (with its already-delivered artifact still attached) back to
FAILED.

Fix: the terminal publish for a DoneEvent now runs in the try's `else:`
clause — outside the try body — so a failure there is not caught by the
except handlers and cannot re-trigger the FAILED path a second time.

No unittest.mock/MagicMock — a real InMemoryTaskStore subclass whose
publish() raises exactly once, on the first final=True DoneEvent(ok=True)
frame, driven through the real run_task_worker.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.events import DoneEvent
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import StreamItem, new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _GoodResult(BaseModel):
    data_type: str = "sync_terminal_result"
    value: str = "ok"


_sync_tools = ToolSet()


@_sync_tools.tool(tier=1, emits=_GoodResult)
async def sync_terminal_tool() -> _GoodResult:
    """Synchronous tool that emits an artifact before the run completes."""
    return _GoodResult()


_REGISTRY = ToolRegistry([_sync_tools], {})


class _FirstSuccessfulDoneEventPublishExplodes(InMemoryTaskStore):
    """Simulates a durable-store write failure on the SINGLE publish() call
    that carries the real, successful terminal DoneEvent frame. Only the
    first matching call raises, so a test can distinguish a correctly
    suppressed duplicate from a genuinely repeated terminal publish."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._raised = False

    def publish(self, task_id: str, event: Any) -> None:
        if (
            not self._raised
            and isinstance(event, StreamItem)
            and event.final
            and isinstance(event.event, DoneEvent)
            and event.event.ok
        ):
            self._raised = True
            raise RuntimeError("simulated durable publish failure on terminal frame")
        super().publish(task_id, event)


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


@pytest.mark.asyncio
async def test_terminal_publish_failure_does_not_flip_completed_task_to_failed() -> None:
    store = _FirstSuccessfulDoneEventPublishExplodes()
    record = _make_record(store)

    model = FakeModelClient().script(tool_call("sync_terminal_tool", {}), reply("finished"))

    with pytest.raises(RuntimeError):
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

    assert record.task.status.state == TaskState.COMPLETED, (
        "a publish() failure on the already-decided successful terminal "
        f"DoneEvent must not flip the task back to FAILED, got {record.task.status.state!r}"
    )
    assert record.task.artifacts, "COMPLETED task must retain its already-delivered artifact"
