"""RT-B-001: tasks_cancel must cancel record.bg_task, not just record.worker.

Root cause: a long_running (GH-87) tool's DeferredEvent handoff exits
run_task_worker's for-loop immediately, leaving record.worker done and only
record.bg_task (the background awaiter in
``agent_sdk/agent/runner.py::_run_deferred_background``) still running.
``tasks_cancel`` only cancelled ``record.worker``, so a task cancelled while
its deferred tool call was still in flight left the background awaiter free
to keep running: it later resolves the tool call, and its own
``repair_dangling_tool_use(..., overrides={tool_call_id: (real_result,
"success")})`` call becomes a silent no-op (the transcript tail is no longer
a dangling assistant toolUse turn — ``tasks_cancel``'s own repair already
closed it out), and it flips the already-CANCELED task back to COMPLETED —
after the client already received a 200 response reporting it canceled.

Two independent fixes are exercised here:

1. ``tasks_cancel`` (``agent_sdk/routes/a2a.py``) now cancels
   ``record.bg_task`` alongside ``record.worker``, mirroring
   ``InMemoryTaskStore.evict``.
2. ``_run_deferred_background`` (``agent_sdk/agent/runner.py``) now bails out
   with an early return the instant it observes
   ``record.task.status.state`` already in ``TERMINAL_STATES`` — a backstop
   for the case where ``asyncio.Task.cancel()`` loses the race against an
   already-resolving handle, so the awaiter can never revert a terminal task
   or publish a second terminal frame onto streams ``tasks_cancel`` already
   closed.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredEvent, DeferredResult
from agent_sdk.agent.registry import ToolSet
from agent_sdk.agent.runner import (
    StreamItem,
    _run_deferred_background,
    new_task,
    repair_dangling_tool_use,
)
from agent_sdk.auth.identity import Identity
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import TaskState, TaskStatus
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import tool_call

pytestmark = pytest.mark.asyncio

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── AC1 (HTTP end-to-end): cancel with an in-flight deferred tool ──────────


class _Gate:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()


gate = _Gate()

rtb001_cancel_tools = ToolSet()


@rtb001_cancel_tools.tool(
    tier=1, name="rtb001_gated_deferred", long_running=True, tool_timeout_override=30.0
)
async def rtb001_gated_deferred() -> DeferredResult:
    """Hands off to the runner's background awaiter; the handle blocks until
    the test releases it, simulating a tool call still in flight when the
    task is cancelled."""

    async def _job() -> dict[str, Any]:
        gate.started.set()
        await gate.release.wait()
        return {"ok": True}

    return DeferredResult(handle=_job())


@pytest.fixture
def reset_gate() -> _Gate:
    gate.started = asyncio.Event()
    gate.release = asyncio.Event()
    return gate


@pytest.fixture
def rtb001_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rtb001_cancel_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def rtb001_client(rtb001_app):
    async with rtb001_app.router.lifespan_context(rtb001_app):
        _, token = rtb001_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rtb001_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def send_body(text: str) -> dict[str, Any]:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def test_cancel_with_in_flight_deferred_tool_never_reverts(
    rtb001_client, fake_model, rtb001_app, reset_gate
):
    fake_model.script(tool_call("rtb001_gated_deferred", {}))

    r = await rtb001_client.post("/v1/message:send", json=send_body("go"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    await asyncio.wait_for(gate.started.wait(), timeout=2.0)

    record = rtb001_app.state.task_store.get(task_id)
    assert record is not None
    assert record.bg_task is not None, "long_running tool must launch the background awaiter"
    assert not record.bg_task.done()

    c = await rtb001_client.post(f"/v1/tasks/{task_id}:cancel")
    assert c.status_code == 200, c.text
    assert c.json()["status"]["state"] == "canceled"

    # RT-B-001 fix 1: tasks_cancel must cancel the background awaiter, not
    # just the (already-exited) worker.
    await asyncio.sleep(0)  # let the cancellation request reach the awaiter
    assert record.bg_task.cancelled() or record.bg_task.done(), (
        "record.bg_task was never cancelled by tasks_cancel"
    )

    # Even if the underlying job goes on to "succeed" regardless, the task
    # must never come back from CANCELED after the 200 response.
    gate.release.set()
    await asyncio.sleep(0.05)

    got = await rtb001_client.get(f"/v1/tasks/{task_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"]["state"] == "canceled", (
        "a deferred tool that later succeeds must never revert an "
        f"already-CANCELED task; got {body['status']['state']!r}"
    )
    assert not body.get("artifacts"), (
        "the background awaiter must never publish a terminal artifact for "
        "a call this task has already cancelled"
    )

    # Transcript must never be contradicted: the synthetic cancelled
    # toolResult tasks_cancel wrote stays the ONLY toolResult for this call.
    result_blocks = [
        block["toolResult"]
        for message in record.messages
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolResult" in block
    ]
    assert len(result_blocks) == 1, (
        f"expected exactly one toolResult for the cancelled call, got {result_blocks!r}"
    )
    assert result_blocks[0]["status"] == "error", result_blocks[0]


# ── AC2 (direct): the awaiter never reverts an already-terminal task ───────


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    return store.create(task, _IDENTITY)


async def test_deferred_background_never_reverts_already_terminal_task() -> None:
    """Direct exercise of the second, independent guard: even when the
    deferred handle DOES resolve successfully, ``_run_deferred_background``
    must bail out the instant it observes the task already terminal — the
    backstop for the case where ``asyncio.Task.cancel()`` loses the race
    against an already-resolving handle. Reproduces the exact post-cancel
    shape ``tasks_cancel`` leaves behind before handing control to the
    awaiter."""
    store = InMemoryTaskStore()
    record = _make_record(store)
    record.messages.append(
        {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": "call-1", "name": "rtb001_gated_deferred", "input": {}}}
            ],
        }
    )
    store.subscribe(record.task.id)

    # Simulate exactly what tasks_cancel already committed before this
    # awaiter gets a chance to run its success path.
    record.task.status = TaskStatus(state=TaskState.CANCELED, timestamp=_now_iso())
    repair_dangling_tool_use(
        record, default_content=[{"text": "tool call cancelled"}], store=store
    )
    store.publish(record.task.id, StreamItem(frame={"final": True}, event=None, final=True))
    store.close_streams(record.task.id)

    async def _resolves_immediately() -> dict[str, Any]:
        return {"ok": True}

    event = DeferredEvent(
        deferred=DeferredResult(handle=_resolves_immediately()),
        tool_name="rtb001_gated_deferred",
        tool_call_id="call-1",
        emits=None,
        timeout_seconds=5.0,
    )

    await _run_deferred_background(
        store=store, record=record, event=event, capabilities=_CAPABILITIES
    )

    assert record.task.status.state == TaskState.CANCELED, (
        "the background awaiter must never revert an already-terminal task, "
        f"even when its own handle resolves successfully; got "
        f"{record.task.status.state!r}"
    )
    assert not record.task.artifacts, (
        "no terminal artifact may be published for a call the task has "
        "already cancelled"
    )
