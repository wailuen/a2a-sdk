"""RT-B-204: ``tasks_cancel`` (routes/a2a.py) must publish its terminal
``StreamItem`` with a matching loop ``event``, not ``event=None``.

Every other terminal publisher in the SDK (``run_task_worker``'s two
terminal handlers, its ``else:`` clause, and
``_run_deferred_background._fail``) publishes a ``DoneEvent`` alongside the
A2A wire frame. AG-UI's ``_RunMapper`` (routes/ag_ui.py) maps ``.event``,
never ``.frame`` — ``_RunMapper.map(None)`` returns ``[]``. Before this fix,
a task cancelled through the A2A route while an AG-UI subscriber was
streaming it broke out of the frame loop with ``terminal_sent`` still
``False`` and fell through to the generic ``RUN_ERROR: "stream ended
unexpectedly"`` fallback — a misleading error for a deliberate, successful
cancellation. The A2A SSE consumer of the same task got a correct
``final:true`` status frame throughout, so the two transports disagreed
about what happened.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import tool_call

from .conftest import sse_frames

pytestmark = pytest.mark.asyncio


# ── a tool that blocks until the test releases it ──────────────────────────


class _Signals:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()


signals = _Signals()

rtb204_tools = ToolSet()


class SlowInput(BaseModel):
    pass


@rtb204_tools.tool(tier=1)
async def rtb204_slow_tool(inp: SlowInput) -> dict[str, Any]:
    """Parks forever (until released) — keeps the task WORKING so the test
    can cancel it while an AG-UI stream is still subscribed."""
    signals.started.set()
    await signals.release.wait()
    return {"done": True}


@pytest.fixture
def reset_signals() -> _Signals:
    signals.started = asyncio.Event()
    signals.release = asyncio.Event()
    return signals


@pytest.fixture
def rtb204_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rtb204_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def rtb204_client(rtb204_app):
    async with rtb204_app.router.lifespan_context(rtb204_app):
        _, token = rtb204_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rtb204_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def run_body(text: str = "hello", **extra) -> dict:
    return {
        "threadId": uuid.uuid4().hex,
        "runId": uuid.uuid4().hex,
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


async def test_agui_stream_gets_cancellation_frame_not_stream_ended_unexpectedly(
    rtb204_client, fake_model, reset_signals
):
    fake_model.script(tool_call("rtb204_slow_tool", {}))

    run_task = asyncio.create_task(
        rtb204_client.post("/ag-ui/run", json=run_body("go slow"))
    )
    try:
        await asyncio.wait_for(reset_signals.started.wait(), timeout=2.0)

        # RT-B-204 regression coverage relies on this GET to resolve the
        # task id the AG-UI route created internally — no id is echoed on
        # any AG-UI frame.
        r_list = await rtb204_client.get("/v1/tasks")
        assert r_list.status_code == 200, r_list.text
        tasks = r_list.json()["tasks"]
        assert len(tasks) == 1, tasks
        task_id = tasks[0]["id"]

        r_cancel = await rtb204_client.post(f"/v1/tasks/{task_id}:cancel")
        assert r_cancel.status_code == 200, r_cancel.text
        assert r_cancel.json()["status"]["state"] == "canceled"

        r_agui = await asyncio.wait_for(run_task, timeout=5.0)
    finally:
        if not run_task.done():
            run_task.cancel()

    assert r_agui.status_code == 200, r_agui.text
    frames = sse_frames(r_agui.text)
    types = [f["type"] for f in frames]

    terminal_types = [t for t in types if t in ("RUN_FINISHED", "RUN_ERROR")]
    assert terminal_types == ["RUN_ERROR"], types
    assert types[-1] == "RUN_ERROR"

    terminal_frame = frames[-1]
    assert terminal_frame["message"] == "task canceled", terminal_frame
    assert terminal_frame["message"] != "stream ended unexpectedly", terminal_frame
