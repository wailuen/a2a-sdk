"""MCP protocol conformance tests — wave 9, Group C (SC-C1 through SC-C5).

SC-C1  structuredContent for non-BaseModel emits (dict returned against declared emits=)
SC-C2  tools/list cursor/nextCursor pagination (PAGE_SIZE=64)
SC-C3  WWW-Authenticate challenge includes scope= parameter
SC-C4  Example tools (echo, demo_kpis) have annotations.destructiveHint=false
SC-C5  Tool name length > 64 raises ValueError at registration time
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from agent_sdk import BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
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
# SC-C3: WWW-Authenticate challenge includes scope=
# ---------------------------------------------------------------------------


async def test_sc_c3_www_authenticate_has_scope(client):
    """Unauthenticated request → 401 WWW-Authenticate header must contain scope=."""
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": ""},
    )
    assert r.status_code == 401
    www_auth = r.headers.get("www-authenticate", "")
    assert "scope=" in www_auth, f"Expected 'scope=' in WWW-Authenticate but got: {www_auth!r}"


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
