"""RT-002: every deferred FAILED branch must close the AG-UI tool-call
lifecycle symmetrically with the SUCCESS branch.

``_run_deferred_background``'s SUCCESS path (RT-W025-003) publishes a
synthetic ``ToolResultEvent`` specifically so the AG-UI ``RunMapper`` emits a
``TOOL_CALL_RESULT`` that closes the tool-call lifecycle opened by the
``TOOL_CALL_START`` emitted before the loop yielded the ``DeferredEvent``. By
that same contract, every FAILED branch (timeout, cancel, generic exception,
and the post-resolution artifact-build failure) must do the same — otherwise
strict AG-UI clients receive a ``TOOL_CALL_START`` with no matching
``TOOL_CALL_RESULT`` whenever a deferred tool fails rather than succeeds.

These tests pin the fix at two levels:
  1. unit level — the raw ``StreamItem.event`` stream published by the
     background awaiter must contain a ``ToolResultEvent(ok=False, ...)``
     with the SAME ``tool_call_id``/``tool_name`` as the deferred event,
     published before the terminal ``DoneEvent(ok=False)``.
  2. AG-UI SSE level — the full ``/ag-ui/run`` stream for a deferred tool
     that times out must contain a ``TOOL_CALL_RESULT`` frame (mirroring
     ``test_gh87_deferred_task.py::test_ag_ui_deferred_tool_call_result``,
     which only covers the success path).

No unittest.mock.patch / MagicMock / AsyncMock. Uses FakeModelClient and the
real run_task_worker + InMemoryTaskStore.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

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

_timeout_tools = ToolSet()


@_timeout_tools.tool(tier=1, long_running=True, tool_timeout_override=0.05)
async def rt002_slow_tool() -> DeferredResult:
    """Deferred tool whose handle never resolves before the timeout."""
    return DeferredResult(handle=asyncio.sleep(9999))


_TIMEOUT_REGISTRY = ToolRegistry([_timeout_tools], {})


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


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
            raise AssertionError(f"task stuck in state {state!r} after {timeout}s")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_deferred_timeout_publishes_synthetic_tool_result_event() -> None:
    """RT-002: the timeout FAILED branch must publish a ToolResultEvent(ok=False)
    with the matching tool_call_id/tool_name BEFORE the terminal DoneEvent, so a
    TOOL_CALL_START opened earlier in the stream always gets a closing result."""
    store = InMemoryTaskStore()
    record = _make_record(store)
    task_id = record.task.id
    sub = store.subscribe(task_id)

    model = FakeModelClient().script(tool_call("rt002_slow_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_TIMEOUT_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )
    await _wait_for_state(store, task_id)

    events: list[Any] = []
    while True:
        item = await asyncio.wait_for(sub.get(), timeout=3.0)
        if item is None:  # close sentinel
            break
        events.append(item.event)

    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results, (
        "RT-002: no ToolResultEvent published on the deferred timeout FAILED "
        f"path; raw events were {[type(e).__name__ for e in events]}"
    )
    result_ev = tool_results[0]
    assert result_ev.ok is False
    assert result_ev.tool_name == "rt002_slow_tool"
    assert "unrenderable" not in (result_ev.error or "")

    done_events = [e for e in events if isinstance(e, DoneEvent)]
    assert done_events and done_events[-1].ok is False
    tool_result_index = events.index(tool_results[0])
    done_index = events.index(done_events[-1])
    assert tool_result_index < done_index, (
        "the synthetic ToolResultEvent must be published before the terminal "
        "DoneEvent so the tool-call lifecycle closes before the run terminates"
    )


def _sse_frames(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_ag_ui_deferred_timeout_closes_tool_call_lifecycle(tmp_path) -> None:
    """RT-002: a deferred tool that TIMES OUT must still produce a
    TOOL_CALL_RESULT in the AG-UI stream, closing the lifecycle opened by
    TOOL_CALL_START — mirroring the success-path assertion in
    test_gh87_deferred_task.py::test_ag_ui_deferred_tool_call_result."""
    from agent_sdk import BaseAgentSettings
    from agent_sdk.app import Agent

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="deferred-ag-ui-failed-test",
    )
    fake = FakeModelClient().script(tool_call("rt002_slow_tool", {}))
    app = Agent(
        settings=settings,
        persona="test agent",
        toolsets=[_timeout_tools],
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
                "threadId": "t-deferred-failed",
                "runId": "r-deferred-failed",
                "messages": [{"id": "m1", "role": "user", "content": "run slow job"}],
                "state": {},
                "tools": [],
                "context": [],
                "forwardedProps": {},
            }
            r = await client.post("/ag-ui/run", json=body)
            assert r.status_code == 200, r.text
            frames = _sse_frames(r.text)

        app.state.credential_store.close()

    types = [f["type"] for f in frames]

    assert types[0] == "RUN_STARTED", f"expected RUN_STARTED first, got {types[:3]}"
    assert types[-1] == "RUN_ERROR", (
        f"expected terminal RUN_ERROR for a failed deferred tool, got {types[-1]!r}"
    )
    assert "TOOL_CALL_START" in types, f"expected TOOL_CALL_START in stream; got {types}"
    assert "TOOL_CALL_RESULT" in types, (
        "RT-002: TOOL_CALL_RESULT missing on the deferred FAILED path — AG-UI "
        f"tool-call lifecycle not closed. Stream types: {types}"
    )

    start_frame = next(f for f in frames if f["type"] == "TOOL_CALL_START")
    result_frame = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")
    assert result_frame["toolCallId"] == start_frame["toolCallId"]
    assert "timed out" in result_frame["content"].lower()
