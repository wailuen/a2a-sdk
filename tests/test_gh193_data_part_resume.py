"""GH-193: a resume of an interrupt may carry exactly one DataPart.
Ruling: https://github.com/wailuen/a2a-sdk/issues/193#issuecomment-6229360550"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk import Agent, BaseAgentSettings
from agent_sdk.agent.loop import ToolInterrupt
from agent_sdk.agent.registry import ToolSet
from agent_sdk.contrib.action_gate.gate import Outcome, parse_decision
from agent_sdk.testing import reply, tool_call

pytestmark = pytest.mark.asyncio

tools = ToolSet()
received: list[Any] = []


class NoInput(BaseModel):
    pass


async def _handler(value: Any) -> dict[str, Any]:
    received.append(value)
    return {"answered": True}


@tools.tool(tier=1)
async def ask(inp: NoInput) -> dict[str, Any]:
    """Pause for structured input."""
    raise ToolInterrupt(
        "need",
        "more?",
        response_schema={"type": "object"},
        resume_handler=_handler,
    )


class Model:
    async def converse(self, *, system, messages, tools, max_tokens=4096, tool_choice="auto"):
        done = any(
            isinstance(b, dict) and "toolResult" in b
            for m in messages
            for b in (m.get("content") or [])
        )
        return reply("done") if done else tool_call("ask", {})


@pytest.fixture
def app(tmp_path):
    received.clear()
    settings = BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="g193")
    agent = Agent(
        settings=settings,
        persona="g193",
        skills_dir=Path(__file__).parent.parent / "agent_sdk" / "example" / "skills",
        toolsets=[tools],
        model_client=Model(),
    )
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


def _body(parts: list[dict], task_id: str | None = None) -> dict:
    msg: dict[str, Any] = {"role": "user", "parts": parts, "messageId": uuid.uuid4().hex}
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


TEXT = {"kind": "text", "text": "go"}


async def _interrupted(c) -> str:
    r = await c.post("/v1/message:send", json=_body([TEXT]))
    tid = r.json()["id"]
    for _ in range(300):
        if (await c.get(f"/v1/tasks/{tid}")).json()["status"]["state"] == "input-required":
            return tid
        await asyncio.sleep(0.02)
    raise AssertionError("no interrupt")


async def _done(c, tid) -> None:
    for _ in range(300):
        if (await c.get(f"/v1/tasks/{tid}")).json()["status"]["state"] == "completed":
            return
        await asyncio.sleep(0.02)
    raise AssertionError("not completed")


def _client(app):
    _, tok = app.state.auth.api_keys.mint("alice")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {tok}"},
    )


DATA = {"kind": "data", "data": {"decision": "approved", "n": 1}}


async def test_fresh_data_part_still_rejected(app):
    async with app.router.lifespan_context(app):
        c = _client(app)
        r = await c.post("/v1/message:send", json=_body([DATA]))
        assert r.status_code == 415
        assert r.json()["error"]["code"] == -32005
        r = await c.post(
            "/v1/message:send",
            json=_body([{"kind": "file", "file": {"uri": "http://x/y"}}]),
        )
        assert r.status_code == 415
        await c.aclose()


async def test_send_data_resume_delivers_payload(app):
    async with app.router.lifespan_context(app):
        c = _client(app)
        tid = await _interrupted(c)
        r = await c.post("/v1/message:send", json=_body([DATA], tid))
        assert r.status_code == 200, r.text
        await _done(c, tid)
        assert received == [{"status": None, "payload": DATA["data"]}]
        await c.aclose()


async def test_stream_data_resume_delivers_payload(app):
    async with app.router.lifespan_context(app):
        c = _client(app)
        tid = await _interrupted(c)
        async with c.stream("POST", "/v1/message:stream", json=_body([DATA], tid)) as r:
            assert r.status_code == 200
            async for _ in r.aiter_lines():
                pass
        await _done(c, tid)
        assert received == [{"status": None, "payload": DATA["data"]}]
        await c.aclose()


async def test_text_resume_stays_plain_string(app):
    async with app.router.lifespan_context(app):
        c = _client(app)
        tid = await _interrupted(c)
        r = await c.post("/v1/message:send", json=_body([{"kind": "text", "text": "yes"}], tid))
        assert r.status_code == 200
        await _done(c, tid)
        assert received == ["yes"]
        await c.aclose()


SECRET = "s3cr3t-value"


@pytest.mark.parametrize(
    "parts,status,code",
    [
        ([{"kind": "file", "file": {"uri": "http://x/" + SECRET}}], 415, -32005),
        (
            [DATA, {"kind": "file", "file": {"uri": "http://x/" + SECRET}}],
            415,
            -32005,
        ),
        ([TEXT, {"kind": "data", "data": {"k": SECRET}}], 400, -32602),
        ([{"kind": "data", "data": {"k": SECRET}}, {"kind": "data", "data": {"k": 2}}], 400, -32602),
        ([{"kind": "data", "data": [SECRET]}], 400, -32602),
    ],
)
async def test_bad_resume_shapes_refused_and_task_still_waiting(app, parts, status, code):
    async with app.router.lifespan_context(app):
        c = _client(app)
        tid = await _interrupted(c)
        r = await c.post("/v1/message:send", json=_body(parts, tid))
        assert r.status_code == status, r.text
        assert r.json()["error"]["code"] == code
        assert SECRET not in r.text
        assert (await c.get(f"/v1/tasks/{tid}")).json()["status"]["state"] == "input-required"
        assert received == []
        await c.aclose()


async def test_data_resume_unknown_task_is_plain_not_found(app):
    async with app.router.lifespan_context(app):
        c = _client(app)
        r = await c.post("/v1/message:send", json=_body([DATA], uuid.uuid4().hex))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == -32001
        await c.aclose()


async def test_action_gate_reads_payload_decision_only():
    approved = parse_decision({"status": None, "payload": {"decision": "approved"}})
    assert approved.outcome == Outcome.APPROVED
    sneaky = parse_decision({"status": None, "payload": {"status": "approved"}})
    assert sneaky.outcome != Outcome.APPROVED
