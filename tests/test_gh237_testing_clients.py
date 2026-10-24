"""GH-237: testing clients — load_skill count, A2A kind, AG-UI history + role filter."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field, field_serializer

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


class _Msg(dict):
    """Equal to any message dict with the same role and content; the posted id is generated."""

    def __eq__(self, other):
        return isinstance(other, dict) and all(other.get(k) == v for k, v in self.items()) and bool(other.get("id"))

    __hash__ = None  # type: ignore[assignment]


Q = _Msg({"role": "user", "content": "q"})


@pytest.mark.asyncio
async def test_turn_text_finished_appends_user_and_assistant():
    bodies: list = []
    _, d = _driver([_start("m1"), _content("hi"), FINISHED], bodies)
    msgs: list = []
    assert await d.agui_turn("q", "t", msgs) == "hi"
    assert msgs[-2:] == [Q, _Msg({"role": "assistant", "content": "hi"})]
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
    assert msgs == [Q, _Msg({"role": "assistant", "content": "done"})]
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
    assert msgs == [Q, _Msg({"role": "assistant", "content": "ok"})]


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
    ([{**_start("n"), "role": None}, _content("kept", "n"), FINISHED], "kept"),
    ([{**_chunk("kept", "n1"), "role": None}, _chunk(" too"), FINISHED], "kept too"),
    ([{**_start("e"), "role": ""}, _content("empty", "e"), FINISHED], "empty"),
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
        if req.method == "POST":
            seen.append(json.loads(req.content))
        return httpx.Response(200, content=b"")

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    await _a2a_attempt(client, "q", {})
    assert seen[0]["message"]["kind"] == "message"


def _fake_tools_app(tmp_path, *, skills: bool, domain_load_skill: bool = False, extra_tools=()):
    ts = ToolSet()

    @ts.tool(tier=1, read_only=True)
    async def real(inp: _GateIn) -> str:
        """Real domain tool."""
        return "ok"

    if domain_load_skill:

        @ts.tool(tier=1, read_only=True)
        async def load_skill(inp: _GateIn) -> str:
            """Domain tool that happens to share the built-in name."""
            return "ok"

    kw: dict[str, Any] = {}
    if skills:
        sd = tmp_path / "skills"
        sd.mkdir()
        (sd / "s0.md").write_text("---\nname: s0\ndescription: d\n---\nBody.\n", encoding="utf-8")
        kw = {"skills_dir": sd, "mcp_skills": "tool"}
    return Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="t"),
        model_client=FakeModelClient(),
        persona="p",
        toolsets=[ts, *extra_tools],
        **kw,
    ).build_app()


async def _gate(app, tmp_path, samples, **kw):
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        key_file = tmp_path / "key"
        key_file.write_text(token)
        async with McpClient(
            "http://test", key_file=key_file, transport=httpx.ASGITransport(app=app)
        ) as c:
            res = await run_gate(c, samples, **kw)
    app.state.credential_store.close()
    return res


@pytest.mark.asyncio
async def test_domain_load_skill_without_skills_dir_is_counted(tmp_path):
    app = _fake_tools_app(tmp_path, skills=False, domain_load_skill=True)
    res = await _gate(app, tmp_path, {"real": {"a": "x"}, "load_skill": {"a": "x"}}, expected_count=2)
    assert res.failures == []
    assert sorted(res.called) == ["load_skill", "real"]


@pytest.mark.asyncio
async def test_builtin_present_wrong_expected_count_fails(tmp_path):
    app = _fake_tools_app(tmp_path, skills=True)
    res = await _gate(app, tmp_path, {"real": {"a": "x"}}, expected_count=2)
    assert any("count 1 != registered tier-1 tools 2" in f for f in res.failures)


@pytest.mark.asyncio
async def test_builtin_matched_by_shape_not_name_only():
    from agent_sdk.agent.loop import LOAD_SKILL_TOOL
    from agent_sdk.testing.mcp import _check_list

    builtin = {
        "name": LOAD_SKILL_TOOL,
        "title": "Load skill",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "d"}}, "required": ["name"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }
    domain = {"name": LOAD_SKILL_TOOL, "inputSchema": {"type": "object", "properties": {}}}
    assert _check_list([builtin, {"name": "b", "inputSchema": {}}], 1, 10_000) == []
    assert _check_list([domain, {"name": "b", "inputSchema": {}}], 2, 10_000) == []
    assert _check_list([domain, {"name": "b", "inputSchema": {}}], 1, 10_000) != []
    assert _check_list([domain], 0, 10_000, skills_tool=True) == []


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner):
        self.inner = inner
        self.seen: list[tuple[str | None, str | None, Any]] = []

    async def handle_async_request(self, request):
        body = json.loads(request.content) if request.content else {}
        self.seen.append((body.get("method"), request.headers.get("mcp-protocol-version"), body.get("params")))
        return await self.inner.handle_async_request(request)


@pytest.mark.asyncio
async def test_mcp_client_sends_negotiated_version_header(tmp_path):
    from agent_sdk.routes.mcp import SUPPORTED_PROTOCOL_VERSIONS

    app = _fake_tools_app(tmp_path, skills=False)
    rec = _RecordingTransport(httpx.ASGITransport(app=app))
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        kf = tmp_path / "key"
        kf.write_text(token)
        async with McpClient("http://test", key_file=kf, transport=rec) as c:
            await c.initialize()
            await c.list_tools()
    app.state.credential_store.close()
    assert rec.seen[0][0] == "initialize"
    assert rec.seen[0][2]["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]
    assert rec.seen[0][1] is None
    later = [v for _, v, _ in rec.seen[1:]]
    assert later
    assert all(v == SUPPORTED_PROTOCOL_VERSIONS[0] for v in later)


class _OutOk(BaseModel):
    n: int


@pytest.mark.asyncio
async def test_run_gate_validates_structured_content_conforming(tmp_path):
    ts = ToolSet()

    @ts.tool(tier=1, read_only=True)
    async def good(inp: _GateIn) -> _OutOk:
        """Returns a conforming object."""
        return _OutOk(n=1)

    app = Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="t"),
        model_client=FakeModelClient(),
        persona="p",
        toolsets=[ts],
    ).build_app()
    res = await _gate(app, tmp_path, {"good": {"a": "x"}})
    assert res.failures == []


class _OutBad(BaseModel):
    n: int

    @field_serializer("n")
    def _leak(self, v):
        return "SECRET-VALUE"


def _schema_app(tmp_path, mode):
    ts = ToolSet()

    if mode == "absent":

        @ts.tool(tier=1, read_only=True, emits=_OutOk)
        async def t(inp: _GateIn) -> _OutOk:  # type: ignore[empty-body]
            """Returns nothing."""
            return None  # type: ignore[return-value]

    elif mode == "mismatch":

        @ts.tool(tier=1, read_only=True, emits=_OutBad)
        async def t(inp: _GateIn) -> _OutBad:
            """Returns a non-conforming object."""
            return _OutBad(n=1)

    else:

        @ts.tool(tier=1, read_only=True, emits=_OutOk)
        async def t(inp: _GateIn) -> _OutOk:
            """Returns a conforming object."""
            return _OutOk(n=1)

    return Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="t"),
        model_client=FakeModelClient(),
        persona="p",
        toolsets=[ts],
    ).build_app()


@pytest.mark.asyncio
# "absent" is a void tool: the server (routes/mcp.py, §5.6) sends an empty text
# block and no structuredContent, so the gate must not fail it (v0.22.0 gate).
@pytest.mark.parametrize("mode,bad", [("ok", False), ("mismatch", True), ("absent", False)])
async def test_run_gate_output_schema_check(tmp_path, mode, bad):
    res = await _gate(_schema_app(tmp_path, mode), tmp_path, {"t": {"a": "x"}})
    assert (not res.ok) is bad
    if bad:
        assert any("structuredContent" in f and "tool t" in f for f in res.failures)


def test_check_structured_missing_with_text_fails():
    from agent_sdk.testing.mcp import _check_structured

    tool = {"outputSchema": {"type": "object"}}
    assert _check_structured(tool, {"content": [{"type": "text", "text": ""}]}) == ""
    assert "absent" in _check_structured(tool, {"content": [{"type": "text", "text": "x"}]})
    assert "absent" in _check_structured(tool, {"content": [{"type": "text", "text": ""}], "isError": True})


@pytest.mark.asyncio
async def test_run_gate_output_schema_failure_does_not_echo_values(tmp_path):
    res = await _gate(_schema_app(tmp_path, "mismatch"), tmp_path, {"t": {"a": "x"}})
    assert not res.ok
    assert "SECRET-VALUE" not in " ".join(res.failures)


@pytest.mark.asyncio
async def test_a2a_attempt_activates_a2ui_when_advertised():
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    posts: list = []
    gets: list = []

    def handler(req):
        if req.method == "GET":
            gets.append(req.url.path)
            return httpx.Response(
                200, json={"preferredTransport": "HTTP+JSON", "capabilities": {"extensions": [{"uri": A2UI_EXTENSION_URI}]}}
            )
        posts.append(req)
        return httpx.Response(200, content=b"")

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    drv = ChatDriver(client)
    await _a2a_attempt(client, "q", {}, drv)
    await _a2a_attempt(client, "q", {}, drv)
    assert len(gets) == 1
    for req in posts:
        assert req.headers["x-a2a-extensions"] == A2UI_EXTENSION_URI
        assert json.loads(req.content)["message"]["metadata"]["a2uiClientCapabilities"] == drv._caps


@pytest.mark.asyncio
async def test_a2a_attempt_no_extension_when_not_advertised():
    posts: list = []

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"capabilities": {"extensions": []}})
        posts.append(req)
        return httpx.Response(200, content=b"")

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    await _a2a_attempt(client, "q", {})
    assert "x-a2a-extensions" not in posts[0].headers
    assert "a2uiClientCapabilities" not in (json.loads(posts[0].content)["message"].get("metadata") or {})


def test_not_authenticated_renamed_with_deprecated_alias():
    from agent_sdk.testing.chat import A2AError

    assert A2AError.AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED == -32007
    assert A2AError.NOT_AUTHENTICATED == -32007


@pytest.mark.asyncio
async def test_missing_preferred_transport_defaults_to_jsonrpc_and_is_rejected():
    def handler(req):
        return httpx.Response(200, json={"name": "x"})

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="JSONRPC"):
        await ChatDriver(client).a2a_turn("q")


@pytest.mark.asyncio
async def test_posted_agui_messages_carry_ids():
    bodies: list = []
    _, d = _driver([_content("hi"), FINISHED], bodies)
    msgs: list = []
    await d.agui_turn("q", "t", msgs)
    await d.agui_turn("q2", "t", msgs)
    assert all(isinstance(m.get("id"), str) and m["id"] for m in msgs)
    assert len({m["id"] for m in msgs}) == len(msgs)
    assert all(m.get("id") for m in bodies[1]["messages"])
    msgs2: list = [{"role": "user", "content": "q", "id": "u1"}]
    await d.agui_resume("i1", "t", msgs2)
    assert msgs2[-1]["role"] == "assistant" and msgs2[-1]["id"]


@pytest.mark.asyncio
async def test_agui_turn_connect_error_leaves_messages_unchanged():
    def handler(req):
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    msgs: list = [{"role": "user", "content": "old", "id": "x"}]
    before = list(msgs)
    with pytest.raises(httpx.ConnectError):
        await ChatDriver(client).agui_turn("q", "t", msgs)
    assert msgs == before


@pytest.mark.asyncio
async def test_agui_turn_cancel_after_first_frame_leaves_messages_unchanged():
    import asyncio

    class _Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _sse(_content("part"))
            await asyncio.sleep(30)

    def handler(req):
        return httpx.Response(200, stream=_Stream())

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    msgs: list = []
    task = asyncio.ensure_future(ChatDriver(client).agui_turn("q", "t", msgs))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert msgs == []
