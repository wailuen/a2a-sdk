"""RT-002/RT-001: MCP ``tools/call`` must not render the literal string
``"None"`` for a void Tier-1 tool, but it also must NOT diverge from
agent/loop.py's verdict for the identical result (§5.6 surface parity rule).

Before the RT-002 fix, an async-generator Tier-1 tool that yields nothing at
all drains to ``ToolTerminalResult(value=None)`` (registry.py's
``invoke_gen``), and an ordinary coroutine tool can simply ``return None``.
When the tool declares no ``emits``, ``_handle_tools_call``'s SC-C1 coercion
is skipped (``emits_type is None``) and the fold path ran ``_tool_text(None)``
-> ``str(None)`` -> the literal string ``"None"``, returned as
``{"content": [{"type": "text", "text": "None"}], "isError": False}``.

RT-002's own fix over-corrected: it flipped the same case to
``isError: True`` ("tool produced no result"), but agent/loop.py's
``run_loop`` folds this identical None result into a SUCCESS toolResult
(``_fold_result_content(None) -> {"text": ""}``, status "success") on the
A2A/AG-UI surfaces — so the same void Tier-1 tool call succeeded over
A2A/AG-UI yet failed over MCP, breaking surface parity (RT-001).

The corrected behaviour: fold ``None`` to ``isError: False`` with an empty
text block, matching loop.py exactly, while still never emitting the literal
string "None".

Tests:
1. test_mcp_tools_call_empty_generator_is_success: a long_running=True
   async-generator tool that yields nothing must return isError: false with
   empty text, never the literal "None" text.
2. test_mcp_tools_call_none_coroutine_is_success: an ordinary coroutine tool
   that returns None must behave identically (the symmetric case).

RT-002 (follow-up): the parity fix above only covered tools with NO ``emits``
declared. A Tier-1 tool that DOES declare ``emits`` but returns/yields None
fell through to the SC-C1 coercion block, where
``emits_type.model_validate(None)`` raises and the call returned
``isError: true`` ("tool output coercion failed") — diverging from the
identical void call succeeding over A2A/AG-UI. §5.6 parity must hold
regardless of whether the tool declares an output schema, so this must also
fold to ``isError: false`` with empty text and no ``structuredContent``.

3. test_mcp_tools_call_none_coroutine_with_emits_is_success: an ordinary
   coroutine tool that declares ``emits`` but returns None.
4. test_mcp_tools_call_empty_generator_with_emits_is_success: an
   async-generator tool that declares ``emits`` but yields no terminal value.
"""

from __future__ import annotations

import gc
from typing import Any, AsyncGenerator

import httpx
import pytest
from pydantic import BaseModel

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


class _Rt002Payload(BaseModel):
    data_type: str = "rt002_payload"
    value: str = "unused"


@rt002_tools.tool(tier=1, emits=_Rt002Payload)
async def rt002_none_coroutine_with_emits_tool() -> _Rt002Payload | None:
    """Coroutine tool that declares emits but returns None."""
    return None


@rt002_tools.tool(tier=1, emits=_Rt002Payload, long_running=True)
async def rt002_empty_gen_with_emits_tool() -> AsyncGenerator[Any, None]:
    """Async-generator tool that declares emits but yields no terminal value."""
    return
    yield  # pragma: no cover - makes this an async generator function


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


async def test_mcp_tools_call_empty_generator_is_success(rt002_client) -> None:
    headers = await _mcp_init(rt002_client)
    result = await _call(rt002_client, headers, "rt002_empty_gen_tool")

    assert result.get("isError") is False, (
        "a void Tier-1 tool must report the same verdict as agent/loop.py's "
        f"_fold_result_content(None) (SUCCESS); got {result}"
    )
    text = result["content"][0]["text"]
    assert text == "", f"None must fold to empty text, not the literal 'None'; got {text!r}"


async def test_mcp_tools_call_none_coroutine_is_success(rt002_client) -> None:
    headers = await _mcp_init(rt002_client)
    result = await _call(rt002_client, headers, "rt002_none_coroutine_tool")

    assert result.get("isError") is False, (
        "a void Tier-1 tool must report the same verdict as agent/loop.py's "
        f"_fold_result_content(None) (SUCCESS); got {result}"
    )
    text = result["content"][0]["text"]
    assert text == "", f"None must fold to empty text, not the literal 'None'; got {text!r}"


async def test_mcp_tools_call_none_coroutine_with_emits_is_success(rt002_client) -> None:
    headers = await _mcp_init(rt002_client)
    result = await _call(rt002_client, headers, "rt002_none_coroutine_with_emits_tool")

    assert result.get("isError") is False, (
        "a void Tier-1 tool must report SUCCESS regardless of whether it "
        f"declares emits — matching A2A/AG-UI's _fold_result_content(None); got {result}"
    )
    text = result["content"][0]["text"]
    assert text == "", f"None must fold to empty text, not the literal 'None'; got {text!r}"
    assert "structuredContent" not in result, (
        f"no structuredContent should be emitted for a None result; got {result}"
    )


async def test_mcp_tools_call_empty_generator_with_emits_is_success(rt002_client) -> None:
    headers = await _mcp_init(rt002_client)
    result = await _call(rt002_client, headers, "rt002_empty_gen_with_emits_tool")

    assert result.get("isError") is False, (
        "a void Tier-1 tool must report SUCCESS regardless of whether it "
        f"declares emits — matching A2A/AG-UI's _fold_result_content(None); got {result}"
    )
    text = result["content"][0]["text"]
    assert text == "", f"None must fold to empty text, not the literal 'None'; got {text!r}"
    assert "structuredContent" not in result, (
        f"no structuredContent should be emitted for a None result; got {result}"
    )
