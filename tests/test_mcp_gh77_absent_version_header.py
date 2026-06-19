"""GH-77: absent MCP-Protocol-Version header on post-init requests must return 400.

MCP spec §10: the MCP-Protocol-Version header is REQUIRED on every non-initialize
request after the session is established. The server must return 400 when the
header is absent on a non-initialize POST, not silently fall back.

Tests:
- POST to a non-initialize endpoint with no MCP-Protocol-Version header → 400
- POST to initialize with no MCP-Protocol-Version header → 200 (regression guard)
- POST to a non-initialize endpoint with a present but unrecognized version → 400
  (existing behavior, must remain unchanged)
"""

from __future__ import annotations

import httpx
import pytest

from agent_sdk.routes.mcp import SUPPORTED_PROTOCOL_VERSIONS, _HEADER_ABSENT, _negotiated_version


# ---------------------------------------------------------------------------
# Unit: _negotiated_version sentinel distinctions
# ---------------------------------------------------------------------------


class _FakeRequest:
    """Minimal stand-in for a Starlette Request, sufficient for header inspection."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_negotiated_version_absent_returns_sentinel() -> None:
    """`_negotiated_version` must return `_HEADER_ABSENT` (not a version string)
    when the MCP-Protocol-Version header is missing."""
    req = _FakeRequest({})
    result = _negotiated_version(req)  # type: ignore[arg-type]
    assert result is _HEADER_ABSENT, (
        f"Expected _HEADER_ABSENT sentinel for absent header; got {result!r}"
    )


def test_negotiated_version_recognized_returns_version() -> None:
    """A recognized version string must be returned as-is."""
    req = _FakeRequest({"MCP-Protocol-Version": "2025-06-18"})
    result = _negotiated_version(req)  # type: ignore[arg-type]
    assert result == "2025-06-18", f"Expected '2025-06-18'; got {result!r}"


def test_negotiated_version_unrecognized_returns_none() -> None:
    """An unrecognized version string must return None (caller answers 400)."""
    req = _FakeRequest({"MCP-Protocol-Version": "9999-99-99"})
    result = _negotiated_version(req)  # type: ignore[arg-type]
    assert result is None, f"Expected None for unrecognized version; got {result!r}"


# ---------------------------------------------------------------------------
# Integration: POST /mcp — absent header on non-initialize → 400
# ---------------------------------------------------------------------------


async def test_absent_version_header_on_ping_returns_400(
    client: httpx.AsyncClient,
) -> None:
    """POST /mcp with method=ping and NO MCP-Protocol-Version header must
    return 400 per MCP spec §10 (header required post-initialization)."""
    # Establish a session first.
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
    assert session_id, "Expected Mcp-Session-Id from initialize"

    # Send ping with no MCP-Protocol-Version header.
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        headers={"Mcp-Session-Id": session_id},
        # deliberately no MCP-Protocol-Version header
    )
    assert r.status_code == 400, (
        f"Absent MCP-Protocol-Version on post-init ping must return 400; "
        f"got {r.status_code}: {r.text}"
    )


async def test_absent_version_header_on_tools_list_returns_400(
    client: httpx.AsyncClient,
) -> None:
    """POST /mcp with method=tools/list and NO MCP-Protocol-Version header must
    return 400 (same rule applies to all non-initialize methods)."""
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
    assert session_id

    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers={"Mcp-Session-Id": session_id},
    )
    assert r.status_code == 400, (
        f"Absent MCP-Protocol-Version on tools/list must return 400; "
        f"got {r.status_code}: {r.text}"
    )


# ---------------------------------------------------------------------------
# Regression: initialize with absent header still succeeds
# ---------------------------------------------------------------------------


async def test_initialize_with_no_version_header_returns_200(
    client: httpx.AsyncClient,
) -> None:
    """POST /mcp with method=initialize and NO MCP-Protocol-Version header must
    still return 200 — the header is not required during initialization."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        # deliberately no MCP-Protocol-Version header
    )
    assert r.status_code == 200, (
        f"initialize with absent version header must return 200; "
        f"got {r.status_code}: {r.text}"
    )


async def test_initialize_with_no_version_header_returns_session_id(
    client: httpx.AsyncClient,
) -> None:
    """initialize without the header must still allocate a session."""
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
    assert r.headers.get("mcp-session-id"), "initialize must return an Mcp-Session-Id"
