"""Legacy transport handshake test — RT-004 coverage gap.

RT-004 finding: no test exercises a full initialize JSON-RPC message on the
legacy POST /mcp/messages endpoint.  The existing tests cover only origin
guards and non-initialize dispatch.  This gap allowed the GH-77 fix (absent
MCP-Protocol-Version → 400) to silently break legacy initialize because
mcp_messages validated the header unconditionally, before checking whether the
method was initialize.

Tests:
- POST initialize to /mcp/messages with no MCP-Protocol-Version header → 202
  (absent-header carve-out must mirror mcp_post for initialize).
- The queued result carries a valid initialize response (result.protocolVersion
  and result.serverInfo present).
- POST initialize to /mcp/messages with a present, supported version header →
  202 (normal path still works after the carve-out is applied).
- POST a non-initialize method to /mcp/messages with no version header → 400
  (carve-out must not weaken the non-initialize header requirement).
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest

from agent_sdk.routes.mcp import SUPPORTED_PROTOCOL_VERSIONS, _sse_queues


# ---------------------------------------------------------------------------
# Helper: inject a fake SSE session (simulates GET /mcp/sse completing the
# handshake without consuming the infinite SSE stream, which httpx
# ASGITransport cannot do — it buffers the full response body).
# ---------------------------------------------------------------------------


def _owner_for_client(app, bearer_token: str) -> str:
    """Resolve the API-key identity from a bearer token and return its owner key.

    The mcp_messages route compares rec[1] == _identity_key(identity); we
    must register the SSE session under the same owner key the route will
    compute from the incoming request's Authorization header.
    """
    identity = app.state.auth.api_keys.verify(bearer_token)
    assert identity is not None, "bearer token must be valid"
    return f"{identity.kind}:{identity.subject}"


def _register_sse_session(app, owner: str) -> tuple[str, asyncio.Queue]:
    """Register a fake SSE session and return (session_id, queue)."""
    queues = _sse_queues(app)
    session_id = uuid.uuid4().hex
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
    queues[session_id] = (queue, owner)
    return session_id, queue


def _cleanup_sse_session(app, session_id: str) -> None:
    _sse_queues(app).pop(session_id, None)


# ---------------------------------------------------------------------------
# RED test (before fix): initialize on /mcp/messages with absent version header
# ---------------------------------------------------------------------------


async def test_legacy_initialize_absent_version_header_returns_202(
    client: httpx.AsyncClient, app
) -> None:
    """POST initialize to /mcp/messages with no MCP-Protocol-Version header must
    return 202 (absent-header carve-out mirrors mcp_post's behavior for initialize).

    Before the fix this returns 400 — that is the regression RT-004 guards against.
    """
    bearer = client.headers["authorization"].removeprefix("Bearer ")
    owner = _owner_for_client(app, bearer)
    session_id, queue = _register_sse_session(app, owner)
    try:
        r = await client.post(
            "/mcp/messages",
            params={"session_id": session_id},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
            # deliberately no MCP-Protocol-Version header
        )
        assert r.status_code == 202, (
            f"legacy initialize with absent version header must return 202; "
            f"got {r.status_code}: {r.text}"
        )
    finally:
        _cleanup_sse_session(app, session_id)


async def test_legacy_initialize_queues_valid_result(
    client: httpx.AsyncClient, app
) -> None:
    """After a 202 response the SSE queue must contain a JSON-RPC result with
    result.protocolVersion and result.serverInfo (end-to-end legacy flow)."""
    bearer = client.headers["authorization"].removeprefix("Bearer ")
    owner = _owner_for_client(app, bearer)
    session_id, queue = _register_sse_session(app, owner)
    try:
        r = await client.post(
            "/mcp/messages",
            params={"session_id": session_id},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
            # deliberately no MCP-Protocol-Version header
        )
        assert r.status_code == 202, (
            f"legacy initialize must return 202; got {r.status_code}: {r.text}"
        )
        # The result must have been enqueued synchronously before the 202 ack.
        assert not queue.empty(), "initialize result must be queued after 202 ack"
        raw = queue.get_nowait()
        response = json.loads(raw)
        assert "result" in response, f"Expected JSON-RPC result; got: {response}"
        result = response["result"]
        assert "protocolVersion" in result, (
            f"initialize result must contain protocolVersion; got: {result}"
        )
        assert result["protocolVersion"] in SUPPORTED_PROTOCOL_VERSIONS, (
            f"protocolVersion must be a supported version; got {result['protocolVersion']!r}"
        )
        assert "serverInfo" in result, (
            f"initialize result must contain serverInfo; got: {result}"
        )
    finally:
        _cleanup_sse_session(app, session_id)


async def test_legacy_initialize_with_version_header_returns_202(
    client: httpx.AsyncClient, app
) -> None:
    """POST initialize to /mcp/messages with a supported MCP-Protocol-Version
    header must also return 202 (normal path must remain unaffected by carve-out)."""
    bearer = client.headers["authorization"].removeprefix("Bearer ")
    owner = _owner_for_client(app, bearer)
    session_id, queue = _register_sse_session(app, owner)
    try:
        r = await client.post(
            "/mcp/messages",
            params={"session_id": session_id},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
            headers={"MCP-Protocol-Version": "2025-06-18"},
        )
        assert r.status_code == 202, (
            f"legacy initialize with version header must return 202; "
            f"got {r.status_code}: {r.text}"
        )
    finally:
        _cleanup_sse_session(app, session_id)


async def test_legacy_non_initialize_absent_version_header_returns_202(
    client: httpx.AsyncClient, app
) -> None:
    """POST a non-initialize method to /mcp/messages with no MCP-Protocol-Version
    header must return 202 on the legacy SSE transport — MCP spec §10 says
    absent header SHOULD assume 2025-03-26 (a SHOULD, not a MUST), so the
    legacy path proceeds with the assumed default rather than rejecting."""
    bearer = client.headers["authorization"].removeprefix("Bearer ")
    owner = _owner_for_client(app, bearer)
    session_id, queue = _register_sse_session(app, owner)
    try:
        r = await client.post(
            "/mcp/messages",
            params={"session_id": session_id},
            json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        )
        assert r.status_code == 202, (
            f"legacy non-initialize with absent version header must return 202; "
            f"got {r.status_code}: {r.text}"
        )
    finally:
        _cleanup_sse_session(app, session_id)


async def test_legacy_non_initialize_unrecognized_version_returns_400(
    client: httpx.AsyncClient, app
) -> None:
    """POST a non-initialize method to /mcp/messages with a present but
    unrecognized MCP-Protocol-Version header must return 400 — the None
    branch (present-but-unrecognized) is still rejected."""
    bearer = client.headers["authorization"].removeprefix("Bearer ")
    owner = _owner_for_client(app, bearer)
    session_id, queue = _register_sse_session(app, owner)
    try:
        r = await client.post(
            "/mcp/messages",
            params={"session_id": session_id},
            json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
            headers={"MCP-Protocol-Version": "9999-99-99"},
        )
        assert r.status_code == 400, (
            f"legacy non-initialize with unrecognized version must return 400; "
            f"got {r.status_code}: {r.text}"
        )
    finally:
        _cleanup_sse_session(app, session_id)
