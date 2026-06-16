"""MCP protocol conformance tests — wave 10, Group D (M-1, L-1).

M-1  POST /mcp without Mcp-Session-Id on a non-initialize request, when the
     caller already has a live session, must be rejected with HTTP 400.
L-1  tools/call with an unknown tool name returns JSON-RPC -32601 (method not
     found), not -32602.  tools/call with a valid name but non-dict arguments
     still returns -32602 (invalid params).
"""

from __future__ import annotations

import gc

import httpx
import pytest

from agent_sdk.example.agent import make_agent


# ---------------------------------------------------------------------------
# Helpers (mirrors test_mcp_conformance_w9._mcp_init)
# ---------------------------------------------------------------------------


async def _mcp_init(client: httpx.AsyncClient) -> dict[str, str]:
    """Run MCP initialize handshake; return header dict including session id."""
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
# M-1: absent Mcp-Session-Id on a non-initialize request rejected with 400
# ---------------------------------------------------------------------------


async def test_m1_absent_session_id_after_init_returns_400(client: httpx.AsyncClient) -> None:
    """After a successful initialize (session established), a subsequent
    non-initialize POST that omits the Mcp-Session-Id header must return 400
    with JSON body {"error": "Mcp-Session-Id required"}."""
    # Establish a session for this caller.
    await _mcp_init(client)

    # Send a ping WITHOUT the Mcp-Session-Id header.
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        headers={"MCP-Protocol-Version": "2025-06-18"},
        # Deliberately omit Mcp-Session-Id
    )
    assert r.status_code == 400, (
        f"Expected 400 when Mcp-Session-Id absent and owner has live session; got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert body.get("error") == "Mcp-Session-Id required", (
        f"Unexpected error body: {body}"
    )


async def test_m1_absent_session_id_before_any_init_is_ok(client: httpx.AsyncClient) -> None:
    """Before any initialize has been called (no session exists for this owner),
    a non-initialize POST without Mcp-Session-Id must NOT return 400 — the
    request reaches dispatch normally (it may fail for other reasons, e.g.
    unknown method, but the session gate must not fire)."""
    # No initialize call — no live session for this owner.
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )
    # 400 from the session gate would be wrong; anything else is acceptable.
    assert r.status_code != 400 or r.json().get("error") != "Mcp-Session-Id required", (
        "Session gate must not fire when the owner has no established session"
    )


# ---------------------------------------------------------------------------
# L-1: unknown tool → -32601; bad arguments → -32602
# ---------------------------------------------------------------------------


async def test_l1_unknown_tool_returns_method_not_found(client: httpx.AsyncClient) -> None:
    """tools/call with a tool name that does not exist must return a JSON-RPC
    error with code -32601 (Method Not Found), not -32602."""
    headers = await _mcp_init(client)

    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool_xyz", "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" in body, f"Expected a JSON-RPC error object; got: {body}"
    code = body["error"]["code"]
    assert code == -32601, (
        f"Unknown tool must return -32601 (Method Not Found); got {code}"
    )


async def test_l1_malformed_arguments_returns_invalid_params(client: httpx.AsyncClient) -> None:
    """tools/call for a real tool with non-dict arguments must still return
    -32602 (Invalid Params) — the invalid-params path is unchanged."""
    headers = await _mcp_init(client)

    # 'echo' is the example tool guaranteed to exist in the example agent.
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            # arguments is a list, not a dict — invalid params
            "params": {"name": "echo", "arguments": ["not", "a", "dict"]},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" in body, f"Expected a JSON-RPC error object; got: {body}"
    code = body["error"]["code"]
    assert code == -32602, (
        f"Non-dict arguments must return -32602 (Invalid Params); got {code}"
    )
