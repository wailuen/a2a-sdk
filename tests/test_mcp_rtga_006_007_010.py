"""Regression tests for RTGA-006, RTGA-007, RTGA-010.

RTGA-006  initialize must bypass MCP-Protocol-Version header validation.
          A future/unsupported version in the header must NOT cause 400;
          the server returns 200 with its highest negotiated version in
          the response body.

RTGA-007  Trailing-slash configured CORS origins must not be 403'd by the
          defense-in-depth origin guards on POST /mcp, GET /mcp, DELETE /mcp,
          GET /mcp/sse, POST /mcp/messages.

RTGA-010  Re-initializing evicts the previous session for the same owner
          so orphan slots do not accumulate against the LRU cap.
"""

from __future__ import annotations

import gc

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.routes.mcp import SUPPORTED_PROTOCOL_VERSIONS, _sessions
from agent_sdk.testing import FakeModelClient


# ---------------------------------------------------------------------------
# RTGA-006 — initialize bypasses MCP-Protocol-Version header validation
# ---------------------------------------------------------------------------


async def test_initialize_with_future_version_header_returns_200(
    client: httpx.AsyncClient,
) -> None:
    """POST /mcp with method=initialize + MCP-Protocol-Version: 9999-99-99
    must return HTTP 200.  The unrecognized header must NOT trigger 400."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        headers={"MCP-Protocol-Version": "9999-99-99"},
    )
    assert r.status_code == 200, (
        f"initialize with future version header must return 200; got {r.status_code}: {r.text}"
    )


async def test_initialize_with_future_version_header_returns_negotiated_version(
    client: httpx.AsyncClient,
) -> None:
    """The response body must contain the server's highest supported version
    in result.protocolVersion (the client decides whether to continue)."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "9999-99-99", "capabilities": {}},
        },
        headers={"MCP-Protocol-Version": "9999-99-99"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, f"Expected result; got: {body}"
    negotiated = body["result"].get("protocolVersion")
    assert negotiated == SUPPORTED_PROTOCOL_VERSIONS[0], (
        f"Server must return its highest supported version on unrecognized client version; "
        f"got {negotiated!r}, expected {SUPPORTED_PROTOCOL_VERSIONS[0]!r}"
    )


async def test_non_initialize_with_future_version_header_returns_400(
    client: httpx.AsyncClient,
) -> None:
    """After a valid session exists, a post-init request with an unsupported
    MCP-Protocol-Version must still return 400 (unchanged behavior)."""
    # First, establish a session with a valid version.
    r_init = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r_init.status_code == 200, r_init.text
    session_id = r_init.headers.get("mcp-session-id")
    assert session_id, "Expected Mcp-Session-Id in initialize response"

    # Now send ping with an unsupported version.
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        headers={
            "Mcp-Session-Id": session_id,
            "MCP-Protocol-Version": "9999-99-99",
        },
    )
    assert r.status_code == 400, (
        f"Post-init request with unsupported version header must return 400; "
        f"got {r.status_code}: {r.text}"
    )


# ---------------------------------------------------------------------------
# RTGA-007 — trailing-slash CORS origin normalization
# ---------------------------------------------------------------------------


@pytest.fixture
def trailing_slash_app(tmp_path):
    """App configured with a trailing-slash CORS origin."""
    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        CORS_ORIGINS=["https://app.example.com/"],
    )
    built = make_agent(settings, model_client=FakeModelClient()).build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def trailing_slash_client(trailing_slash_app) -> httpx.AsyncClient:
    async with trailing_slash_app.router.lifespan_context(trailing_slash_app):
        _, token = trailing_slash_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=trailing_slash_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_trailing_slash_origin_not_403_on_post_mcp(
    trailing_slash_client: httpx.AsyncClient,
) -> None:
    """POST /mcp with Origin: https://app.example.com (no trailing slash) must
    NOT return 403 when the configured origin has a trailing slash."""
    r = await trailing_slash_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        headers={"Origin": "https://app.example.com"},
    )
    assert r.status_code != 403, (
        f"Trailing-slash configured origin must not be 403'd on POST /mcp; "
        f"got {r.status_code}: {r.text}"
    )


async def test_trailing_slash_origin_normalized_in_app_state(
    trailing_slash_app,
) -> None:
    """app.state.cors_origins must contain the stripped form so the route
    guard membership test succeeds."""
    cors_origins = trailing_slash_app.state.cors_origins
    assert "https://app.example.com" in cors_origins, (
        f"Normalized (no trailing slash) origin must be in cors_origins; "
        f"got: {cors_origins!r}"
    )
    assert "https://app.example.com/" not in cors_origins, (
        "Trailing-slash form must NOT be in cors_origins after normalization; "
        f"got: {cors_origins!r}"
    )


# ---------------------------------------------------------------------------
# RTGA-010 — re-initialize evicts previous owner session
# ---------------------------------------------------------------------------


async def test_reinitialize_evicts_previous_session(
    client: httpx.AsyncClient, app
) -> None:
    """A second initialize from the same owner must evict the first session
    so orphan slots don't accumulate against the LRU cap."""
    sessions = _sessions(app)

    # First initialize — allocates one session.
    r1 = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r1.status_code == 200, r1.text
    sid1 = r1.headers.get("mcp-session-id")
    assert sid1, "Expected Mcp-Session-Id from first initialize"
    assert sid1 in sessions, "First session must be registered"

    # Capture the owner key from the recorded session entry.
    owner = sessions[sid1][1]

    def _owner_sessions() -> list[str]:
        return [s for s, rec in sessions.items() if rec[1] == owner]

    assert len(_owner_sessions()) == 1, (
        f"Expected 1 owner session after first init; got {_owner_sessions()!r}"
    )

    # Second initialize — must evict the first and allocate a new one.
    r2 = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r2.status_code == 200, r2.text
    sid2 = r2.headers.get("mcp-session-id")
    assert sid2, "Expected Mcp-Session-Id from second initialize"
    assert sid2 != sid1, "Second initialize must allocate a new session id"

    # The old session must have been evicted.
    assert sid1 not in sessions, (
        f"First session {sid1!r} must be evicted after re-initialize"
    )
    # Exactly one owner session must remain.
    remaining = _owner_sessions()
    assert len(remaining) == 1, (
        f"Expected exactly 1 owner session after re-initialize; "
        f"got {len(remaining)}: {remaining!r}"
    )
    assert sid2 in sessions, "New session must be registered"
