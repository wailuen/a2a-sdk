"""GH-237: testing clients — load_skill count, A2A kind, AG-UI history + role filter."""

from __future__ import annotations

import json
from typing import Any, ClassVar

import httpx
import pytest
from pydantic import BaseModel, Field, field_serializer

from agent_sdk.testing.chat import ChatDriver
from agent_sdk import BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.agent.loop import ToolInterrupt
from agent_sdk.app import Agent
from agent_sdk.models.content_types import _REGISTRY, KpiCard, MetricItem, register_content_type
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

    # MockTransport: scripted frames or failures a real app cannot produce.
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
        # MockTransport: scripted frames or failures a real app cannot produce.
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
async def test_a2a_message_has_kind(tmp_path):
    class _Bodies(httpx.AsyncBaseTransport):
        def __init__(self, inner):
            self.inner = inner
            self.posted: list = []

        async def handle_async_request(self, request):
            if request.method == "POST":
                self.posted.append(json.loads(request.content))
            return await self.inner.handle_async_request(request)

    app = _fake_tools_app(tmp_path, skills=False)
    rec = _Bodies(httpx.ASGITransport(app=app))
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        async with httpx.AsyncClient(
            transport=rec, base_url="http://test", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            at = await _a2a_attempt(client, "q", {})
    app.state.credential_store.close()
    assert rec.posted[0]["message"]["kind"] == "message"
    assert at.status is None


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


def test_not_authenticated_renamed_with_deprecated_alias():
    from agent_sdk.testing.chat import A2AError

    assert A2AError.AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED == -32007
    assert A2AError.NOT_AUTHENTICATED == -32007


@pytest.mark.asyncio
async def test_missing_preferred_transport_defaults_to_jsonrpc_and_is_rejected():
    def handler(req):
        return httpx.Response(200, json={"name": "x"})

    # MockTransport: scripted frames or failures a real app cannot produce.
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

    # MockTransport: scripted frames or failures a real app cannot produce.
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

    # MockTransport: scripted frames or failures a real app cannot produce.
    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    msgs: list = []
    task = asyncio.ensure_future(ChatDriver(client).agui_turn("q", "t", msgs))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert msgs == []


class _Recorder(httpx.AsyncBaseTransport):
    def __init__(self, inner):
        self.inner = inner
        self.posts: list = []

    async def handle_async_request(self, request):
        if request.method == "POST":
            self.posts.append(request)
        return await self.inner.handle_async_request(request)


class _DomCatalog(KpiCard):
    catalog_id: ClassVar[str] = "urn:test-gh256-domain:v1"
    data_type: ClassVar[str] = "gh256_dom"
    component: ClassVar[str] = "Gh256Dom"


def _a2ui_app(tmp_path, model=None, *, domain=False):
    ts = ToolSet()

    if domain:

        @ts.tool(tier=1, read_only=True, emits=_DomCatalog, sample={"a": "x"})
        async def dom(inp: _GateIn) -> _DomCatalog:
            """Emit a domain card."""
            return _DomCatalog(title="d", metrics=[MetricItem(label="Rev", value="1")])

    @ts.tool(tier=1, read_only=True, emits=KpiCard, sample={"a": "x"})
    async def kpi(inp: _GateIn) -> KpiCard:
        """Emit a KPI card."""
        return KpiCard(title="k", metrics=[MetricItem(label="Rev", value="1")])

    @ts.tool(tier=1)
    async def ask(inp: _GateIn) -> str:
        """Pause for input."""
        raise ToolInterrupt("need", "more?", response_schema={"type": "object"})

    return Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="t"),
        model_client=model or FakeModelClient(),
        persona="p",
        toolsets=[ts],
    ).build_app()


async def _asgi_client(app, rec):
    _, token = app.state.auth.api_keys.mint("t", admin=True)
    return httpx.AsyncClient(
        transport=rec, base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    )


@pytest.mark.asyncio
async def test_a2a_attempt_activates_a2ui_when_advertised(tmp_path):
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI
    from agent_sdk.testing.chat import card_catalog_ids

    app = _a2ui_app(tmp_path)
    rec = _Recorder(httpx.ASGITransport(app=app))
    async with app.router.lifespan_context(app):
        async with await _asgi_client(app, rec) as client:
            card = (await client.get("/.well-known/agent-card.json")).json()
            uris = [e["uri"] for e in card["capabilities"]["extensions"]]
            assert A2UI_EXTENSION_URI in uris
            drv = ChatDriver(client)
            await _a2a_attempt(client, "q", {}, drv)
            await _a2a_attempt(client, "q", {}, drv)
    app.state.credential_store.close()
    assert len(rec.posts) == 2
    for req in rec.posts:
        assert req.headers["x-a2a-extensions"] == A2UI_EXTENSION_URI
        caps = json.loads(req.content)["message"]["metadata"]["a2uiClientCapabilities"]
        assert caps == drv._caps
        for cid in card_catalog_ids(card):
            assert cid in caps["catalogs"]


@pytest.mark.asyncio
async def test_a2a_attempt_no_extension_when_not_advertised(tmp_path):
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    app = _fake_tools_app(tmp_path, skills=False)
    rec = _Recorder(httpx.ASGITransport(app=app))
    async with app.router.lifespan_context(app):
        async with await _asgi_client(app, rec) as client:
            card = (await client.get("/.well-known/agent-card.json")).json()
            uris = [e["uri"] for e in card["capabilities"].get("extensions", [])]
            assert A2UI_EXTENSION_URI not in uris
            await _a2a_attempt(client, "q", {})
    app.state.credential_store.close()
    assert "x-a2a-extensions" not in rec.posts[0].headers
    assert "a2uiClientCapabilities" not in (json.loads(rec.posts[0].content)["message"].get("metadata") or {})


@pytest.mark.asyncio
async def test_card_catalog_ids_reach_a2ui_capabilities_over_build_app(tmp_path):
    from agent_sdk.testing.chat import card_catalog_ids

    register_content_type(_DomCatalog)
    try:
        app = _a2ui_app(tmp_path, domain=True)
        rec = _Recorder(httpx.ASGITransport(app=app))
        async with app.router.lifespan_context(app):
            async with await _asgi_client(app, rec) as client:
                card = (await client.get("/.well-known/agent-card.json")).json()
                ids = card_catalog_ids(card)
                assert "urn:test-gh256-domain:v1" in ids and len(ids) > 1
                await _a2a_attempt(client, "q", {})
        app.state.credential_store.close()
    finally:
        _REGISTRY.pop("gh256_dom", None)
    caps = json.loads(rec.posts[0].content)["message"]["metadata"]["a2uiClientCapabilities"]
    assert "urn:test-gh256-domain:v1" in caps["catalogs"]


@pytest.mark.asyncio
async def test_a2a_resume_over_build_app_sends_task_and_context_id(tmp_path):
    from agent_sdk.testing import reply, tool_call

    model = FakeModelClient([tool_call("ask", {}), reply("done")])
    app = _a2ui_app(tmp_path, model)
    rec = _Recorder(httpx.ASGITransport(app=app))
    async with app.router.lifespan_context(app):
        async with await _asgi_client(app, rec) as client:
            first = await _a2a_attempt(client, "go", {})
            assert first.status is None
            assert first.ids["state"] == "input-required"
            second = await _a2a_attempt(client, "answer", first.ids)
    app.state.credential_store.close()
    assert second.status is None
    msg = json.loads(rec.posts[1].content)["message"]
    assert msg["taskId"] == first.ids["task_id"]
    assert msg["contextId"] == first.ids["context_id"]
    assert second.ids["task_id"] == first.ids["task_id"]


# ── GH-256 ────────────────────────────────────────────────────────────────────


def _card_client(card, posts, stream_body=b""):
    # MockTransport: build_app cannot serve a non-object card, a failing card
    # fetch, or a hand-written stream body.
    def handler(req):
        if req.method == "GET":
            if isinstance(card, Exception):
                raise card
            return httpx.Response(200, json=card)
        posts.append(req)
        return httpx.Response(200, content=stream_body)

    return httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))


def _a2ui_card(ids):
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    return {
        "preferredTransport": "HTTP+JSON",
        "capabilities": {
            "extensions": [{"uri": A2UI_EXTENSION_URI, "params": {"supportedCatalogIds": ids}}]
        },
    }


async def _attempt_over_app(tmp_path, state, model=None):
    app = _a2ui_app(tmp_path, model)
    rec = _Recorder(httpx.ASGITransport(app=app))
    async with app.router.lifespan_context(app):
        async with await _asgi_client(app, rec) as client:
            at = await _a2a_attempt(client, "q", state)
    app.state.credential_store.close()
    return at, rec


@pytest.mark.asyncio
async def test_resume_sends_both_task_and_context_id(tmp_path):
    state = {"task_id": "t1", "context_id": "c1", "state": "input-required"}
    _, rec = await _attempt_over_app(tmp_path, state)
    msg = json.loads(rec.posts[0].content)["message"]
    assert msg["taskId"] == "t1" and msg["contextId"] == "c1"


@pytest.mark.asyncio
async def test_context_only_when_not_interrupted(tmp_path):
    state = {"task_id": "t1", "context_id": "c1", "state": "completed"}
    _, rec = await _attempt_over_app(tmp_path, state)
    msg = json.loads(rec.posts[0].content)["message"]
    assert "taskId" not in msg and msg["contextId"] == "c1"


@pytest.mark.asyncio
@pytest.mark.parametrize("card", [[], "x", None, {"capabilities": []}, {"capabilities": {"extensions": "x"}}])
async def test_non_object_card_is_not_advertised(card):
    client = _card_client(card, [])
    assert await ChatDriver(client).a2ui_client_activation() == ({}, {})


@pytest.mark.asyncio
async def test_card_fetch_failure_logged_by_type_only(caplog):
    client = _card_client(httpx.ConnectError("secret-host-detail"), [])
    with caplog.at_level("WARNING"):
        assert await ChatDriver(client).a2ui_client_activation() == ({}, {})
    assert "ConnectError" in caplog.text
    assert "secret-host-detail" not in caplog.text


@pytest.mark.asyncio
async def test_stream_message_event_is_reply():
    # MockTransport: build_app never streams a bare kind=="message" event.
    body = _sse(
        {"kind": "message", "role": "agent", "contextId": "c9", "parts": [{"kind": "text", "text": "hello"}]},
        {"kind": "status-update", "taskId": "late", "status": {"state": "failed"}, "final": True},
    )
    client = _card_client({"capabilities": {}}, [], body)
    at = await _a2a_attempt(client, "q", {})
    assert at.reply == "hello" and at.ids["context_id"] == "c9" and at.ids["state"] == ""


@pytest.mark.asyncio
async def test_stream_stops_at_final_over_build_app(tmp_path):
    from agent_sdk.testing import reply

    at, _ = await _attempt_over_app(tmp_path, {}, FakeModelClient([reply("done")]))
    assert at.ids["state"] == "completed" and at.reply == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("advertised", [False, True])
async def test_chat_driver_sends_a2ui_header_only_when_advertised(tmp_path, advertised):
    app = _a2ui_app(tmp_path) if advertised else _fake_tools_app(tmp_path, skills=False)
    rec = _Recorder(httpx.ASGITransport(app=app))
    async with app.router.lifespan_context(app):
        async with await _asgi_client(app, rec) as client:
            d = ChatDriver(client)
            await d.a2a_turn("q")
            from agent_sdk.testing.chat import A2AError

            with pytest.raises(A2AError):  # unknown task: the server refuses, the request still went out
                await d.resume("no-task", "no-ctx", "r")
    app.state.credential_store.close()
    assert len(rec.posts) == 2
    for req in rec.posts:
        assert ("x-a2a-extensions" in req.headers) is advertised
        meta = json.loads(req.content)["message"].get("metadata") or {}
        assert ("a2uiClientCapabilities" in meta) is advertised


@pytest.mark.asyncio
async def test_a2a_attempt_over_build_app_asgi(tmp_path):
    app = _fake_tools_app(tmp_path, skills=False)
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            at = await _a2a_attempt(client, "hello", {})
    app.state.credential_store.close()
    assert at.status is None
    assert at.ids["task_id"] and at.ids["context_id"]


@pytest.mark.asyncio
async def test_mcp_client_rejects_unsupported_negotiated_version(tmp_path):
    from agent_sdk.testing.mcp import McpError

    # MockTransport: a real server never negotiates an unsupported version.
    def handler(req):
        body = json.loads(req.content)
        if body.get("method") == "initialize":
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "1999-01-01"}}
            )
        return httpx.Response(202)

    kf = tmp_path / "key"
    kf.write_text("tok")
    async with McpClient("http://t", key_file=kf, transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(McpError):
            await c.initialize()


def test_check_structured_unresolvable_ref_is_failure():
    from agent_sdk.testing.mcp import _check_structured

    tool = {"outputSchema": {"type": "object", "properties": {"a": {"$ref": "#/$defs/missing"}}}}
    out = _check_structured(tool, {"structuredContent": {"a": 1}})
    assert "$ref" in out


# ── GH-264 ────────────────────────────────────────────────────────────────────

from agent_sdk.testing.chat import _STANDARD_CATALOG as _STD  # noqa: E402


def _counting_client(card, stream_body, gets, posts, *, card_delay=0.0, post_statuses=None):
    import asyncio

    statuses = list(post_statuses or [])

    async def handler(req):
        if req.method == "GET":
            gets.append(req)
            if card_delay:
                await asyncio.sleep(card_delay)
            return httpx.Response(200, json=card)
        posts.append(req)
        if statuses:
            return httpx.Response(statuses.pop(0), content=b"")
        return httpx.Response(200, content=stream_body)

    return httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))


async def _no_sleep(_s):
    return None


@pytest.mark.asyncio
async def test_message_kind_stream_clears_stored_task_and_state(tmp_path):
    from agent_sdk.testing.turns import run_turn

    (tmp_path / "acc-k-a2a-task.txt").write_text("old-task")
    (tmp_path / "acc-k-a2a-state.txt").write_text("input-required")
    body = _sse({"kind": "message", "role": "agent", "contextId": "c1", "parts": [{"kind": "text", "text": "hi"}]})
    client = _counting_client({"capabilities": {}}, body, [], [])
    out = await run_turn(
        transport="a2a", base_url="http://t", key_file="unused", query="q", run_key="k",
        state_dir=tmp_path, lock_dir=tmp_path / "locks", client=client,
    )
    assert out["ok"] is True
    assert (tmp_path / "acc-k-a2a-task.txt").read_text() == ""
    assert (tmp_path / "acc-k-a2a-state.txt").read_text() == ""
    assert (tmp_path / "acc-k-a2a-ctx.txt").read_text() == "c1"


def test_chat_driver_merges_and_dedupes_catalogs():
    d = ChatDriver(None, extra_catalogs=["urn:a", _STD, "urn:a", "urn:b"])
    assert d._caps["catalogs"] == [_STD, "urn:a", "urn:b"]


@pytest.mark.asyncio
async def test_chat_driver_card_parameter_skips_fetch():
    gets: list = []
    client = _counting_client({}, b"", gets, [])
    d = ChatDriver(client, card=_a2ui_card(["urn:z"]))
    headers, meta = await d.a2ui_client_activation()
    assert headers and meta["a2uiClientCapabilities"]["catalogs"] == [_STD]
    assert gets == []


@pytest.mark.asyncio
async def test_card_fetched_once_across_retries_and_catalogs_deduped(tmp_path, monkeypatch):
    from agent_sdk.testing import turns

    monkeypatch.setattr(turns, "_sleep", _no_sleep)
    gets: list = []
    posts: list = []
    body = _sse({"kind": "message", "role": "agent", "parts": [{"kind": "text", "text": "ok"}]})
    card = _a2ui_card(["urn:x", _STD, "urn:x"])
    client = _counting_client(card, body, gets, posts, post_statuses=[429])
    out = await turns.run_turn(
        transport="a2a", base_url="http://t", key_file="unused", query="q", run_key="k2",
        state_dir=tmp_path, lock_dir=tmp_path / "locks", client=client,
    )
    assert out["ok"] is True and out["attempts"] == 2
    assert len(gets) == 1
    caps = json.loads(posts[-1].content)["message"]["metadata"]["a2uiClientCapabilities"]
    assert caps["catalogs"] == [_STD, "urn:x"]


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["a2a", "agui"])
async def test_card_fetch_is_inside_time_budget(tmp_path, transport):
    from agent_sdk.testing.turns import run_turn

    client = _counting_client({"capabilities": {}}, b"", [], [], card_delay=30.0)
    out = await run_turn(
        transport=transport, base_url="http://t", key_file="unused", query="q", run_key="k3",
        state_dir=tmp_path, lock_dir=tmp_path / "locks", budget_s=0.3, client=client,
    )
    assert out["ok"] is False and out["reason"] == "budget-exceeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["a2a", "agui"])
async def test_card_fetch_waits_for_slot(tmp_path, transport):
    from agent_sdk.testing.turns import SlotLimiter, run_turn

    held = SlotLimiter(tmp_path / "locks", 1).try_acquire()
    assert held is not None
    gets: list = []
    client = _counting_client({"capabilities": {}}, b"", gets, [])
    try:
        out = await run_turn(
            transport=transport, base_url="http://t", key_file="unused", query="q", run_key="k4",
            state_dir=tmp_path, lock_dir=tmp_path / "locks", max_slots=1, budget_s=0.3, client=client,
        )
    finally:
        held.release()
    assert out["ok"] is False and out["reason"] == "slot-wait-exceeded"
    assert gets == []


@pytest.mark.asyncio
async def test_agui_turn_declares_card_catalogs(tmp_path):
    from agent_sdk.testing.turns import run_turn

    posts: list = []
    # An empty reply is a failed attempt and is retried, so the stream carries text.
    body = _sse(_start("m1"), _content("hi"), FINISHED)
    client = _counting_client(_a2ui_card(["urn:x", "urn:x"]), body, [], posts)
    out = await run_turn(
        transport="agui", base_url="http://t", key_file="unused", query="q", run_key="k5",
        state_dir=tmp_path, lock_dir=tmp_path / "locks", budget_s=10.0, client=client,
    )
    assert out["ok"] is True
    caps = json.loads(posts[0].content)["forwardedProps"]["a2uiClientCapabilities"]
    assert caps["catalogs"] == [_STD, "urn:x"]


@pytest.mark.asyncio
async def test_agui_run_turn_over_build_app_declares_domain_catalog(tmp_path):
    from agent_sdk.testing import reply
    from agent_sdk.testing.turns import run_turn

    register_content_type(_DomCatalog)
    try:
        # An unscripted model errors every run, so script one text reply.
        app = _a2ui_app(tmp_path, FakeModelClient([reply("done")]), domain=True)
        rec = _Recorder(httpx.ASGITransport(app=app))
        async with app.router.lifespan_context(app):
            async with await _asgi_client(app, rec) as client:
                out = await run_turn(
                    transport="agui", base_url="http://test", key_file="unused", query="q",
                    run_key="k6", state_dir=tmp_path, lock_dir=tmp_path / "locks", budget_s=10.0,
                    client=client,
                )
        app.state.credential_store.close()
    finally:
        _REGISTRY.pop("gh256_dom", None)
    assert out["ok"] is True
    caps = json.loads(rec.posts[0].content)["forwardedProps"]["a2uiClientCapabilities"]
    assert "urn:test-gh256-domain:v1" in caps["catalogs"]


@pytest.mark.asyncio
async def test_card_fetch_builds_no_new_client(tmp_path, monkeypatch):
    from agent_sdk.testing.turns import run_turn

    # Each stream carries a text reply: an empty reply is retried until the budget ends.
    bodies = {
        "a2a": _sse({"kind": "message", "role": "agent", "parts": [{"kind": "text", "text": "ok"}]}),
        "agui": _sse(_start("m1"), _content("hi"), FINISHED),
    }
    clients = {t: _counting_client(_a2ui_card(["urn:x"]), b, [], []) for t, b in bodies.items()}
    built: list = []
    real_init = httpx.AsyncClient.__init__

    def spy(self, *a, **kw):
        built.append(1)
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy)
    for transport in ("a2a", "agui"):
        out = await run_turn(
            transport=transport, base_url="http://t", key_file="unused", query="q", run_key="k7",
            state_dir=tmp_path, lock_dir=tmp_path / "locks", budget_s=10.0, client=clients[transport],
        )
        assert out["ok"] is True
    assert built == []


@pytest.mark.asyncio
async def test_mcp_missing_protocol_version_is_error_without_echo(tmp_path):
    from agent_sdk.testing.mcp import McpError

    def handler(req):
        body = json.loads(req.content)
        if body.get("method") == "initialize":
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"serverInfo": {"name": "BODY-MARKER-9"}}}
            )
        return httpx.Response(202)

    kf = tmp_path / "key"
    kf.write_text("tok")
    async with McpClient("http://t", key_file=kf, transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(McpError) as ei:
            await c.initialize()
    assert "BODY-MARKER-9" not in str(ei.value)


@pytest.mark.asyncio
async def test_malformed_sse_frame_is_a_failed_attempt_not_a_traceback():
    client = _card_client({"capabilities": {}}, [], b"data: {not json\n\n")
    at = await _a2a_attempt(client, "q", {})
    assert at.reason == "malformed-stream" and at.classify() is False


@pytest.mark.asyncio
async def test_a2a_turn_rejects_non_object_card():
    client = _card_client(["not", "an", "object"], [])
    with pytest.raises(ValueError, match="not a JSON object"):
        await ChatDriver(client).a2a_turn("q")


def test_check_structured_other_validator_error_is_not_reported_as_ref(monkeypatch):
    from agent_sdk.testing import mcp as mcp_mod

    def boom(*_a, **_k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(mcp_mod.jsonschema, "validate", boom)
    tool = {"outputSchema": {"type": "object"}}
    out = mcp_mod._check_structured(tool, {"structuredContent": {}})
    assert "$ref" not in out and "secret detail" not in out and out
