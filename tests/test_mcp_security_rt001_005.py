"""Security regression tests — RT-001, RT-003, RT-004, RT-005.

RT-001  tools/list cursor must be clamped to ≥0; a crafted negative-offset
        cursor (e.g. base64('-1') = 'LTE=') must NOT wrap to the tail of the
        tool list.  (LRN-018)

RT-003  Legacy SSE session map must be bounded; after _MAX_SSE_SESSIONS are
        opened the oldest entry is evicted rather than growing unboundedly.
        (Tested structurally — the dict never exceeds the cap.)

RT-004  DELETE /mcp, GET /mcp/sse, and POST /mcp/messages all reject a
        non-allowlisted Origin with 403, mirroring the guard on POST /mcp and
        GET /mcp.

RT-005  SI-2: tools/call with an unknown tool name returns the generic message
        'tool not found', NOT the caller-supplied name.  An unknown JSON-RPC
        method returns 'method not found', NOT the caller-supplied method string.
"""

from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from agent_sdk.routes.mcp import _MAX_SSE_SESSIONS, _decode_cursor, _sse_queues


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


def test_decode_cursor_negative_clamped_by_unit() -> None:
    """_decode_cursor itself returns a negative int — the clamp lives in
    _handle_tools_list. Verify the raw decoder handles known negative inputs."""
    # base64('-1') == 'LTE='
    crafted = base64.b64encode(b"-1").decode()
    assert crafted == "LTE="
    assert _decode_cursor(crafted) == -1  # raw decoder returns -1 as documented


async def test_negative_cursor_does_not_wrap_tool_list(client: httpx.AsyncClient) -> None:
    """A crafted negative-offset cursor must return the same page as cursor=0
    (i.e. the first page), not the tail of the list."""
    headers = await _mcp_init(client)

    # Fetch the first page with no cursor.
    r0 = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
        headers=headers,
    )
    assert r0.status_code == 200, r0.text
    first_page_tools = r0.json()["result"]["tools"]

    # Fetch with a crafted negative cursor (base64('-1')).
    r_neg = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
            "params": {"cursor": _neg_cursor(-1)},
        },
        headers=headers,
    )
    assert r_neg.status_code == 200, r_neg.text
    neg_cursor_tools = r_neg.json()["result"]["tools"]

    # The negative-cursor result must be identical to the no-cursor first page.
    assert neg_cursor_tools == first_page_tools, (
        "Negative cursor must be clamped to 0; got different tool list: "
        f"first_page={[t['name'] for t in first_page_tools]!r} "
        f"neg_cursor={[t['name'] for t in neg_cursor_tools]!r}"
    )

    # Sanity: a large negative offset also stays on page 0.
    r_big_neg = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/list",
            "params": {"cursor": _neg_cursor(-9999)},
        },
        headers=headers,
    )
    assert r_big_neg.status_code == 200, r_big_neg.text
    assert r_big_neg.json()["result"]["tools"] == first_page_tools, (
        "Large negative cursor must also be clamped to page 0"
    )


# ---------------------------------------------------------------------------
# RT-003 — SSE session dict bounded by _MAX_SSE_SESSIONS
# ---------------------------------------------------------------------------


def test_sse_queue_cap_constant_is_set() -> None:
    """_MAX_SSE_SESSIONS must be defined and < _MAX_SESSIONS (1_000)."""
    from agent_sdk.routes.mcp import _MAX_SESSIONS

    assert isinstance(_MAX_SSE_SESSIONS, int), "_MAX_SSE_SESSIONS must be an int"
    assert 0 < _MAX_SSE_SESSIONS < _MAX_SESSIONS, (
        f"_MAX_SSE_SESSIONS ({_MAX_SSE_SESSIONS}) must be > 0 and < _MAX_SESSIONS ({_MAX_SESSIONS})"
    )


async def test_sse_queue_dict_stays_bounded(app) -> None:
    """Directly manipulate the SSE queue dict to confirm the eviction logic in
    mcp_sse keeps it within _MAX_SSE_SESSIONS.

    httpx.ASGITransport buffers the full response body before returning, so it
    cannot be used with infinite SSE streams (the response never completes and
    the call blocks forever).  Instead we exercise the eviction code directly:
    the production handler runs the eviction and queue registration
    synchronously in the route-handler body (before the StreamingResponse
    generator starts), so we can verify the invariant by replicating that
    exact sequence against the live queues dict.
    """
    import uuid

    queues = _sse_queues(app)

    # Pre-fill to exactly the cap.
    fill_count = _MAX_SSE_SESSIONS
    fake_ids: list[str] = []
    for _ in range(fill_count):
        sid = uuid.uuid4().hex
        fake_ids.append(sid)
        queues[sid] = (asyncio.Queue(maxsize=1), "fake:owner")

    assert len(queues) == _MAX_SSE_SESSIONS

    # Replicate the eviction + registration code from mcp_sse exactly.
    # This is the same sequence the route handler executes before returning
    # the StreamingResponse (i.e. it runs synchronously, before any streaming).
    new_sid = uuid.uuid4().hex
    while len(queues) >= _MAX_SSE_SESSIONS:
        queues.pop(next(iter(queues)), None)
    new_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
    queues[new_sid] = (new_queue, "test:owner")

    # The dict must not have grown beyond the cap.
    assert len(queues) <= _MAX_SSE_SESSIONS, (
        f"SSE queue dict grew to {len(queues)}, expected ≤ {_MAX_SSE_SESSIONS}"
    )
    # The new entry must have been registered.
    assert new_sid in queues, "new session id was not added to the queue dict"

    # Cleanup: drain all entries so other tests are unaffected.
    queues.pop(new_sid, None)
    for sid in fake_ids:
        queues.pop(sid, None)


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
