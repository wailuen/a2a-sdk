"""GH-173 (round 7, fresh-lens): MCP must not turn a non-finite tool output
into an unhandled HTTP 500 or a lost reply.

Root cause: both MCP writers serialize strictly (Starlette ``JSONResponse``
and the legacy ``json.dumps(..., allow_nan=False)``), but nothing between
``_handle_tools_call`` building ``structuredContent`` and the writer checked
the payload could be written. A value that bypassed validation
(``model_construct``, assignment after construction) raised ``ValueError``
out of the route.

Contract asserted here:
* ``tools/call`` whose output cannot be written is an ``isError: true``
  RESULT with fixed text (MCP §5.5: tool faults are results), on BOTH the
  Streamable HTTP and the legacy HTTP+SSE transport.
* Any other unwritable response still gets a fixed -32603 error for its id;
  the legacy POST still acks 202 and the SSE client still gets a reply.
* No ``NaN``/``Infinity`` literal reaches the wire (SI-2: no value echo).
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.models.content_types import BarChart, BarItem
from agent_sdk.routes import mcp as mcp_route
from agent_sdk.routes.mcp import _sse_queues

_LITERAL = re.compile(r"\b(nan|-?inf(inity)?)\b", re.IGNORECASE)

_tools = ToolSet()


@_tools.tool(tier=1, emits=BarChart, read_only=True)
async def nan_bars() -> BarChart:
    """Returns a bar chart whose value bypassed validation."""
    return BarChart.model_construct(
        bars=[BarItem.model_construct(category="a", value=float("nan"))]
    )


@_tools.tool(tier=1, emits=BarChart, read_only=True)
async def ok_bars() -> BarChart:
    """Returns a valid bar chart."""
    return BarChart(bars=[BarItem(category="a", value=1.5)])


def _use_tools(client) -> None:
    client.app.state.registry = ToolRegistry([_tools], {})


async def _mcp_init(client) -> dict[str, str]:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r.status_code == 200, r.text
    return {
        "mcp-session-id": r.headers["mcp-session-id"],
        "mcp-protocol-version": "2025-06-18",
    }


def _call(name: str, rid: int = 7) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": name, "arguments": {}}}


async def test_streamable_tools_call_non_finite_is_is_error_result(client):
    _use_tools(client)
    headers = await _mcp_init(client)
    r = await client.post("/mcp", json=_call("nan_bars"), headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 7
    assert "error" not in body
    assert body["result"]["isError"] is True
    assert body["result"]["content"] == [
        {"type": "text", "text": "tool output not serializable"}
    ]
    assert "structuredContent" not in body["result"]
    assert not _LITERAL.search(r.text)


async def test_streamable_tools_call_finite_output_unchanged(client):
    _use_tools(client)
    headers = await _mcp_init(client)
    r = await client.post("/mcp", json=_call("ok_bars"), headers=headers)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["bars"][0]["value"] == 1.5


async def test_streamable_unwritable_response_is_internal_error_not_500(
    client, monkeypatch
):
    """Writer backstop: any dispatch response that still cannot be written
    becomes a fixed -32603 error for the same id, never a bare HTTP 500."""
    headers = await _mcp_init(client)

    async def bad_dispatch(app, message):
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"x": float("inf")}}

    monkeypatch.setattr(mcp_route, "_dispatch", bad_dispatch)
    r = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "jsonrpc": "2.0", "id": 9, "error": {"code": -32603, "message": "internal error"}
    }
    assert not _LITERAL.search(r.text)


async def _legacy_post(client, sid: str, message: dict):
    return await client.post(
        f"/mcp/messages?session_id={sid}",
        json=message,
        headers={"mcp-protocol-version": "2025-06-18"},
    )


async def _legacy_session_for(client) -> tuple[str, asyncio.Queue]:
    # Learn the owner key the route computes for this caller from one 404
    # probe, then register a session under it, as GET /mcp/sse would.
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    sid = "a" * 32
    captured: dict = {}
    real = mcp_route._identity_key

    def spy(identity):
        key = real(identity)
        captured["key"] = key
        return key

    # a placeholder record so the route reaches the owner comparison
    _sse_queues(client.app)[sid] = (queue, "placeholder-owner")
    mcp_route._identity_key = spy
    try:
        r = await _legacy_post(client, sid, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    finally:
        mcp_route._identity_key = real
    assert r.status_code == 404
    _sse_queues(client.app)[sid] = (queue, captured["key"])
    return sid, queue


async def test_legacy_tools_call_non_finite_still_replies(client):
    _use_tools(client)
    sid, queue = await _legacy_session_for(client)
    r = await _legacy_post(client, sid, _call("nan_bars", rid=11))
    assert r.status_code == 202, r.text
    assert queue.qsize() == 1
    raw = queue.get_nowait()
    assert not _LITERAL.search(raw)
    body = json.loads(raw)
    assert body["id"] == 11
    assert body["result"]["isError"] is True
    assert body["result"]["content"][0]["text"] == "tool output not serializable"


async def test_legacy_unwritable_response_enqueues_internal_error(client, monkeypatch):
    sid, queue = await _legacy_session_for(client)

    async def bad_dispatch(app, message):
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"x": float("nan")}}

    monkeypatch.setattr(mcp_route, "_dispatch", bad_dispatch)
    r = await _legacy_post(client, sid, {"jsonrpc": "2.0", "id": 12, "method": "tools/list"})
    assert r.status_code == 202, r.text
    raw = queue.get_nowait()
    assert not _LITERAL.search(raw)
    assert json.loads(raw) == {
        "jsonrpc": "2.0", "id": 12, "error": {"code": -32603, "message": "internal error"}
    }
