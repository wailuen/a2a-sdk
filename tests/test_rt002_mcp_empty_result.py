"""RT-002: MCP ``tools/call`` must not fold a ``None`` terminal artifact into
a fake success when the tool declares no ``emits``.

Before the fix, an async-generator Tier-1 tool that yields nothing at all
drains to ``ToolTerminalResult(value=None)`` (registry.py's ``invoke_gen``),
and an ordinary coroutine tool can simply ``return None``. When the tool
declares no ``emits``, ``_handle_tools_call``'s SC-C1 coercion is skipped
(``emits_type is None``) and the fold path ran ``_tool_text(None)`` ->
``str(None)`` -> the literal string ``"None"``, returned as
``{"content": [{"type": "text", "text": "None"}], "isError": False}`` — a
successful-looking result carrying no real content.

Tests:
1. test_mcp_tools_call_empty_generator_is_error: a long_running=True
   async-generator tool that yields nothing must return isError: true with a
   diagnostic, never the literal "None" text with isError: false.
2. test_mcp_tools_call_none_coroutine_is_error: an ordinary coroutine tool
   that returns None must behave identically (the symmetric case).
"""

from __future__ import annotations

import gc
from typing import Any, AsyncGenerator

import httpx
import pytest

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent

rt002_tools = ToolSet()


@rt002_tools.tool(tier=1, long_running=True)
async def rt002_empty_gen_tool() -> AsyncGenerator[Any, None]:
    """Async-generator tool that yields nothing at all."""
    return
    yield  # pragma: no cover - makes this an async generator function


@rt002_tools.tool(tier=1)
async def rt002_none_coroutine_tool() -> None:
    """Ordinary coroutine tool that returns None."""
    return None


@pytest.fixture
def rt002_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rt002_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def rt002_client(rt002_app):
    async with rt002_app.router.lifespan_context(rt002_app):
        _, token = rt002_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt002_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def _mcp_init(client: httpx.AsyncClient) -> dict[str, str]:
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


async def _call(client: httpx.AsyncClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, f"expected a JSON-RPC result, got {body}"
    return body["result"]


async def test_mcp_tools_call_empty_generator_is_error(rt002_client) -> None:
    headers = await _mcp_init(rt002_client)
    result = await _call(rt002_client, headers, "rt002_empty_gen_tool")

    assert result.get("isError") is True, (
        f"a generator tool with no terminal yield must not report success; got {result}"
    )
    text = result["content"][0]["text"]
    assert text != "None", f"literal 'None' text must never reach the wire; got {text!r}"


async def test_mcp_tools_call_none_coroutine_is_error(rt002_client) -> None:
    headers = await _mcp_init(rt002_client)
    result = await _call(rt002_client, headers, "rt002_none_coroutine_tool")

    assert result.get("isError") is True, (
        f"a coroutine tool returning None must not report success; got {result}"
    )
    text = result["content"][0]["text"]
    assert text != "None", f"literal 'None' text must never reach the wire; got {text!r}"
