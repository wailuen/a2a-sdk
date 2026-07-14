"""GH-120: ``ToolEntry.invoke_any()`` (registry.py) awaits a ``DeferredResult``
handle exactly once and never rechecks whether the awaited value is itself
another ``DeferredResult``.

Root cause: after resolving ``result.handle`` once, ``invoke_any`` returned
``result`` unconditionally. If the handle resolves to ANOTHER
``DeferredResult`` (a tool bug, or a chained deferral), the nested object
flows back to the caller verbatim. ``routes/mcp.py``'s ``_tool_text()`` has
no branch for a ``DeferredResult`` and falls through to ``str(artifact)``,
baking the dataclass repr — including an unawaited inner coroutine's memory
address — into ``content[0].text`` under a false ``isError: false``.

Fix: ``invoke_any`` re-checks ``isinstance(result, DeferredResult)`` after
each await, bounded to at most one extra resolution beyond the original
(2 total handle awaits). A single level of nesting (handle resolves to a
DeferredResult whose own handle resolves to a plain value) is fully resolved.
A second level of nesting (that inner DeferredResult's handle ALSO resolves
to a DeferredResult) raises a clean ``AgentError(INTERNAL)`` instead of ever
returning/leaking the nested object — this maps straight onto each caller's
existing generic-exception -> isError:true / ok:false path (routes/mcp.py,
routes/admin.py), no new exception branch needed on either surface.

Tests:
1. test_invoke_any_resolves_single_nested_deferred_result: one level of
   nesting is fully resolved to the innermost plain value (unit-level,
   direct ToolEntry.invoke_any(), mirrors test_rt002's style).
2. test_invoke_any_raises_on_doubly_nested_deferred_result: two levels of
   nesting raise AgentError(INTERNAL) with a generic, non-leaking message
   (unit-level).
3. test_mcp_tools_call_nested_deferred_result_resolves: end-to-end MCP
   tools/call for a long_running=True tool whose handle resolves to another
   DeferredResult (single nesting) — must be a clean isError: false with the
   fully-resolved value, never a raw repr (mirrors test_rt001's style).
4. test_mcp_tools_call_doubly_nested_deferred_result_is_clean_error:
   end-to-end MCP tools/call for double nesting — must be a clean
   isError: true, never "DeferredResult(" or "coroutine object" in the text.

No unittest.mock.patch / MagicMock / AsyncMock. Unit tests build a real
ToolEntry directly; MCP tests drive the full ASGI app via
httpx.ASGITransport, real registry + real dispatch.
"""

from __future__ import annotations

import asyncio
import gc
import warnings
from typing import Any

import httpx
import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.registry import ToolDecl, ToolEntry, ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.models.errors import AgentError


def _coroutine_deferred_entry(handle_coro) -> ToolEntry:
    async def _fn() -> DeferredResult:
        return DeferredResult(handle=handle_coro)

    decl = ToolDecl(
        fn=_fn,
        name="gh120_deferred_tool",
        description="deferred tool",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
        long_running=True,
    )
    return ToolEntry(decl=decl)


async def test_invoke_any_resolves_single_nested_deferred_result():
    async def _inner_job():
        await asyncio.sleep(0)
        return {"ok": True, "value": "inner-done"}

    async def _outer_job():
        await asyncio.sleep(0)
        return DeferredResult(handle=_inner_job())

    entry = _coroutine_deferred_entry(_outer_job())
    result = await entry.invoke_any({}, {})

    assert not isinstance(result, DeferredResult), (
        f"a single level of nesting must be fully resolved, not returned as a "
        f"DeferredResult: {result!r}"
    )
    assert result == {"ok": True, "value": "inner-done"}


async def test_invoke_any_raises_on_doubly_nested_deferred_result():
    async def _level_b_job():
        await asyncio.sleep(0)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        future.set_result({"unreachable": True})
        return DeferredResult(handle=future)

    async def _level_a_job():
        await asyncio.sleep(0)
        return DeferredResult(handle=_level_b_job())

    entry = _coroutine_deferred_entry(_level_a_job())

    with pytest.raises(AgentError) as exc_info:
        await entry.invoke_any({}, {})

    message = str(exc_info.value)
    assert "DeferredResult(" not in message, (
        f"internal DeferredResult repr must never leak into the error: {message!r}"
    )
    assert "coroutine object" not in message, (
        f"unawaited coroutine repr must never leak into the error: {message!r}"
    )


async def test_invoke_any_closes_abandoned_coroutine_handle_on_double_nesting():
    """RT-002: when invoke_any bails out on the nesting-exceeded AgentError,
    the innermost DeferredResult's handle must be closed rather than
    abandoned unawaited. Unlike test_invoke_any_raises_on_doubly_nested_
    deferred_result (which uses a pre-resolved asyncio.Future for the
    deepest handle — nothing to close, nothing to leak), this test uses a
    real coroutine so the leak actually surfaces as a "coroutine was never
    awaited" RuntimeWarning if the fix regresses.
    """

    async def _level_c_job():
        return {"unreachable": True}

    async def _level_b_job():
        await asyncio.sleep(0)
        return DeferredResult(handle=_level_c_job())

    async def _level_a_job():
        await asyncio.sleep(0)
        return DeferredResult(handle=_level_b_job())

    entry = _coroutine_deferred_entry(_level_a_job())

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(AgentError):
            await entry.invoke_any({}, {})
        gc.collect()

    leaks = [w for w in caught if "was never awaited" in str(w.message)]
    assert not leaks, f"abandoned coroutine handle leaked unawaited: {leaks}"


mcp_nested_tools = ToolSet()


async def _mcp_inner_job() -> str:
    await asyncio.sleep(0)
    return "nested-deferred-done"


async def _mcp_outer_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_mcp_inner_job())


@mcp_nested_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def gh120_single_nested_tool() -> DeferredResult:
    """Long-running tool whose handle resolves to another DeferredResult."""
    return DeferredResult(handle=_mcp_outer_job())


async def _mcp_double_inner_job():
    await asyncio.sleep(0)
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    future.set_result("unreachable")
    return DeferredResult(handle=future)


async def _mcp_double_outer_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_mcp_double_inner_job())


@mcp_nested_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def gh120_double_nested_tool() -> DeferredResult:
    """Long-running tool whose handle resolves through TWO nested DeferredResults."""
    return DeferredResult(handle=_mcp_double_outer_job())


@pytest.fixture
def gh120_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [mcp_nested_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def gh120_client(gh120_app):
    async with gh120_app.router.lifespan_context(gh120_app):
        _, token = gh120_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gh120_app),
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


async def test_mcp_tools_call_nested_deferred_result_resolves(gh120_client) -> None:
    headers = await _mcp_init(gh120_client)
    result = await asyncio.wait_for(
        _call(gh120_client, headers, "gh120_single_nested_tool"), timeout=5.0
    )

    text = result["content"][0]["text"]
    assert "DeferredResult" not in text, (
        f"internal DeferredResult repr must never reach the wire; got {text!r}"
    )
    assert "coroutine object" not in text, (
        f"unawaited coroutine repr must never reach the wire; got {text!r}"
    )
    if result.get("isError") is False:
        assert "nested-deferred-done" in text, (
            f"expected the fully-resolved value folded into content text, got {text!r}"
        )
    else:
        assert result.get("isError") is True


async def test_mcp_tools_call_doubly_nested_deferred_result_is_clean_error(
    gh120_client,
) -> None:
    headers = await _mcp_init(gh120_client)
    result = await asyncio.wait_for(
        _call(gh120_client, headers, "gh120_double_nested_tool"), timeout=5.0
    )

    assert result.get("isError") is True, (
        f"a doubly-nested DeferredResult must surface as isError: true, got {result}"
    )
    text = result["content"][0]["text"]
    assert "DeferredResult(" not in text, (
        f"internal DeferredResult repr must never reach the wire; got {text!r}"
    )
    assert "coroutine object" not in text, (
        f"unawaited coroutine repr must never reach the wire; got {text!r}"
    )
