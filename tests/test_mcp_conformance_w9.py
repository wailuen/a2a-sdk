"""MCP protocol conformance tests — wave 9, Group C (SC-C1 through SC-C8 + RT-004).

SC-C1  structuredContent for non-BaseModel emits (dict returned against declared emits=)
SC-C2  tools/list cursor/nextCursor pagination (PAGE_SIZE=64)
SC-C3  WWW-Authenticate challenge omits scope= (RFC 6750 §3 — empty scope is malformed)
SC-C4  Example tools (echo, demo_kpis) have annotations.destructiveHint=false
SC-C5  Tool name length > 64 raises ValueError at registration time
SC-C6  Auto-derived title from a snake_case function name when title= is omitted
SC-C7  MarketBriefing MCP outputSchema + structuredContent are a JSON object
       wrapping the markdown ({"markdown": to_markdown()}), never a bare string
       or the field dict (GH-105, MCP 2025-06-18 object-only requirement)
SC-C8  openWorldHint reflects whether a tool is SourceAdapter-backed, not
       tier/read_only (GH-52, corrected by GH-134)
RT-004 Agent card omits x-sdk.outputSchema (GH-219); MCP carries it for a
       MarketBriefing-emitting tool
"""

from __future__ import annotations

import asyncio
import gc
import logging
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from agent_sdk import BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.sources import SourceAdapter
from agent_sdk.testing import FakeModelClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _mcp_init(client):
    """Run MCP initialize handshake, return session id header dict."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r.status_code == 200, r.text
    session = r.headers.get("mcp-session-id")
    headers: dict[str, str] = {"MCP-Protocol-Version": "2025-06-18"}
    if session:
        headers["Mcp-Session-Id"] = session
    return headers


# ---------------------------------------------------------------------------
# SC-C1: structuredContent for non-BaseModel emits
# ---------------------------------------------------------------------------


class KpiCardLike(BaseModel):
    """Minimal model matching a KPI card shape for SC-C1 test."""

    title: str
    value: float


@pytest.fixture
def sc_c1_app(settings, fake_model):
    """App with a tool that declares emits=KpiCardLike but returns a plain dict.

    The function is unannotated (no return type) so SC-F1 validation passes,
    but it returns a raw dict at runtime — exactly the SC-C1 scenario.
    """
    from pydantic import BaseModel as PM

    class _Empty(PM):
        pass

    from agent_sdk.agent.registry import ToolDecl

    extra = ToolSet()

    # Define without return annotation so SC-F1 permits it.
    async def dict_emitter(inp: _Empty):  # noqa: no return annotation intentional
        """Return a raw dict that matches KpiCardLike schema."""
        return {"title": "Revenue", "value": 42.0}

    extra.decls.append(
        ToolDecl(
            fn=dict_emitter,
            name="dict_emitter",
            description="Return a raw dict that matches KpiCardLike schema.",
            tier=1,
            emits=KpiCardLike,
            sample=None,
            input_model=_Empty,
            adapter_params={},
            title=None,
            annotations=None,
        )
    )

    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [extra]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def sc_c1_client(sc_c1_app):
    async with sc_c1_app.router.lifespan_context(sc_c1_app):
        _, token = sc_c1_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=sc_c1_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_sc_c1_structured_content_for_dict_return(sc_c1_client):
    """Tool declaring emits=KpiCardLike but returning a plain dict MUST emit
    structuredContent in tools/call (MCP §4 MUST)."""
    headers = await _mcp_init(sc_c1_client)

    r = await sc_c1_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "dict_emitter", "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result.get("isError") is False
    assert "structuredContent" in result, (
        "structuredContent MUST be present when emits= is declared"
    )
    sc = result["structuredContent"]
    assert sc["title"] == "Revenue"
    assert sc["value"] == 42.0


# ---------------------------------------------------------------------------
# SC-C2: tools/list pagination
# ---------------------------------------------------------------------------


@pytest.fixture
def sc_c2_app(settings, fake_model):
    """App with 65 registered tier-1 tools to exercise pagination."""
    extra = ToolSet()

    from pydantic import BaseModel as PM

    class _Empty(PM):
        pass

    for i in range(65):

        async def _tool_fn(**_kw: Any) -> dict:
            return {}

        _tool_fn.__name__ = f"tool_{i:03d}"
        _tool_fn.__doc__ = f"Tool number {i}"
        import inspect

        # Build a properly decorated ToolDecl manually
        from agent_sdk.agent.registry import ToolDecl

        extra.decls.append(
            ToolDecl(
                fn=_tool_fn,
                name=f"tool_{i:03d}",
                description=f"Tool number {i}",
                tier=1,
                emits=None,
                sample=None,
                input_model=_Empty,
                adapter_params={},
                title=None,
                annotations=None,
            )
        )

    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [extra]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def sc_c2_client(sc_c2_app):
    async with sc_c2_app.router.lifespan_context(sc_c2_app):
        _, token = sc_c2_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=sc_c2_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_sc_c2_pagination_first_page(sc_c2_client):
    """First tools/list call returns 64 tools and a nextCursor."""
    headers = await _mcp_init(sc_c2_client)

    r = await sc_c2_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    # We have 65 total (2 example tools + 65 extra = 67, but only tier1 matters).
    # The example agent has echo + demo_kpis (tier 1) → 67 tier-1 tools total.
    assert len(result["tools"]) == 64
    assert "nextCursor" in result


async def test_sc_c2_pagination_second_page(sc_c2_client):
    """Second tools/list call using nextCursor returns remaining tools, no nextCursor."""
    headers = await _mcp_init(sc_c2_client)

    # First page
    r1 = await sc_c2_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r1.status_code == 200
    first = r1.json()["result"]
    next_cursor = first["nextCursor"]
    first_names = {t["name"] for t in first["tools"]}

    # Second page
    r2 = await sc_c2_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
            "params": {"cursor": next_cursor},
        },
        headers=headers,
    )
    assert r2.status_code == 200
    second = r2.json()["result"]
    # Remaining tools (67 - 64 = 3)
    assert len(second["tools"]) >= 1
    assert "nextCursor" not in second
    # No overlap
    second_names = {t["name"] for t in second["tools"]}
    assert first_names.isdisjoint(second_names)


# ---------------------------------------------------------------------------
# SC-C3: WWW-Authenticate challenge is RFC 6750 §3-compliant (no empty scope=)
# ---------------------------------------------------------------------------


async def test_sc_c3_www_authenticate_no_empty_scope(client):
    """Unauthenticated request → 401 WWW-Authenticate must NOT contain scope=.

    RFC 6750 §3 ABNF requires at least one non-empty token in the scope
    production; an empty scope="" is malformed and causes strict OAuth 2.1
    clients to abort discovery.  The challenge must carry resource_metadata=
    (RFC 9728 §3.1) but omit scope entirely when no scopes are defined.
    """
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": ""},
    )
    assert r.status_code == 401
    www_auth = r.headers.get("www-authenticate", "")
    assert "scope=" not in www_auth, (
        f"scope= must not appear in WWW-Authenticate (empty scope is RFC 6750 §3 "
        f"malformed); got: {www_auth!r}"
    )
    assert 'resource_metadata="' in www_auth, (
        f"WWW-Authenticate must still carry resource_metadata= (RFC 9728 §3.1); "
        f"got: {www_auth!r}"
    )


# ---------------------------------------------------------------------------
# SC-C4: Example tools have annotations.destructiveHint=false
# ---------------------------------------------------------------------------


async def test_sc_c4_echo_destructive_hint_false(client):
    """echo tool must have annotations.destructiveHint=false."""
    headers = await _mcp_init(client)

    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    echo = next((t for t in tools if t["name"] == "echo"), None)
    assert echo is not None, "echo tool not found in tools/list"
    annotations = echo.get("annotations", {})
    assert annotations.get("destructiveHint") is False, (
        f"echo.annotations.destructiveHint should be False, got: {annotations}"
    )


async def test_sc_c4_demo_kpis_destructive_hint_false(client):
    """demo_kpis tool must have annotations.destructiveHint=false."""
    headers = await _mcp_init(client)

    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    demo_kpis = next((t for t in tools if t["name"] == "demo_kpis"), None)
    assert demo_kpis is not None, "demo_kpis tool not found in tools/list"
    annotations = demo_kpis.get("annotations", {})
    assert annotations.get("destructiveHint") is False, (
        f"demo_kpis.annotations.destructiveHint should be False, got: {annotations}"
    )


# ---------------------------------------------------------------------------
# SC-C5: Tool name length validation at registration
# ---------------------------------------------------------------------------


def test_sc_c5_tool_name_too_long_raises_at_registration(settings, fake_model):
    """Registering a tool with a name > 64 chars must raise ValueError at build_app()."""
    extra = ToolSet()

    from pydantic import BaseModel as PM

    class _Empty(PM):
        pass

    from agent_sdk.agent.registry import ToolDecl

    long_name = "a" * 65
    extra.decls.append(
        ToolDecl(
            fn=None,  # type: ignore[arg-type]
            name=long_name,
            description="Too long",
            tier=1,
            emits=None,
            sample=None,
            input_model=_Empty,
            adapter_params={},
            title=None,
            annotations=None,
        )
    )

    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [extra]
    with pytest.raises(ValueError, match="exceeds 64-char MCP Directory limit"):
        agent.build_app()


def test_sc_c5_tool_name_exactly_64_ok(settings, fake_model):
    """A tool name of exactly 64 chars must be accepted."""
    extra = ToolSet()

    from pydantic import BaseModel as PM

    class _Empty(PM):
        pass

    from agent_sdk.agent.registry import ToolDecl

    import asyncio as _asyncio

    async def _fn() -> None:
        pass

    name_64 = "a" * 64
    extra.decls.append(
        ToolDecl(
            fn=_fn,
            name=name_64,
            description="Exactly 64",
            tier=1,
            emits=None,
            sample=None,
            input_model=_Empty,
            adapter_params={},
            title=None,
            annotations=None,
        )
    )

    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [extra]
    app = agent.build_app()  # should not raise
    app.state.credential_store.close()
    gc.collect()


# ---------------------------------------------------------------------------
# SC-C6: Auto-derived title for tools registered without explicit title=
# ---------------------------------------------------------------------------


def test_sc_c6_auto_derived_title_snake_case():
    """A tool registered via @tools.tool() without title= gets an auto-derived
    title from its snake_case function name (e.g. get_user_profile → 'Get User Profile')."""
    extra = ToolSet()

    @extra.tool(tier=1, read_only=True)
    async def get_user_profile() -> None:
        """Get user profile."""

    decl = extra.decls[0]
    assert decl.title == "Get User Profile", (
        f"expected auto-derived title 'Get User Profile', got {decl.title!r}"
    )


def test_sc_c6_explicit_title_not_overridden():
    """A tool registered with an explicit title= must keep that title exactly."""
    extra = ToolSet()

    @extra.tool(tier=1, read_only=True, title="My Custom Title")
    async def get_user_profile() -> None:
        """Get user profile."""

    decl = extra.decls[0]
    assert decl.title == "My Custom Title", (
        f"explicit title should be preserved, got {decl.title!r}"
    )


async def test_sc_c6_auto_title_appears_in_tools_list_wire(client):
    """A tool with no explicit title= must appear with its auto-derived title
    in the tools/list wire response."""
    headers = await _mcp_init(client)

    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    echo = next((t for t in tools if t["name"] == "echo"), None)
    assert echo is not None, "echo tool not found in tools/list"
    # echo is registered with explicit title="Echo" in example/agent.py
    assert echo.get("title") == "Echo", (
        f"echo title should be 'Echo', got {echo.get('title')!r}"
    )
    demo_kpis = next((t for t in tools if t["name"] == "demo_kpis"), None)
    assert demo_kpis is not None, "demo_kpis tool not found in tools/list"
    assert demo_kpis.get("title") == "Demo Kpis", (
        f"demo_kpis title should be 'Demo Kpis', got {demo_kpis.get('title')!r}"
    )


# ---------------------------------------------------------------------------
# SC-C7: MarketBriefing tools/call structuredContent must be a JSON object
#         wrapping the markdown string (MCP 2025-06-18 object-only requirement;
#         GH-105). The bare-string AG-UI/A2A wire contract stays untouched on
#         translator.py — see tests/test_a2ui_wire.py.
# ---------------------------------------------------------------------------


@pytest.fixture
def sc_c7_app(settings, fake_model):
    """App with a tool that declares emits=MarketBriefing and returns a
    MarketBriefing instance, so the MCP route must emit structuredContent as a
    JSON object wrapping the markdown ({"markdown": to_markdown()}), never a
    bare string or the field dict (wire()) — GH-105, MCP 2025-06-18."""
    from pydantic import BaseModel as PM

    from agent_sdk.agent.registry import ToolDecl
    from agent_sdk.models.content_types import MarketBriefing

    class _Empty(PM):
        pass

    async def briefing_tool(inp: _Empty):  # noqa: no return annotation — SC-F1 compliance
        """Return a MarketBriefing."""
        return MarketBriefing(title="Weekly Wrap", as_of="2026-06-16", prose="Markets flat.")

    extra = ToolSet()
    extra.decls.append(
        ToolDecl(
            fn=briefing_tool,
            name="briefing_tool",
            description="Return a MarketBriefing.",
            tier=1,
            emits=MarketBriefing,
            sample=None,
            input_model=_Empty,
            adapter_params={},
            title=None,
            annotations=None,
        )
    )

    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [extra]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def sc_c7_client(sc_c7_app):
    async with sc_c7_app.router.lifespan_context(sc_c7_app):
        _, token = sc_c7_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=sc_c7_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_sc_c7_market_briefing_structured_content_is_object(sc_c7_client):
    """GH-105: MCP 2025-06-18 requires Tool.outputSchema and
    CallToolResult.structuredContent to always be JSON objects. tools/call for
    a tool with emits=MarketBriefing must return structuredContent as an
    object wrapping the markdown string ({"markdown": ...}), not a bare
    string. The outputSchema in tools/list must advertise an object schema
    with a required "markdown" string property. content[0].text still
    carries the raw markdown unchanged."""
    headers = await _mcp_init(sc_c7_client)

    # 1. Verify tools/list advertises an object outputSchema.
    r_list = await sc_c7_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r_list.status_code == 200, r_list.text
    tools = r_list.json()["result"]["tools"]
    briefing = next((t for t in tools if t["name"] == "briefing_tool"), None)
    assert briefing is not None, "briefing_tool not found in tools/list"
    output_schema = briefing.get("outputSchema")
    assert output_schema is not None, "outputSchema must be present for emits=MarketBriefing"
    assert output_schema == {
        "type": "object",
        "properties": {"markdown": {"type": "string"}},
        "required": ["markdown"],
    }, (
        f"outputSchema for MarketBriefing must be an object schema wrapping "
        f"'markdown', got: {output_schema!r}"
    )

    # 2. Verify tools/call returns structuredContent as an object, not a bare string.
    r_call = await sc_c7_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "briefing_tool", "arguments": {}},
        },
        headers=headers,
    )
    assert r_call.status_code == 200, r_call.text
    result = r_call.json()["result"]
    assert result.get("isError") is False, f"Unexpected error: {result}"
    assert "structuredContent" in result, (
        "structuredContent MUST be present when emits=MarketBriefing is declared"
    )
    sc = result["structuredContent"]
    assert isinstance(sc, dict), (
        f"structuredContent for MarketBriefing must be a JSON object, got {type(sc).__name__}: {sc!r}"
    )
    assert set(sc.keys()) == {"markdown"}, f"expected only 'markdown' key, got: {sc!r}"
    assert isinstance(sc["markdown"], str), (
        f"structuredContent['markdown'] must be a string, got {type(sc['markdown']).__name__}"
    )
    assert "Weekly Wrap" in sc["markdown"], (
        f"Expected 'Weekly Wrap' in markdown output, got: {sc['markdown']!r}"
    )
    assert "Markets flat." in sc["markdown"], (
        f"Expected prose 'Markets flat.' in markdown output, got: {sc['markdown']!r}"
    )

    # content[0].text still carries the raw markdown unchanged (unwrapped).
    text_block = result["content"][0]["text"]
    assert text_block == sc["markdown"], (
        "content[0].text must carry the same raw markdown as structuredContent['markdown']"
    )


async def test_rt004_agent_card_omits_output_schema_mcp_keeps_it(sc_c7_client):
    """RT-004 (rewritten, GH-219): the agent card no longer repeats each
    skill's outputSchema; MCP tools/list is the one place that carries it,
    including the MarketBriefing object wrapper (GH-105).
    Ruling: https://github.com/wailuen/a2a-sdk/issues/219#issuecomment-6345507008"""
    card_r = await sc_c7_client.get("/.well-known/agent-card.json")
    assert card_r.status_code == 200, card_r.text
    card = card_r.json()
    briefing_skill = next((s for s in card["skills"] if s["id"] == "briefing_tool"), None)
    assert briefing_skill is not None, "briefing_tool skill not found in agent card"
    assert "outputSchema" not in briefing_skill["x-sdk"]
    assert "inputSchema" in briefing_skill["x-sdk"]

    headers = await _mcp_init(sc_c7_client)
    r_list = await sc_c7_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    tools = r_list.json()["result"]["tools"]
    briefing = next(t for t in tools if t["name"] == "briefing_tool")
    assert briefing["outputSchema"] == {
        "type": "object",
        "properties": {"markdown": {"type": "string"}},
        "required": ["markdown"],
    }


async def test_rt001_agent_card_has_no_wire_note(sc_c7_client):
    """RT-001 (rewritten, GH-219): with outputSchema gone from the card, the
    outputSchemaWireNote that guarded it is gone too.
    Ruling: https://github.com/wailuen/a2a-sdk/issues/219#issuecomment-6345507008"""
    card = (await sc_c7_client.get("/.well-known/agent-card.json")).json()
    briefing_skill = next(s for s in card["skills"] if s["id"] == "briefing_tool")
    assert "outputSchemaWireNote" not in briefing_skill["x-sdk"]


# ---------------------------------------------------------------------------
# SC-C8: GH-52 — openWorldHint seeded by default; corrected by GH-134
#
# MCP 2025-06-18: openWorldHint defaults to True when absent, which causes
# Claude.ai's consent UI to flag pure local tools as world-altering.
# GH-52 (w016) originally seeded openWorldHint=False for tier==1 OR
# read_only=True — but tying it to tier overgeneralized the fix: a tier-1
# tool backed by a SourceAdapter DOES talk to an external system and should
# be open-world. GH-134 corrects this: the SDK seeds openWorldHint=True when
# the tool has at least one SourceAdapter-backed (keyword-only) parameter,
# False otherwise — independent of tier and read_only. read_only's
# readOnlyHint/destructiveHint seeding is unaffected.
# ---------------------------------------------------------------------------


class _AdapterBackedFakeSource(SourceAdapter):
    source_name = "sc_c8_fake_source"
    allowed_hosts = ["example.com"]


async def test_sc_c8_echo_open_world_hint_false(client):
    """echo (tier=1, read_only=True) must have annotations.openWorldHint=False."""
    headers = await _mcp_init(client)

    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    echo = next((t for t in tools if t["name"] == "echo"), None)
    assert echo is not None, "echo tool not found in tools/list"
    annotations = echo.get("annotations", {})
    assert annotations.get("openWorldHint") is False, (
        f"echo.annotations.openWorldHint should be False (GH-52), got: {annotations}"
    )


async def test_sc_c8_demo_kpis_open_world_hint_false(client):
    """demo_kpis (tier=1, read_only=True) must have annotations.openWorldHint=False."""
    headers = await _mcp_init(client)

    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    demo_kpis = next((t for t in tools if t["name"] == "demo_kpis"), None)
    assert demo_kpis is not None, "demo_kpis tool not found in tools/list"
    annotations = demo_kpis.get("annotations", {})
    assert annotations.get("openWorldHint") is False, (
        f"demo_kpis.annotations.openWorldHint should be False (GH-52), got: {annotations}"
    )


def test_sc_c8_tier1_non_adapter_tool_open_world_hint_false():
    """A tier-1 tool with NO SourceAdapter-backed parameter must get
    openWorldHint=False — it never talks to an external system, regardless
    of tier (GH-134: this must no longer depend on tier==1 alone)."""
    extra = ToolSet()

    @extra.tool(tier=1)
    async def query_only() -> None:
        """A tier-1 query tool with no adapter parameters."""

    decl = extra.decls[0]
    assert decl.annotations is not None, (
        "tier-1 non-adapter tool should have annotations dict seeded (openWorldHint=False)"
    )
    assert decl.annotations.get("openWorldHint") is False, (
        f"tier-1 tool with no SourceAdapter-backed parameter must get "
        f"openWorldHint=False, got: {decl.annotations}"
    )


def test_sc_c8_tier1_adapter_backed_tool_open_world_hint_true():
    """A tier-1 tool with a SourceAdapter-backed keyword-only parameter must
    get openWorldHint=True — it talks to an external system (GH-134). Tier
    alone must no longer force openWorldHint=False for adapter-backed tools."""
    extra = ToolSet()

    @extra.tool(tier=1)
    async def query_upstream(*, source: _AdapterBackedFakeSource) -> None:
        """A tier-1 tool backed by a SourceAdapter."""

    decl = extra.decls[0]
    assert decl.annotations is not None
    assert decl.annotations.get("openWorldHint") is True, (
        f"tier-1 SourceAdapter-backed tool must get openWorldHint=True (GH-134), "
        f"got: {decl.annotations}"
    )


def test_sc_c8_tier2_adapter_backed_tool_open_world_hint_true():
    """A tier-2 tool with a SourceAdapter-backed keyword-only parameter must
    get openWorldHint=True — the same adapter-backed rule applies regardless
    of tier (GH-134)."""
    extra = ToolSet()

    @extra.tool(tier=2)
    async def compose_upstream(*, source: _AdapterBackedFakeSource) -> None:
        """A tier-2 composite tool backed by a SourceAdapter."""

    decl = extra.decls[0]
    assert decl.annotations is not None
    assert decl.annotations.get("openWorldHint") is True, (
        f"tier-2 SourceAdapter-backed tool must get openWorldHint=True (GH-134), "
        f"got: {decl.annotations}"
    )


def test_sc_c8_tier2_non_read_only_non_adapter_tool_annotations_seeded():
    """RT-015: a tier-2, non-``read_only``, non-adapter tool with no explicit
    ``annotations=`` still gets a populated ``decl.annotations`` dict —
    ``{"openWorldHint": False}`` — never ``None``. Before GH-134,
    ``openWorldHint`` was seeded only for ``tier == 1 or read_only``, so this
    exact shape (tier=2, read_only=False) fell through to ``ann or None`` ==
    ``None``. GH-134 seeds ``openWorldHint`` unconditionally, so this shape
    now always carries a dict; pin it explicitly so the shape change is
    covered by a test, not just the CHANGELOG note."""
    extra = ToolSet()

    @extra.tool(tier=2)
    async def compose_only() -> None:
        """A tier-2 composite tool with no adapter parameters, not read_only."""

    decl = extra.decls[0]
    assert decl.annotations == {"openWorldHint": False}, (
        f"tier-2 non-adapter, non-read_only tool must get a seeded "
        f"{{'openWorldHint': False}} dict, never None, got: {decl.annotations}"
    )


def test_sc_c8_explicit_annotations_can_override_open_world_hint():
    """An explicit annotations={'openWorldHint': True} must override the seeded
    default, allowing callers to opt out field-by-field."""
    extra = ToolSet()

    @extra.tool(tier=1, annotations={"openWorldHint": True})
    async def special_tool() -> None:
        """A tier-1 tool that explicitly opts into openWorldHint=True."""

    decl = extra.decls[0]
    assert decl.annotations is not None
    assert decl.annotations.get("openWorldHint") is True, (
        f"explicit annotations dict must override seeded openWorldHint=False, "
        f"got: {decl.annotations}"
    )


def test_sc_c8_explicit_open_world_hint_override_wins():
    """GH-134: `resolved_annotations.update(annotations or {})` runs after the
    adapter-derived seed, so an explicit annotations= entry must win in BOTH
    directions — overriding an adapter-backed tool's seeded True down to
    False, and overriding a non-adapter tool's seeded False up to True."""
    extra = ToolSet()

    @extra.tool(tier=1, annotations={"openWorldHint": False})
    async def adapter_backed_but_forced_closed(*, source: _AdapterBackedFakeSource) -> None:
        """A tier-1 SourceAdapter-backed tool that explicitly forces openWorldHint=False."""

    @extra.tool(tier=1, annotations={"openWorldHint": True})
    async def non_adapter_but_forced_open() -> None:
        """A tier-1 non-adapter tool that explicitly forces openWorldHint=True."""

    adapter_decl = next(
        d for d in extra.decls if d.name == "adapter_backed_but_forced_closed"
    )
    non_adapter_decl = next(
        d for d in extra.decls if d.name == "non_adapter_but_forced_open"
    )

    assert adapter_decl.annotations is not None
    assert adapter_decl.annotations["openWorldHint"] is False, (
        f"explicit annotations={{'openWorldHint': False}} must override the "
        f"adapter-derived seed of True, got: {adapter_decl.annotations}"
    )

    assert non_adapter_decl.annotations is not None
    assert non_adapter_decl.annotations["openWorldHint"] is True, (
        f"explicit annotations={{'openWorldHint': True}} must override the "
        f"non-adapter seed of False, got: {non_adapter_decl.annotations}"
    )


# ---------------------------------------------------------------------------
# RT-008: a tier-2 tool with no SourceAdapter-backed parameter is seeded
# openWorldHint=False (LRN-043's landed rule — correct and unchanged by this
# finding). A tier-2 *composite* tool is the shape most likely to reach an
# external system by a route other than a declared adapter parameter (a
# nested call into another tool's function, a contrib source that doesn't
# follow the SourceAdapter contract), so registration logs a WARNING
# pointing the author at the annotations={"openWorldHint": True} escape
# hatch — RT-008 does not change the derivation (see docstring in
# registry.py / LRN-043 for why bool(adapter_params) is a complete
# derivation under the SDK's DI contract), only closes the discoverability
# gap for the one case that finding raised.
# ---------------------------------------------------------------------------

REGISTRY_LOGGER = "agent_sdk.agent.registry"


def test_rt008_tier2_non_adapter_tool_warns_open_world_hint(sdk_caplog):
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=2)
        async def compose_only() -> None:
            """A tier-2 composite tool with no adapter parameters."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert warnings, (
        "expected a WARNING for a tier-2 tool with no SourceAdapter-backed "
        "parameter and no explicit openWorldHint override"
    )
    msg = warnings[0].getMessage()
    assert "compose_only" in msg, f"warning must name the tool; got: {msg!r}"
    assert "openWorldHint" in msg, f"warning must name the annotation; got: {msg!r}"
    assert tools.decls[0].annotations == {"openWorldHint": False}


def test_rt008_tier2_non_adapter_tool_explicit_override_no_warning(sdk_caplog):
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=2, annotations={"openWorldHint": True})
        async def compose_reaches_out() -> None:
            """A tier-2 composite tool that explicitly declares open-world reach."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert not warnings, (
        f"expected no WARNING when openWorldHint is explicitly overridden; "
        f"got: {[r.getMessage() for r in warnings]}"
    )
    assert tools.decls[0].annotations == {"openWorldHint": True}


def test_rt008_tier2_adapter_backed_tool_no_warning(sdk_caplog):
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=2)
        async def compose_upstream(*, source: _AdapterBackedFakeSource) -> None:
            """A tier-2 composite tool backed by a SourceAdapter."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert not warnings, (
        f"expected no WARNING for an adapter-backed tool (openWorldHint=True "
        f"is correct without an override); got: {[r.getMessage() for r in warnings]}"
    )


def test_rt008_tier1_non_adapter_tool_no_warning(sdk_caplog):
    """RT-008's warning is scoped to tier-2 (composite) tools only — a tier-1
    query tool with no adapter parameter is the common, well-covered case
    GH-134's own test suite (SC-C8) already pins; warning on it would be
    noise on every plain query tool in the SDK."""
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=1)
        async def query_only() -> None:
            """A tier-1 query tool with no adapter parameters."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert not warnings, (
        f"expected no WARNING for a tier-1 non-adapter tool; got: "
        f"{[r.getMessage() for r in warnings]}"
    )
