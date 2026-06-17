"""MCP initialize version-gated serverInfo.title — GH #43.

AC (conservative gate — see REVIEWS.md Round 4 and _TITLE_MIN_VERSION comment):
  1. serverInfo.title ABSENT when negotiated version is 2025-06-18 (GH-43 observed
     Claude.ai rejecting the handshake; gate conservatively at 2025-11-25 until re-tested live).
  2. serverInfo.title PRESENT when negotiated version is 2025-11-25.
  3. 2025-11-25 is in SUPPORTED_PROTOCOL_VERSIONS (clients requesting it get it echoed).
  4. A client requesting 2025-11-25 gets 2025-11-25 back, not the old fallback.
"""

from __future__ import annotations

import httpx
import pytest

from agent_sdk.routes.mcp import SUPPORTED_PROTOCOL_VERSIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _initialize(client: httpx.AsyncClient, protocol_version: str) -> dict:
    """Run an MCP initialize and return the parsed JSON-RPC result body."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": protocol_version, "capabilities": {}},
        },
        headers={"MCP-Protocol-Version": protocol_version},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, f"Expected result in body; got: {body}"
    return body["result"]


# ---------------------------------------------------------------------------
# AC-3: 2025-11-25 must be in SUPPORTED_PROTOCOL_VERSIONS
# ---------------------------------------------------------------------------


def test_2025_11_25_in_supported_versions() -> None:
    """2025-11-25 must appear in SUPPORTED_PROTOCOL_VERSIONS so clients that
    request it can negotiate to it rather than being downgraded."""
    assert "2025-11-25" in SUPPORTED_PROTOCOL_VERSIONS, (
        f"2025-11-25 not in SUPPORTED_PROTOCOL_VERSIONS: {SUPPORTED_PROTOCOL_VERSIONS}"
    )


# ---------------------------------------------------------------------------
# AC-1: title absent for 2025-06-18
# ---------------------------------------------------------------------------


async def test_title_absent_for_2025_06_18(client: httpx.AsyncClient) -> None:
    """serverInfo.title must NOT be present when the negotiated version is
    2025-06-18 — title was introduced in 2025-11-25 and its presence under an
    older negotiated version causes Claude.ai to reject the handshake."""
    result = await _initialize(client, "2025-06-18")
    server_info = result.get("serverInfo", {})
    assert "title" not in server_info, (
        f"serverInfo.title must be absent for 2025-06-18; got serverInfo={server_info}"
    )
    # name and version must still be present
    assert "name" in server_info, "serverInfo.name must always be present"
    assert "version" in server_info, "serverInfo.version must always be present"
    # negotiated version must be echoed correctly
    assert result.get("protocolVersion") == "2025-06-18"


# ---------------------------------------------------------------------------
# AC-1 (older baseline): title absent for 2025-03-26
# ---------------------------------------------------------------------------


async def test_title_absent_for_2025_03_26(client: httpx.AsyncClient) -> None:
    """serverInfo.title must also be absent for the older 2025-03-26 baseline."""
    result = await _initialize(client, "2025-03-26")
    server_info = result.get("serverInfo", {})
    assert "title" not in server_info, (
        f"serverInfo.title must be absent for 2025-03-26; got serverInfo={server_info}"
    )
    assert result.get("protocolVersion") == "2025-03-26"


# ---------------------------------------------------------------------------
# AC-2: title present for 2025-11-25
# ---------------------------------------------------------------------------


async def test_title_present_for_2025_11_25(client: httpx.AsyncClient) -> None:
    """serverInfo.title MUST be present when the negotiated version is 2025-11-25."""
    result = await _initialize(client, "2025-11-25")
    server_info = result.get("serverInfo", {})
    assert "title" in server_info, (
        f"serverInfo.title must be present for 2025-11-25; got serverInfo={server_info}"
    )
    assert isinstance(server_info["title"], str) and server_info["title"], (
        "serverInfo.title must be a non-empty string"
    )
    assert result.get("protocolVersion") == "2025-11-25"


# ---------------------------------------------------------------------------
# AC-4: 2025-11-25 is negotiated correctly (not downgraded)
# ---------------------------------------------------------------------------


async def test_2025_11_25_negotiated_version_echoed(client: httpx.AsyncClient) -> None:
    """A client requesting 2025-11-25 must receive protocolVersion=2025-11-25
    in the response — it must not be downgraded to an older supported version."""
    result = await _initialize(client, "2025-11-25")
    assert result.get("protocolVersion") == "2025-11-25", (
        f"Expected 2025-11-25 echoed back; got {result.get('protocolVersion')}"
    )
