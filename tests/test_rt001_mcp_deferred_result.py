"""RT-001/RT-002: MCP ``tools/call`` must handle Tier-1 ``long_running=True``
coroutine tools that return ``DeferredResult`` — the OTHER long-running form
besides the async-generator one GH-115 (LRN-116) fixed.

Before the fix, ``_handle_tools_call``'s non-generator branch called
``entry.invoke()`` and folded whatever it returned via ``_tool_text`` /
``str()`` — a ``DeferredResult`` was never awaited, so the handle coroutine
was silently dropped and the caller received ``isError: false`` with
``content[0].text`` containing the internal ``DeferredResult(handle=<coroutine
object ...>, ...)`` repr, leaking an object address on the wire.

Also (RT-002): neither the generator nor the non-generator branch applied any
timeout budget, so a hanging tool blocked the MCP request indefinitely.

Tests:
1. test_mcp_tools_call_deferred_result_resolves: a long_running=True coroutine
   tool returning ``DeferredResult(handle=<fast coroutine>)`` must resolve the
   handle inline and fold the RESOLVED value — never a DeferredResult repr.
2. test_mcp_tools_call_deferred_result_timeout: a DeferredResult whose handle
   never resolves, under a small ``tool_timeout_override``, must return
   ``isError: true`` promptly rather than hanging or leaking a repr.
3. test_mcp_tools_call_coroutine_timeout: an ordinary (non-deferred) coroutine
   tool that never resolves, under a small ``tool_timeout_override``, must
   return ``isError: true`` promptly (the non-generator branch has a timeout
   budget applied, mirroring agent/loop.py).
4. test_mcp_tools_call_generator_timeout: an async-generator tool whose drain
   never finishes, under a small ``tool_timeout_override``, must return
   ``isError: true`` promptly (the generator branch has a timeout budget
   applied, mirroring agent/loop.py:445's asyncio.timeout wrap).

No unittest.mock.patch / MagicMock / AsyncMock. Drives the full ASGI app via
httpx.ASGITransport, real registry + real dispatch.

SI-2: assertions never require echoing tool names, exception text, or any
caller-supplied payload in the error responses.
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any, AsyncGenerator

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import ToolProgressEvent
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent


class _DeferredPayload(BaseModel):
    data_type: str = "rt001_deferred_result"
    value: str = "deferred-done"


rt001_tools = ToolSet()


async def _fast_job() -> _DeferredPayload:
    await asyncio.sleep(0)
    return _DeferredPayload(value="deferred-done")


@rt001_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt001_deferred_tool() -> DeferredResult:
    """Long-running coroutine tool that returns a DeferredResult immediately."""
    return DeferredResult(handle=_fast_job(), estimated_seconds=1.0)


@rt001_tools.tool(tier=1, long_running=True, tool_timeout_override=0.05)
async def rt001_deferred_timeout_tool() -> DeferredResult:
    """DeferredResult whose handle never resolves."""
    return DeferredResult(handle=asyncio.sleep(9999))


@rt001_tools.tool(tier=1, tool_timeout_override=0.05)
async def rt001_hanging_coroutine_tool() -> str:
    """Ordinary coroutine tool that never resolves."""
    await asyncio.sleep(9999)
    return "unreachable"


@rt001_tools.tool(tier=1, long_running=True, tool_timeout_override=0.05)
async def rt001_hanging_generator_tool() -> AsyncGenerator[Any, None]:
    """Async-generator tool whose drain never finishes."""
    yield ToolProgressEvent(message="working", tool_name="rt001_hanging_generator_tool")
    await asyncio.sleep(9999)
    yield _DeferredPayload(value="unreachable")


@pytest.fixture
def rt001_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rt001_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def rt001_client(rt001_app):
    async with rt001_app.router.lifespan_context(rt001_app):
        _, token = rt001_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt001_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
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


async def test_mcp_tools_call_deferred_result_resolves(rt001_client) -> None:
    headers = await _mcp_init(rt001_client)
    result = await _call(rt001_client, headers, "rt001_deferred_tool")

    assert result.get("isError") is False, f"expected success, got {result}"
    text = result["content"][0]["text"]
    assert "DeferredResult" not in text, (
        f"internal DeferredResult repr must never reach the wire; got {text!r}"
    )
    assert "coroutine object" not in text, (
        f"unawaited coroutine repr must never reach the wire; got {text!r}"
    )
    assert "deferred-done" in text, (
        f"expected the RESOLVED handle value folded into content text, got {text!r}"
    )


async def test_mcp_tools_call_deferred_result_timeout(rt001_client) -> None:
    headers = await _mcp_init(rt001_client)
    result = await asyncio.wait_for(
        _call(rt001_client, headers, "rt001_deferred_timeout_tool"), timeout=5.0
    )
    assert result.get("isError") is True, f"expected isError on timeout, got {result}"


async def test_mcp_tools_call_coroutine_timeout(rt001_client) -> None:
    headers = await _mcp_init(rt001_client)
    result = await asyncio.wait_for(
        _call(rt001_client, headers, "rt001_hanging_coroutine_tool"), timeout=5.0
    )
    assert result.get("isError") is True, f"expected isError on timeout, got {result}"


async def test_mcp_tools_call_generator_timeout(rt001_client) -> None:
    headers = await _mcp_init(rt001_client)
    result = await asyncio.wait_for(
        _call(rt001_client, headers, "rt001_hanging_generator_tool"), timeout=5.0
    )
    assert result.get("isError") is True, f"expected isError on timeout, got {result}"
