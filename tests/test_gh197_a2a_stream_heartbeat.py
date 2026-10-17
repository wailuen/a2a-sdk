"""GH-197: A2A SSE streams send ``: ping`` comment frames while a long tool
runs, so short-timeout clients do not disconnect."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.common import sse
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import reply, tool_call

pytestmark = pytest.mark.asyncio

gate: dict[str, asyncio.Event] = {}
gh197_tools = ToolSet()


class _In(BaseModel):
    pass


@gh197_tools.tool(tier=1)
async def gh197_slow_tool(inp: _In) -> dict[str, Any]:
    """Waits until the test releases it."""
    await gate["release"].wait()
    return {"done": True}


@pytest.fixture
def hb_app(settings, fake_model, monkeypatch):
    monkeypatch.setattr(sse, "STREAM_HEARTBEAT_SECONDS", 0.05)
    gate["release"] = asyncio.Event()
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [gh197_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def hb_client(hb_app):
    async with hb_app.router.lifespan_context(hb_app):
        _, token = hb_app.state.auth.api_keys.mint("gh197", admin=True)
        hb_app.state.gh197_token = token
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=hb_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def _msg(text: str) -> dict[str, Any]:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def _release_later(delay: float = 0.4) -> None:
    await asyncio.sleep(delay)
    gate["release"].set()


async def test_message_stream_sends_heartbeats_and_keeps_frames(hb_client, fake_model):
    fake_model.script(tool_call("gh197_slow_tool", {}), reply("all done"))
    releaser = asyncio.create_task(_release_later())
    r = await hb_client.post("/v1/message:stream", json=_msg("go"))
    await releaser
    assert r.status_code == 200
    text = r.text
    assert text.count(": ping\n\n") >= 2
    assert text.startswith("data: ")
    assert '"kind":"task"' in text.splitlines()[0].replace(" ", "")
    frames = [json.loads(ln[6:]) for ln in text.splitlines() if ln.startswith("data: ")]
    assert frames[-1].get("final") is True
    assert frames[-1]["status"]["state"] == "completed"


async def test_subscribe_sends_heartbeats(hb_client, fake_model):
    fake_model.script(tool_call("gh197_slow_tool", {}), reply("all done"))
    r = await hb_client.post("/v1/message:send", json={**_msg("go"), "configuration": {"blocking": False}})
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    releaser = asyncio.create_task(_release_later())
    r2 = await hb_client.post(f"/v1/tasks/{task_id}:subscribe")
    await releaser
    assert r2.status_code == 200
    assert r2.text.count(": ping\n\n") >= 2
    frames = [json.loads(ln[6:]) for ln in r2.text.splitlines() if ln.startswith("data: ")]
    assert frames[-1].get("final") is True


async def test_disconnect_during_wait_releases_subscription(hb_app, hb_client, fake_model):
    fake_model.script(tool_call("gh197_slow_tool", {}), reply("all done"))
    body = json.dumps(_msg("go")).encode()
    token = hb_app.state.gh197_token
    sent_body = False
    disconnect = asyncio.Event()
    chunks: list[bytes] = []
    got_ping = asyncio.Event()

    async def receive() -> dict:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
            if b": ping" in chunks[-1]:
                got_ping.set()

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/v1/message:stream",
        "raw_path": b"/v1/message:stream", "query_string": b"",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"content-type", b"application/json"),
        ],
        "server": ("test", 80), "client": ("c", 1), "root_path": "",
    }
    req = asyncio.create_task(hb_app(scope, receive, send))
    await asyncio.wait_for(got_ping.wait(), 3)
    store = hb_app.state.task_store
    assert any(rec.subscriptions for rec in store._records.values())
    disconnect.set()
    await asyncio.wait_for(req, 3)
    await asyncio.sleep(0.1)
    assert not any(rec.subscriptions for rec in store._records.values())
    gate["release"].set()
