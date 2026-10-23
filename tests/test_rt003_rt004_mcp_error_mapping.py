"""RT-003/RT-004: MCP ``tools/call`` error mapping for the coroutine and
async-generator branches should mirror ``agent/loop.py``'s diagnostic error
mapping (``AgentError.public()``, ``safe_validation_message``, timeout,
generic fallback) rather than collapsing every non-``AgentError`` failure
(including a caller-correctable input ``ValidationError`` and a timeout) into
the single opaque ``"tool execution failed"`` string.

RT-004: adds ``except asyncio.TimeoutError`` and ``except ValidationError``
branches to ``_handle_tools_call``'s try block (both the coroutine and
async-generator paths), so:
- a bad-input call surfaces a redacted, schema-grounded, model-correctable
  message (via ``safe_validation_message`` — loc + type only, never the
  raw rejected value), distinct from the generic fallback;
- a timeout surfaces a distinct, diagnostic message, distinct from the
  generic fallback and from a validation failure.

RT-003: a Tier-1 coroutine tool that overruns its timeout budget must
surface ``isError: true`` promptly over MCP ``tools/call`` — the same bound
applied on the A2A/AG-UI surfaces (GH-115's non-generator branch now wraps
``entry.invoke()`` in ``asyncio.wait_for(..., timeout=resolve_tool_timeout(...))``,
so MCP is no longer timeout-unbounded on this path).
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any, AsyncGenerator

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolProgressEvent
from agent_sdk.agent.loop import ToolInterrupt
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.routes.mcp import MCP_INTERRUPT_SUFFIX


class _StrictInput(BaseModel):
    value: int


rt004_tools = ToolSet()


@rt004_tools.tool(tier=1, tool_timeout_override=5.0)
async def rt004_validation_tool(inp: _StrictInput) -> str:
    """Ordinary coroutine tool with a required-field input model."""
    return f"got {inp.value}"


@rt004_tools.tool(tier=1, long_running=True, tool_timeout_override=5.0)
async def rt004_gen_validation_tool(inp: _StrictInput) -> AsyncGenerator[Any, None]:
    """Async-generator tool with a required-field input model."""
    yield ToolProgressEvent(message="working", tool_name="rt004_gen_validation_tool")
    yield f"got {inp.value}"


@rt004_tools.tool(tier=1, tool_timeout_override=0.05)
async def rt003_hanging_coroutine_tool() -> str:
    """Ordinary coroutine tool that never resolves — timeout boundary probe."""
    await asyncio.sleep(9999)
    return "unreachable"


@rt004_tools.tool(tier=1, tool_timeout_override=5.0)
async def rt001_interrupt_coroutine_tool() -> str:
    """Ordinary coroutine tool that raises ToolInterrupt (e.g. action_gate)."""
    raise ToolInterrupt("confirm", "please confirm this action")


@rt004_tools.tool(tier=1, long_running=True, tool_timeout_override=5.0)
async def rt001_interrupt_gen_tool() -> AsyncGenerator[Any, None]:
    """Async-generator tool that raises ToolInterrupt mid-drain."""
    yield ToolProgressEvent(message="working", tool_name="rt001_interrupt_gen_tool")
    raise ToolInterrupt("confirm", "please confirm this action")


_NOISY_MESSAGE = "pay \x1b[31m$5\x9b now\x00" + "x" * 3000


@rt004_tools.tool(tier=1, tool_timeout_override=5.0)
async def gh204_message_tool() -> str:
    """Raises ToolInterrupt with a tool-authored message."""
    raise ToolInterrupt("confirm", "Delete invoice INV-7?")


@rt004_tools.tool(tier=1, tool_timeout_override=5.0)
async def gh204_empty_message_tool() -> str:
    """Raises ToolInterrupt with an empty message."""
    raise ToolInterrupt("confirm", "")


@rt004_tools.tool(tier=1, tool_timeout_override=5.0)
async def gh204_noisy_tool() -> str:
    """Raises ToolInterrupt with control chars, over-long message, noisy reason."""
    raise ToolInterrupt("re\x1b[0mason\nforged", _NOISY_MESSAGE)


@pytest.fixture
def rt004_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rt004_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def rt004_client(rt004_app):
    async with rt004_app.router.lifespan_context(rt004_app):
        _, token = rt004_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt004_app),
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


async def test_mcp_tools_call_validation_error_is_diagnostic(rt004_client) -> None:
    """A missing-required-field call to a coroutine tool must surface a
    redacted, schema-grounded message — not the opaque generic fallback."""
    headers = await _mcp_init(rt004_client)
    result = await _call(rt004_client, headers, "rt004_validation_tool")

    assert result.get("isError") is True, f"expected isError, got {result}"
    text = result["content"][0]["text"]
    assert text != "tool execution failed", (
        f"a ValidationError must not collapse into the generic fallback; got {text!r}"
    )
    assert "input invalid" in text, f"expected a diagnostic validation message, got {text!r}"
    assert "value" in text, f"expected the schema field name in the message, got {text!r}"


async def test_mcp_tools_call_generator_validation_error_is_diagnostic(rt004_client) -> None:
    """Same as above, but for the async-generator branch (GH-115 path)."""
    headers = await _mcp_init(rt004_client)
    result = await _call(rt004_client, headers, "rt004_gen_validation_tool")

    assert result.get("isError") is True, f"expected isError, got {result}"
    text = result["content"][0]["text"]
    assert text != "tool execution failed", (
        f"a ValidationError must not collapse into the generic fallback; got {text!r}"
    )
    assert "input invalid" in text, f"expected a diagnostic validation message, got {text!r}"
    assert "value" in text, f"expected the schema field name in the message, got {text!r}"


async def test_mcp_tools_call_timeout_is_diagnostic_not_generic(rt004_client) -> None:
    """RT-003: the coroutine timeout bound now applied by GH-115 must surface
    promptly as isError, with a message distinct from the opaque generic
    fallback and from the validation-error message."""
    headers = await _mcp_init(rt004_client)
    result = await asyncio.wait_for(
        _call(rt004_client, headers, "rt003_hanging_coroutine_tool"), timeout=5.0
    )

    assert result.get("isError") is True, f"expected isError on timeout, got {result}"
    text = result["content"][0]["text"]
    assert "timed out" in text, f"expected a distinct timeout diagnostic, got {text!r}"
    assert text != "tool execution failed", (
        f"a timeout must not collapse into the generic fallback; got {text!r}"
    )


async def test_mcp_tools_call_subsecond_timeout_not_rendered_as_zero(rt004_client) -> None:
    """RT-003: ``rt003_hanging_coroutine_tool``'s 0.05s budget (int(timeout)
    truncation) must not render as the misleading 'timed out after 0s'."""
    headers = await _mcp_init(rt004_client)
    result = await asyncio.wait_for(
        _call(rt004_client, headers, "rt003_hanging_coroutine_tool"), timeout=5.0
    )

    assert result.get("isError") is True, f"expected isError on timeout, got {result}"
    text = result["content"][0]["text"]
    assert "after 0s" not in text, (
        f"a sub-second timeout must not truncate to the misleading '0s', got {text!r}"
    )
    assert "0.05s" in text, f"expected the sub-second budget rendered accurately, got {text!r}"


async def test_mcp_tools_call_interrupt_is_diagnostic_not_generic(rt004_client) -> None:
    """RT-001: a Tier-1 coroutine tool raising ToolInterrupt (e.g. action_gate,
    example/agent.py) has no HITL/resume channel over MCP — it must surface a
    distinct isError diagnostic, not the opaque generic fallback."""
    headers = await _mcp_init(rt004_client)
    result = await _call(rt004_client, headers, "rt001_interrupt_coroutine_tool")

    assert result.get("isError") is True, f"expected isError, got {result}"
    text = result["content"][0]["text"]
    assert text != "tool execution failed", (
        f"a ToolInterrupt must not collapse into the generic fallback; got {text!r}"
    )
    assert text == f"please confirm this action {MCP_INTERRUPT_SUFFIX}", (
        f"expected the tool message plus the interrupt marker, got {text!r}"
    )


async def test_mcp_tools_call_generator_interrupt_is_diagnostic_not_generic(
    rt004_client,
) -> None:
    """Same as above, but for the async-generator branch (GH-115 path)."""
    headers = await _mcp_init(rt004_client)
    result = await _call(rt004_client, headers, "rt001_interrupt_gen_tool")

    assert result.get("isError") is True, f"expected isError, got {result}"
    text = result["content"][0]["text"]
    assert text != "tool execution failed", (
        f"a ToolInterrupt must not collapse into the generic fallback; got {text!r}"
    )
    assert text == f"please confirm this action {MCP_INTERRUPT_SUFFIX}", (
        f"expected the tool message plus the interrupt marker, got {text!r}"
    )


async def test_gh204_interrupt_shows_tool_message_then_suffix(rt004_client) -> None:
    headers = await _mcp_init(rt004_client)
    result = await _call(rt004_client, headers, "gh204_message_tool")
    assert result.get("isError") is True
    text = result["content"][0]["text"]
    assert text.startswith("Delete invoice INV-7?")
    assert text.endswith(MCP_INTERRUPT_SUFFIX)


async def test_gh204_empty_message_falls_back_to_fixed_text(rt004_client) -> None:
    headers = await _mcp_init(rt004_client)
    result = await _call(rt004_client, headers, "gh204_empty_message_tool")
    assert result.get("isError") is True
    text = result["content"][0]["text"]
    assert text.startswith("tool requires interactive confirmation, unsupported over MCP")
    assert text.endswith(MCP_INTERRUPT_SUFFIX)


async def test_gh204_action_gate_interrupt_over_mcp_is_error(rt004_client) -> None:
    headers = await _mcp_init(rt004_client)
    result = await _call(rt004_client, headers, "rt001_interrupt_coroutine_tool")
    assert result.get("isError") is True
    text = result["content"][0]["text"]
    assert text.startswith("please confirm this action")
    assert text.endswith(MCP_INTERRUPT_SUFFIX)


async def test_gh204_si2_wire_text_stripped_capped_and_log_reason_only(
    rt004_client, caplog
) -> None:
    import logging

    headers = await _mcp_init(rt004_client)
    with caplog.at_level(logging.WARNING):
        result = await _call(rt004_client, headers, "gh204_noisy_tool")
    text = result["content"][0]["text"]
    assert result.get("isError") is True
    assert text.endswith(MCP_INTERRUPT_SUFFIX)
    assert not any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in text)
    assert len(text) <= 1024 + 1 + len(MCP_INTERRUPT_SUFFIX)
    assert text.startswith("pay")
    log = "\n".join(r.getMessage() for r in caplog.records if "interrupt" in r.getMessage())
    assert "reason=re [0mason forged" in log
    assert "\x1b" not in log and "\n" not in log
    assert "pay" not in log and "xxxx" not in log
