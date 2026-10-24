"""Security regression tests — RT-001, RT-003, RT-004, RT-005.

RT-001  tools/list cursor must be clamped to ≥0; a crafted negative-offset
        cursor (e.g. base64('-1') = 'LTE=') must NOT wrap to the tail of the
        tool list.  (LRN-018)

RT-003  (superseded — see test_rt001_mcp_sse_stream_cap.py) Legacy SSE
        session map used to be bounded by a dedicated _MAX_SSE_SESSIONS
        evict-oldest loop. A later redteam finding (RT-001 on GH-143) found
        that eviction dropped only the bookkeeping entry, not the live
        stream, and was a cross-tenant DoS (it evicted regardless of owner).
        GET /mcp/sse now shares GET /mcp's reject-based _get_streams() cap
        instead; _MAX_SSE_SESSIONS no longer exists.

RT-004  DELETE /mcp, GET /mcp/sse, and POST /mcp/messages all reject a
        non-allowlisted Origin with 403, mirroring the guard on POST /mcp and
        GET /mcp.

RT-005  SI-2: tools/call with an unknown tool name returns the generic message
        'tool not found', NOT the caller-supplied name.  An unknown JSON-RPC
        method returns 'method not found', NOT the caller-supplied method string.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from agent_sdk.routes.mcp import _decode_cursor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _neg_cursor(n: int = -1) -> str:
    """Encode a negative integer as a base64 cursor string."""
    return base64.b64encode(str(n).encode()).decode()


# ---------------------------------------------------------------------------
# RT-001 — negative cursor clamped to 0
# ---------------------------------------------------------------------------


def test_decode_cursor_negative_rejected_by_unit() -> None:
    """GH-236: the shared decoder rejects a negative or undecodable cursor."""
    from agent_sdk.routes.mcp import _InvalidCursor

    crafted = base64.b64encode(b"-1").decode()
    assert crafted == "LTE="
    with pytest.raises(_InvalidCursor):
        _decode_cursor(crafted)


async def test_negative_cursor_does_not_wrap_tool_list(client: httpx.AsyncClient) -> None:
    """A crafted negative-offset cursor is -32602, never the tail of the list."""
    headers = await _mcp_init(client)
    for n in (-1, -9999):
        r = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {"cursor": _neg_cursor(n)}},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["error"]["code"] == -32602


# ---------------------------------------------------------------------------
# RT-003 — superseded; GET /mcp/sse admission is now covered end-to-end by
# test_rt001_mcp_sse_stream_cap.py (shared _get_streams() cap with GET /mcp,
# reject-not-evict, per-identity isolation, disconnect release).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-004 — origin guard on DELETE /mcp, GET /mcp/sse, POST /mcp/messages
# ---------------------------------------------------------------------------


async def test_origin_guard_delete_mcp(client: httpx.AsyncClient) -> None:
    """DELETE /mcp with a non-allowlisted Origin must return 403."""
    r = await client.delete(
        "/mcp",
        headers={
            "MCP-Protocol-Version": "2025-06-18",
            "Origin": "https://evil.example.com",
        },
    )
    assert r.status_code == 403, (
        f"DELETE /mcp with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )


async def test_origin_guard_get_mcp_sse(client: httpx.AsyncClient) -> None:
    """GET /mcp/sse with a non-allowlisted Origin must return 403."""
    r = await client.get(
        "/mcp/sse",
        headers={
            "Origin": "https://evil.example.com",
        },
    )
    assert r.status_code == 403, (
        f"GET /mcp/sse with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )


async def test_origin_guard_post_mcp_messages(client: httpx.AsyncClient) -> None:
    """POST /mcp/messages with a non-allowlisted Origin must return 403."""
    r = await client.post(
        "/mcp/messages",
        params={"session_id": "fake-session-id"},
        json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        headers={
            "MCP-Protocol-Version": "2025-06-18",
            "Origin": "https://evil.example.com",
        },
    )
    assert r.status_code == 403, (
        f"POST /mcp/messages with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )


async def test_origin_guard_allowlisted_origin_passes_delete(client: httpx.AsyncClient) -> None:
    """DELETE /mcp with no Origin header (normal server-to-server call) must
    NOT be rejected by the origin guard (204 or 404 are both valid)."""
    r = await client.delete(
        "/mcp",
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )
    assert r.status_code in (204, 404, 400), (
        f"DELETE /mcp without Origin must not 403; got {r.status_code}"
    )


# ---------------------------------------------------------------------------
# RT-005 — SI-2: no user-input reflection in error messages
# ---------------------------------------------------------------------------


async def test_unknown_tool_error_message_is_generic(client: httpx.AsyncClient) -> None:
    """tools/call with an unknown name must return 'tool not found', NOT the
    caller-supplied tool name."""
    headers = await _mcp_init(client)
    crafted_name = "INJECTED_TOOL_NAME_xyz_12345"

    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": crafted_name, "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" in body, f"Expected JSON-RPC error; got: {body}"
    msg = body["error"]["message"]
    assert crafted_name not in msg, (
        f"SI-2 violation: caller-supplied tool name reflected in error message: {msg!r}"
    )
    assert "tool not found" in msg.lower(), (
        f"Expected generic 'tool not found' message; got: {msg!r}"
    )


async def test_unknown_method_error_message_is_generic(client: httpx.AsyncClient) -> None:
    """An unknown JSON-RPC method must return 'method not found', NOT the
    caller-supplied method string."""
    headers = await _mcp_init(client)
    crafted_method = "injected/method/name/XYZ_99999"

    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": crafted_method,
            "params": {},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" in body, f"Expected JSON-RPC error; got: {body}"
    msg = body["error"]["message"]
    assert crafted_method not in msg, (
        f"SI-2 violation: caller-supplied method name reflected in error message: {msg!r}"
    )
    assert "method not found" in msg.lower(), (
        f"Expected generic 'method not found' message; got: {msg!r}"
    )
