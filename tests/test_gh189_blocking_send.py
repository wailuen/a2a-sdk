"""GH-189: ``configuration.blocking: true`` waits for a terminal or
interrupted state instead of being rejected (A2A v0.3.0 §7.1)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import reply, tool_call

from .conftest import wait_for_state
from .test_a2a import send_body

pytestmark = pytest.mark.asyncio

gate: dict[str, asyncio.Event] = {}
gh189_tools = ToolSet()


class _In(BaseModel):
    pass


@gh189_tools.tool(tier=1)
async def gh189_slow_tool(inp: _In) -> dict[str, Any]:
    """Waits until the test releases it."""
    await gate["release"].wait()
    return {"done": True}


@pytest.fixture
def bs_app(settings, fake_model):
    gate["release"] = asyncio.Event()
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [gh189_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def bs_client(bs_app):
    async with bs_app.router.lifespan_context(bs_app):
        _, token = bs_app.state.auth.api_keys.mint("gh189", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=bs_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def _blocking(body: dict, value: bool = True) -> dict:
    return {**body, "configuration": {"blocking": value}}


def _open_subs(app) -> int:
    from agent_sdk.routes.a2a import _a2a_streams

    return len(_a2a_streams(app))


async def test_blocking_returns_terminal_task_with_artifacts(bs_client, fake_model):
    fake_model.script(tool_call("demo_kpis", {"title": "T"}), reply("all done"))
    r = await bs_client.post("/v1/message:send", json=_blocking(send_body("hi")))
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"]["state"] == "completed"
    assert task["artifacts"]


async def test_blocking_interrupt_returns_input_required(bs_client, fake_model):
    fake_model.script(tool_call("publish_note", {"note": "hello"}), reply("published"))
    r = await bs_client.post(
        "/v1/message:send", json=_blocking(send_body("publish hello"))
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "input-required"


async def test_blocking_resume_waits_for_terminal(bs_client, fake_model):
    fake_model.script(tool_call("publish_note", {"note": "hello"}), reply("published"))
    r = await bs_client.post(
        "/v1/message:send", json=_blocking(send_body("publish hello"))
    )
    task_id = r.json()["id"]
    r = await bs_client.post(
        "/v1/message:send", json=_blocking(send_body("approved", task_id))
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "completed"


async def test_blocking_cap_returns_current_task_and_worker_continues(
    bs_client, bs_app, fake_model
):
    bs_app.state.settings.blocking_send_max_seconds = 0.1
    fake_model.script(tool_call("gh189_slow_tool", {}), reply("finished"))
    r = await bs_client.post("/v1/message:send", json=_blocking(send_body("go")))
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"]["state"] in ("submitted", "working")
    assert _open_subs(bs_app) == 0
    gate["release"].set()
    done = await wait_for_state(bs_client, task["id"])
    assert done["status"]["state"] == "completed"


async def test_blocking_resume_cap(bs_client, bs_app, fake_model):
    bs_app.state.settings.blocking_send_max_seconds = 0.1
    fake_model.script(
        tool_call("publish_note", {"note": "x"}),
        tool_call("gh189_slow_tool", {}),
        reply("finished"),
    )
    r = await bs_client.post("/v1/message:send", json=_blocking(send_body("p")))
    task_id = r.json()["id"]
    r = await bs_client.post(
        "/v1/message:send", json=_blocking(send_body("approved", task_id))
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] not in ("completed", "failed", "canceled")
    gate["release"].set()
    done = await wait_for_state(bs_client, task_id)
    assert done["status"]["state"] == "completed"


async def test_blocking_disconnect_leaks_no_subscription(bs_app, bs_client, fake_model):
    fake_model.script(tool_call("gh189_slow_tool", {}), reply("finished"))
    req = asyncio.create_task(
        bs_client.post("/v1/message:send", json=_blocking(send_body("go")))
    )
    await asyncio.sleep(0.2)
    assert _open_subs(bs_app) == 1
    req.cancel()
    with pytest.raises(asyncio.CancelledError):
        await req
    gate["release"].set()
    await asyncio.sleep(0.2)
    assert _open_subs(bs_app) == 0


@pytest.mark.parametrize("cfg", [{"blocking": False}, {}, None])
async def test_non_blocking_returns_immediate_snapshot(bs_client, fake_model, cfg):
    fake_model.script(tool_call("gh189_slow_tool", {}), reply("finished"))
    body = send_body("go")
    if cfg is not None:
        body = {**body, "configuration": cfg}
    r = await bs_client.post("/v1/message:send", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] in ("submitted", "working")
    gate["release"].set()
    await wait_for_state(bs_client, r.json()["id"])
