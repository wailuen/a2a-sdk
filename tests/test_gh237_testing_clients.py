"""GH-237: testing clients — load_skill count, A2A kind, AG-UI history + role filter."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from agent_sdk.testing.chat import ChatDriver
from agent_sdk import BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.app import Agent
from agent_sdk.testing import FakeModelClient
from agent_sdk.testing.mcp import McpClient, run_gate
from agent_sdk.testing.turns import _a2a_attempt, _agui_attempt


class _GateIn(BaseModel):
    a: str = Field(default="", description="d")


def _sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def _start(mid, role=None):
    f: dict[str, Any] = {"type": "TEXT_MESSAGE_START", "messageId": mid}
    if role is not None:
        f["role"] = role
    return f


def _content(delta, mid="m1"):
    f: dict[str, Any] = {"type": "TEXT_MESSAGE_CONTENT", "delta": delta}
    if mid is not None:
        f["messageId"] = mid
    return f


def _chunk(delta, mid=None, role=None):
    f: dict[str, Any] = {"type": "TEXT_MESSAGE_CHUNK", "delta": delta}
    if mid:
        f["messageId"] = mid
    if role is not None:
        f["role"] = role
    return f


FINISHED = {"type": "RUN_FINISHED", "outcome": {"type": "success"}}
INTERRUPT = {
    "type": "RUN_FINISHED",
    "outcome": {"type": "interrupt", "interrupts": [{"id": "i1"}]},
}
ERROR = {"type": "RUN_ERROR", "message": "boom"}
A2UI_ONLY = [
    {"type": "CUSTOM", "name": "AGENT_ARTIFACT", "value": {"dataType": "Card", "toolName": "t"}},
    {"type": "CUSTOM", "name": "A2UI_UPDATE", "value": {"messages": []}},
    FINISHED,
]


def _driver(events, bodies=None):
    def handler(req):
        if bodies is not None:
            bodies.append(json.loads(req.content))
        return httpx.Response(200, content=_sse(*events))

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    return client, ChatDriver(client)


Q = {"role": "user", "content": "q"}


@pytest.mark.asyncio
async def test_turn_text_finished_appends_user_and_assistant():
    bodies: list = []
    _, d = _driver([_start("m1"), _content("hi"), FINISHED], bodies)
    msgs: list = []
    assert await d.agui_turn("q", "t", msgs) == "hi"
    assert msgs[-2:] == [Q, {"role": "assistant", "content": "hi"}]
    assert bodies[0]["messages"][-1] == Q


@pytest.mark.asyncio
async def test_turn_a2ui_only_appends_user_only():
    bodies: list = []
    _, d = _driver(A2UI_ONLY, bodies)
    msgs: list = []
    assert await d.agui_turn("q", "t", msgs) == ""
    assert msgs == [Q]
    assert bodies[0]["messages"][-1] == Q


@pytest.mark.asyncio
async def test_turn_interrupt_then_resume_posts_query():
    bodies: list = []
    _, d = _driver([INTERRUPT], bodies)
    msgs: list = []
    await d.agui_turn("q", "t", msgs)
    assert msgs == [Q]
    await d.agui_resume("i1", "t", msgs)
    assert Q in bodies[1]["messages"]
    assert msgs == [Q]


@pytest.mark.asyncio
@pytest.mark.parametrize("events", [[_content("partial"), ERROR], [_content("partial")]])
async def test_turn_error_or_no_terminal_leaves_messages(events):
    bodies: list = []
    _, d = _driver(events, bodies)
    msgs: list = [{"role": "user", "content": "old"}]
    before = list(msgs)
    assert await d.agui_turn("q", "t", msgs) == ""
    assert msgs == before
    assert bodies[0]["messages"][-1] == Q


@pytest.mark.asyncio
async def test_turn_http_error_leaves_messages():
    client = httpx.AsyncClient(
        base_url="http://t", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    msgs: list = []
    with pytest.raises(httpx.HTTPStatusError):
        await ChatDriver(client).agui_turn("q", "t", msgs)
    assert msgs == []


@pytest.mark.asyncio
async def test_resume_appends_assistant_only_on_text():
    _, d = _driver([_content("done"), FINISHED])
    msgs: list = [Q]
    assert await d.agui_resume("i1", "t", msgs) == "done"
    assert msgs == [Q, {"role": "assistant", "content": "done"}]
    _, d = _driver(A2UI_ONLY)
    msgs = [Q]
    await d.agui_resume("i1", "t", msgs)
    assert msgs == [Q]
    _, d = _driver([ERROR])
    await d.agui_resume("i1", "t", msgs)
    assert msgs == [Q]


@pytest.mark.asyncio
async def test_attempt_text_success():
    _, d = _driver([_content("ok"), FINISHED])
    msgs: list = []
    at = await _agui_attempt(d._client, "q", "t", msgs)
    assert at.reply == "ok"
    assert msgs == [Q, {"role": "assistant", "content": "ok"}]


@pytest.mark.asyncio
async def test_attempt_a2ui_only_is_success_and_keeps_query():
    _, d = _driver(A2UI_ONLY)
    msgs: list = []
    at = await _agui_attempt(d._client, "q", "t", msgs)
    assert at.classify()
    assert msgs == [Q]


@pytest.mark.asyncio
async def test_attempt_error_restores_snapshot():
    _, d = _driver([ERROR])
    msgs: list = [{"role": "user", "content": "old"}]
    await _agui_attempt(d._client, "q", "t", msgs)
    assert msgs == [{"role": "user", "content": "old"}]


@pytest.mark.asyncio
async def test_attempt_interrupt_only_is_empty_reply_and_restored():
    _, d = _driver([INTERRUPT])
    msgs: list = []
    at = await _agui_attempt(d._client, "q", "t", msgs)
    assert not at.classify()
    assert at.reason == "empty-reply"
    assert msgs == []


ROLE_CASES = [
    ([_start("d", "developer"), _content("dev", "d"), _start("a", "assistant"), _content("hello", "a"), FINISHED], "hello"),
    ([_start("a"), _content("x", "a"), FINISHED], "x"),
    ([_chunk("c", "c1"), _chunk("d"), FINISHED], "cd"),
    ([_chunk("c", "c1", role="developer"), _chunk("z"), _start("a"), _content("hello", "a"), FINISHED], "hello"),
    ([_content("only", "nostart"), FINISHED], "only"),
    ([_content("noid", None), FINISHED], "noid"),
    ([_start("d", "developer"), _content("dev", "d"), _content("second", "other"), FINISHED], "second"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("events,expected", ROLE_CASES)
async def test_role_filter_chat_driver_and_turns(events, expected):
    _, d = _driver(events)
    assert await d.agui_turn("q", "t", []) == expected
    _, d = _driver(events)
    at = await _agui_attempt(d._client, "q", "t", [])
    assert at.reply == expected


@pytest.mark.asyncio
async def test_run_gate_excludes_load_skill_from_count(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "s0.md").write_text("---\nname: s0\ndescription: d\n---\nBody.\n", encoding="utf-8")
    ts = ToolSet()

    @ts.tool(tier=1, read_only=True)
    async def real(inp: _GateIn) -> str:
        """Real domain tool."""
        return "ok"

    app = Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="t"),
        model_client=FakeModelClient(),
        persona="p",
        skills_dir=skills,
        toolsets=[ts],
        mcp_skills="tool",
    ).build_app()
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        key_file = tmp_path / "key"
        key_file.write_text(token)
        async with McpClient(
            "http://test", key_file=key_file, transport=httpx.ASGITransport(app=app)
        ) as c:
            names = [t["name"] for t in await c.list_tools()]
            assert "load_skill" in names and "real" in names
            res = await run_gate(c, {"real": {"a": "x"}}, expected_count=1)
    app.state.credential_store.close()
    assert res.failures == []
    assert res.called == ["real"]


@pytest.mark.asyncio
async def test_a2a_message_has_kind():
    seen: list = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, content=b"")

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    await _a2a_attempt(client, "q", {})
    assert seen[0]["message"]["kind"] == "message"
