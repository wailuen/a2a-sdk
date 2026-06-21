"""GH-87: first-class long-running / deferred-task delivery.

Tests:
1. test_long_running_flag_accepted: @tool(long_running=True, tool_timeout_override=600)
   decorator records correct fields on ToolDecl.
2. test_deferred_working_state: while the background awaiter is running, the A2A
   task record stays WORKING (not COMPLETED/FAILED).
3. test_deferred_resolves_to_completed: tool returns DeferredResult whose handle
   yields a plain-value result → task transitions to COMPLETED with an artifact.
4. test_deferred_timeout_fails: tool returns DeferredResult(asyncio.sleep(9999))
   with tool_timeout_override=0.1 → task transitions to FAILED with a timeout
   error message.
5. test_ag_ui_deferred_tool_call_result: AG-UI SSE stream for a deferred tool
   must contain TOOL_CALL_RESULT closing the tool-call lifecycle (RT-W025-003).

No unittest.mock.patch / MagicMock / AsyncMock. Uses FakeModelClient and the
real run_task_worker + InMemoryTaskStore.

SI-2: timeout / failure error messages are fixed strings — no credential or
user-supplied content is echoed in any assertion.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredEvent, DeferredResult
from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import run_task_worker, new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call


# ── shared helpers ──

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
    *,
    policies: LoopPolicies | None = None,
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
        policies=policies or LoopPolicies(),
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


# ── tool fixtures ──

deferred_tools = ToolSet()
timeout_tools = ToolSet()


class _DeferredResult(BaseModel):
    """Plain result model yielded by the deferred handle."""
    value: str = "deferred-done"


async def _fast_job() -> _DeferredResult:
    """Awaitable that resolves quickly to a plain result."""
    await asyncio.sleep(0)
    return _DeferredResult(value="deferred-done")


@deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def long_running_tool() -> DeferredResult:
    """Tool that returns a DeferredResult immediately."""
    return DeferredResult(handle=_fast_job(), estimated_seconds=1.0)


@timeout_tools.tool(tier=1, long_running=True, tool_timeout_override=0.05)
async def slow_tool() -> DeferredResult:
    """Tool that returns a DeferredResult whose handle never resolves."""
    return DeferredResult(handle=asyncio.sleep(9999))


DEFERRED_REGISTRY = ToolRegistry([deferred_tools], {})
TIMEOUT_REGISTRY = ToolRegistry([timeout_tools], {})


# ── tests ──


def test_long_running_flag_accepted() -> None:
    """@tool(long_running=True, tool_timeout_override=600) must set ToolDecl fields."""
    flag_tools = ToolSet()

    @flag_tools.tool(tier=1, long_running=True, tool_timeout_override=600.0)
    async def my_long_tool() -> str:
        """A long-running tool."""
        return "ok"

    registry = ToolRegistry([flag_tools], {})
    entry = registry.get("my_long_tool")
    assert entry is not None, "tool not found in registry"
    assert entry.decl.long_running is True, "long_running must be True"
    assert entry.decl.tool_timeout_override == 600.0, (
        f"expected tool_timeout_override=600.0, got {entry.decl.tool_timeout_override!r}"
    )


@pytest.mark.asyncio
async def test_deferred_working_state() -> None:
    """While background awaiter is running, the A2A task state must be WORKING."""
    # Use a barrier to hold the handle until we can observe the WORKING state.
    barrier: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    async def blocking_job() -> _DeferredResult:
        await barrier
        return _DeferredResult(value="after-barrier")

    barrier_tools = ToolSet()

    @barrier_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
    async def barrier_tool() -> DeferredResult:
        """Returns a DeferredResult that blocks until the barrier is released."""
        return DeferredResult(handle=blocking_job())

    registry = ToolRegistry([barrier_tools], {})
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(
        tool_call("barrier_tool", {}),
    )

    # Run the worker in the background — it will launch the deferred background
    # task and then return (loop exits after yielding DeferredEvent).
    worker = asyncio.get_running_loop().create_task(
        _run_worker(store, record, model, registry)
    )

    # Poll until the task reaches WORKING state (no timing dependency).
    await _wait_for_state(store, task_id, states=("working",))

    # While barrier is held, the task MUST be in WORKING state.
    rec = store.get(task_id)
    assert rec is not None
    state_while_waiting = rec.task.status.state
    assert state_while_waiting == TaskState.WORKING, (
        f"expected WORKING during deferred await, got {state_while_waiting!r}"
    )

    # Release the barrier and wait for worker to finish.
    barrier.set_result(None)
    await worker

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.COMPLETED, (
        f"expected COMPLETED after barrier released, got {final_state!r}"
    )


@pytest.mark.asyncio
async def test_deferred_resolves_to_completed() -> None:
    """Tool returning DeferredResult(handle) transitions task to COMPLETED with artifact."""
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(
        tool_call("long_running_tool", {}),
    )

    await _run_worker(store, record, model, DEFERRED_REGISTRY)

    # The run_task_worker returns after DeferredEvent is yielded; the background
    # task completes asynchronously.  Wait for COMPLETED.
    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.COMPLETED, (
        f"expected COMPLETED after deferred handle resolved, got {final_state!r}"
    )

    # Artifact must be present.
    rec = store.get(task_id)
    assert rec is not None
    assert rec.task.artifacts, "expected at least one artifact on COMPLETED task"


@pytest.mark.asyncio
async def test_deferred_timeout_fails() -> None:
    """DeferredResult(asyncio.sleep(9999)) with tool_timeout_override=0.05 → FAILED."""
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(
        tool_call("slow_tool", {}),
    )

    await _run_worker(store, record, model, TIMEOUT_REGISTRY)

    # Wait for the background awaiter to time out and transition to FAILED.
    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.FAILED, (
        f"expected FAILED after deferred job timeout, got {final_state!r}"
    )

    # The error field must be set and contain the fixed "timed out" phrase
    # (SI-2: no credential / user content echoed).
    rec = store.get(task_id)
    assert rec is not None
    error = rec.task.status.error
    assert error is not None, "expected WireError on FAILED task"
    assert "timed out" in error.message.lower(), (
        f"expected 'timed out' in error.message, got {error.message!r}"
    )
    # SI-2 guard: no sensitive path segments, no raw input in the error message.
    assert "asyncio" not in error.message, "error message must not expose internal exception text"


# ── AG-UI integration test (RT-W025-003) ──

def _sse_frames(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_ag_ui_deferred_tool_call_result(tmp_path) -> None:
    """RT-W025-003: AG-UI SSE stream for a deferred tool must contain a
    TOOL_CALL_RESULT frame that closes the tool-call lifecycle opened by the
    TOOL_CALL_START / TOOL_CALL_ARGS / TOOL_CALL_END emitted before the loop
    yielded the DeferredEvent.

    Flow:
      FakeModelClient → tool_call("long_running_tool") → DeferredEvent →
      background awaiter resolves → ToolResultEvent published →
      _RunMapper maps it to TOOL_CALL_RESULT → appears in SSE stream.
    """
    from agent_sdk import BaseAgentSettings
    from agent_sdk.app import Agent

    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="deferred-ag-ui-test"
    )
    # Build an agent that includes the deferred tool set.
    fake = FakeModelClient().script(tool_call("long_running_tool", {}))
    app = Agent(
        settings=settings,
        persona="test agent",
        toolsets=[deferred_tools],
        model_client=fake,
    ).build_app()

    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            body = {
                "threadId": "t-deferred",
                "runId": "r-deferred",
                "messages": [{"id": "m1", "role": "user", "content": "run long job"}],
                "state": {},
                "tools": [],
                "context": [],
                "forwardedProps": {},
            }
            r = await client.post("/ag-ui/run", json=body)
            assert r.status_code == 200, r.text
            frames = _sse_frames(r.text)

    types = [f["type"] for f in frames]

    # AG-UI lifecycle: RUN_STARTED always first, exactly one terminal frame last.
    assert types[0] == "RUN_STARTED", f"expected RUN_STARTED first, got {types[:3]}"
    assert types[-1] in ("RUN_FINISHED", "RUN_ERROR"), (
        f"expected terminal frame last, got {types[-3:]}"
    )
    assert types[-1] == "RUN_FINISHED", (
        f"expected RUN_FINISHED (not RUN_ERROR), got {types[-1]!r}; frames={frames[-3:]}"
    )

    # RT-W025-003 core assertion: TOOL_CALL_RESULT must be present to close the
    # tool-call lifecycle opened by TOOL_CALL_START.
    assert "TOOL_CALL_START" in types, f"expected TOOL_CALL_START in stream; got {types}"
    assert "TOOL_CALL_RESULT" in types, (
        "RT-W025-003: TOOL_CALL_RESULT missing — AG-UI tool-call lifecycle not closed "
        f"for deferred tool. Stream types: {types}"
    )

    # The toolCallId on TOOL_CALL_RESULT must match the one from TOOL_CALL_START.
    start_frame = next(f for f in frames if f["type"] == "TOOL_CALL_START")
    result_frame = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")
    assert result_frame["toolCallId"] == start_frame["toolCallId"], (
        f"TOOL_CALL_RESULT.toolCallId {result_frame['toolCallId']!r} must match "
        f"TOOL_CALL_START.toolCallId {start_frame['toolCallId']!r}"
    )
    # The messageId on TOOL_CALL_RESULT must be a fresh UUID (never derived from toolCallId).
    assert result_frame["messageId"] != result_frame["toolCallId"], (
        "TOOL_CALL_RESULT.messageId must be a fresh UUID, not a copy of toolCallId"
    )

    app.state.credential_store.close()
