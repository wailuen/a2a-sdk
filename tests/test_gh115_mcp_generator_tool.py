"""GH-115: MCP `tools/call` must dispatch async-generator Tier-1 tools via
``invoke_gen()``, mirroring the ``entry.decl.is_generator`` branch already
present in ``agent/loop.py`` (lines 441-446) for the A2A/AG-UI surfaces.

Before the fix, ``_handle_tools_call`` unconditionally called
``entry.invoke()``, which raises ``TypeError`` for a generator tool
(registry.py's ``invoke()`` docstring: "raises TypeError when called on a
generator tool"). The blanket ``except Exception`` in ``_handle_tools_call``
swallowed that into a generic ``isError: true`` result, breaking the module's
own "Tier 1 surface parity" guarantee (mcp.py's module docstring).

Tests:
1. test_mcp_tools_call_generator_tool_succeeds: a `long_running=True`
   async-generator Tier-1 tool must return a valid (non-isError) result with
   the terminal artifact's structuredContent.
2. test_mcp_tools_call_coroutine_tool_unchanged: an ordinary coroutine tool
   on the SAME app continues to behave exactly as before (regression guard).
"""

from __future__ import annotations

import gc
from typing import Any, AsyncGenerator

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolProgressEvent
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent


class _GenResult(BaseModel):
    data_type: str = "gen_result"
    value: str = "gen-done"


gen_tools = ToolSet()


@gen_tools.tool(tier=1, emits=_GenResult, long_running=True)
async def gh115_gen_tool() -> AsyncGenerator[Any, None]:
    """Async-generator Tier-1 tool: interim progress then a terminal result."""
    yield ToolProgressEvent(message="working", tool_name="gh115_gen_tool")
    yield _GenResult(value="gen-done")


@pytest.fixture
def gh115_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [gen_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def gh115_client(gh115_app):
    async with gh115_app.router.lifespan_context(gh115_app):
        _, token = gh115_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gh115_app),
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


async def test_mcp_tools_call_generator_tool_succeeds(gh115_client) -> None:
    """A long_running=True async-generator tool must NOT raise TypeError inside
    invoke() — tools/call must return a valid, non-isError result carrying the
    terminal artifact."""
    headers = await _mcp_init(gh115_client)

    r = await gh115_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "gh115_gen_tool", "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, f"expected a JSON-RPC result, got {body}"
    result = body["result"]
    assert result.get("isError") is False, (
        f"generator tool call must not be isError; got {result}"
    )
    assert result["content"][0]["text"], "expected non-empty text content"
    assert result.get("structuredContent") == {
        "data_type": "gen_result",
        "value": "gen-done",
    }, f"expected terminal artifact's fields in structuredContent, got {result.get('structuredContent')}"


async def test_mcp_tools_call_coroutine_tool_unchanged(gh115_client) -> None:
    """Regression guard: an ordinary coroutine tool (echo, built into the
    example agent) must keep working exactly as before on the same app."""
    headers = await _mcp_init(gh115_client)

    r = await gh115_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hi"}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result.get("isError") is False, f"echo tool call must not be isError; got {result}"
    assert "hi" in result["content"][0]["text"]
