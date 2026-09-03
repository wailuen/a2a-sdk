"""RT-002: ToolEntry.invoke_any() must unwrap a Reusable-returning tool's
result, mirroring agent/loop.py's own unwrap at loop.py:640-648.

Before this fix, invoke_any() (registry.py) returned a Reusable wrapper
verbatim to every caller EXCEPT agent/loop.py — which drives the live model
conversation directly via entry.invoke()/invoke_gen() and unwraps Reusable
itself so it can fold a ``__resolved__`` marker into ``messages`` (the
$ref:<kind> cross-turn mechanism, GH-148). The three callers of invoke_any()
— routes/mcp.py's ``tools/call``, routes/admin.py's try-tool endpoint, and
the commitments executor — have no ``messages`` transcript to fold a marker
into, so they cannot participate in that substitution/validation gate at all;
this is conversation-scoped (loop-only) BY DESIGN, not a gap this fix closes.
What they must not do is leak the internal wrapper object itself:

- routes/mcp.py's ``_handle_tools_call`` folded the wrapper's dataclass repr
  ("Reusable(value=..., kind=..., label=...)") into the wire text for a
  Tier-1 tool with no ``emits``, and raised the SC-C1 coercion's
  ValidationError ("tool output coercion failed") for a Tier-1 tool that
  DOES declare ``emits`` (coercing the raw wrapper, not its `.value`,
  against the declared model) — the identical tool call succeeding over
  A2A/AG-UI (loop.py unwraps first), a §5.6 surface-parity violation.
- routes/admin.py's ``try_tool`` leaked the wrapper's raw dataclass fields
  (``{"value": ..., "kind": ..., "label": ...}``) through ``_safe_result``
  instead of the tool's actual result shape.

Tests:
1. test_invoke_any_unwraps_plain_reusable: registry-level (hand-built
   ToolEntry, mirrors test_rt002_invoke_any_deferred_result.py's pattern) —
   invoke_any() must return ``.value``, never the Reusable wrapper.
2. test_invoke_any_unwraps_reusable_nested_in_deferred_result: a
   long_running coroutine tool whose DeferredResult handle resolves to a
   Reusable — invoke_any() must resolve both layers down to the plain value.
3. test_mcp_tools_call_reusable_no_emits_unwraps_to_value: end-to-end MCP
   tools/call — content text is the unwrapped value, never the dataclass
   repr.
4. test_mcp_tools_call_reusable_with_emits_unwraps_to_value: end-to-end MCP
   tools/call — a Tier-1 tool with ``emits`` returning a Reusable-wrapped
   ContentModel instance succeeds with structuredContent, never "tool output
   coercion failed".
5. test_mcp_tools_call_reusable_with_emits_dict_coerces_unwrapped_value:
   end-to-end MCP tools/call — the exact reported failure mode: a
   Reusable-wrapped raw dict must be SC-C1-coerced against the UNWRAPPED
   dict, not rejected because the coercion target was the wrapper itself.
6. test_admin_try_tool_reusable_no_emits_unwraps_to_value: end-to-end admin
   try-tool — result is the unwrapped value, never the wrapper's raw fields.
7. test_admin_try_tool_reusable_with_emits_unwraps_to_value: end-to-end
   admin try-tool — result is the ContentModel's ``_safe_result`` shape
   (value/data_type/text), never the wrapper's raw kind/label fields.
"""

from __future__ import annotations

import gc
from typing import Any

import httpx
import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.registry import ToolDecl, ToolEntry, ToolSet
from agent_sdk.agent.reuse import Reusable
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import KpiCard, MetricItem

pytestmark = pytest.mark.asyncio


# ── 1-2: registry-level (no ASGI app) ───────────────────────────────────────


async def test_invoke_any_unwraps_plain_reusable():
    async def _fn() -> Any:
        return Reusable(value="ENT_5831", kind="entity_id", label="PT IMC Pelita Logistik")

    decl = ToolDecl(
        fn=_fn,
        name="rt002_reusable_unit_tool",
        description="reusable tool",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
    )
    entry = ToolEntry(decl=decl)
    result = await entry.invoke_any({}, {})

    assert not isinstance(result, Reusable), (
        f"invoke_any must unwrap Reusable, not return the wrapper: {result!r}"
    )
    assert result == "ENT_5831"


async def test_invoke_any_unwraps_reusable_nested_in_deferred_result():
    async def _job() -> Reusable:
        return Reusable(value="ENT_9001", kind="entity_id", label="Other Co")

    async def _fn() -> DeferredResult:
        return DeferredResult(handle=_job())

    decl = ToolDecl(
        fn=_fn,
        name="rt002_deferred_reusable_unit_tool",
        description="deferred tool resolving to a reusable value",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
        long_running=True,
    )
    entry = ToolEntry(decl=decl)
    result = await entry.invoke_any({}, {})

    assert not isinstance(result, Reusable), (
        f"invoke_any must unwrap a Reusable a DeferredResult chain resolves "
        f"to, not return the wrapper: {result!r}"
    )
    assert not isinstance(result, DeferredResult)
    assert result == "ENT_9001"


# ── 3-7: end-to-end through MCP tools/call and the admin try-tool endpoint ──

rt002_reusable_tools = ToolSet()


@rt002_reusable_tools.tool(tier=1)
async def rt002_reusable_no_emits_tool() -> Any:
    """Reusable-returning tool with no emits declared."""
    return Reusable(value="ENT_5831", kind="entity_id", label="PT IMC Pelita Logistik")


@rt002_reusable_tools.tool(tier=1, emits=KpiCard)
async def rt002_reusable_with_emits_tool() -> Any:
    """Reusable-returning tool declaring emits, wrapping an already-built
    ContentModel instance — exercises the direct isinstance(artifact,
    BaseModel) path (no coercion needed) on both surfaces."""
    card = KpiCard(metrics=[MetricItem(label="Revenue", value=42)])
    return Reusable(value=card, kind="entity_id", label="PT IMC Pelita Logistik")


@rt002_reusable_tools.tool(tier=1, emits=KpiCard)
async def rt002_reusable_with_emits_dict_tool() -> Any:
    """Reusable-returning tool declaring emits, wrapping a raw dict —
    exercises MCP's SC-C1 coercion path against the UNWRAPPED value (the
    exact reported failure mode: coercing the raw Reusable dataclass against
    emits raises ValidationError -> 'tool output coercion failed')."""
    return Reusable(
        value={"metrics": [{"label": "Revenue", "value": 42}]},
        kind="entity_id",
        label="PT IMC Pelita Logistik",
    )


@pytest.fixture
def rt002_reusable_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rt002_reusable_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def rt002_reusable_client(rt002_reusable_app):
    async with rt002_reusable_app.router.lifespan_context(rt002_reusable_app):
        _, token = rt002_reusable_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt002_reusable_app),
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


async def test_mcp_tools_call_reusable_no_emits_unwraps_to_value(rt002_reusable_client) -> None:
    headers = await _mcp_init(rt002_reusable_client)
    result = await _call(rt002_reusable_client, headers, "rt002_reusable_no_emits_tool")

    assert result.get("isError") is False, (
        f"identical call succeeds over A2A/AG-UI (loop.py unwraps Reusable); "
        f"must not fail over MCP (§5.6 parity): {result}"
    )
    text = result["content"][0]["text"]
    assert text == "ENT_5831", (
        f"expected the unwrapped value on the wire, not the Reusable wrapper's "
        f"dataclass repr; got {text!r}"
    )
    assert "kind=" not in text and "label=" not in text, (
        f"Reusable wrapper's internal fields leaked onto the MCP wire: {text!r}"
    )


async def test_mcp_tools_call_reusable_with_emits_unwraps_to_value(rt002_reusable_client) -> None:
    headers = await _mcp_init(rt002_reusable_client)
    result = await _call(rt002_reusable_client, headers, "rt002_reusable_with_emits_tool")

    assert result.get("isError") is False, (
        f"identical call succeeds over A2A/AG-UI; must not fail over MCP "
        f"with 'tool output coercion failed' (§5.6 parity): {result}"
    )
    assert "structuredContent" in result, result
    assert result["structuredContent"] == {"metrics": [{"label": "Revenue", "value": 42}]}


async def test_mcp_tools_call_reusable_with_emits_dict_coerces_unwrapped_value(
    rt002_reusable_client,
) -> None:
    headers = await _mcp_init(rt002_reusable_client)
    result = await _call(rt002_reusable_client, headers, "rt002_reusable_with_emits_dict_tool")

    assert result.get("isError") is False, (
        f"SC-C1 coercion must run against the UNWRAPPED dict, not the raw "
        f"Reusable dataclass (the exact reported 'tool output coercion "
        f"failed' regression): {result}"
    )
    assert result["structuredContent"] == {"metrics": [{"label": "Revenue", "value": 42}]}


async def test_admin_try_tool_reusable_no_emits_unwraps_to_value(rt002_reusable_client) -> None:
    r = await rt002_reusable_client.post(
        "/admin/api/tools/rt002_reusable_no_emits_tool/try", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, body
    assert body["result"] == "ENT_5831", (
        f"expected the unwrapped value, not the Reusable wrapper's raw "
        f"fields; got {body['result']!r}"
    )


async def test_admin_try_tool_reusable_with_emits_unwraps_to_value(rt002_reusable_client) -> None:
    r = await rt002_reusable_client.post(
        "/admin/api/tools/rt002_reusable_with_emits_tool/try", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, body
    result = body["result"]
    assert set(result) == {"value", "data_type", "text"}, (
        f"expected _safe_result's ContentModel shape, not the Reusable "
        f"wrapper's raw {{'value', 'kind', 'label'}} fields; got {result}"
    )
    assert result["data_type"] == "kpi_card"
    assert result["value"] == {"metrics": [{"label": "Revenue", "value": 42}]}
