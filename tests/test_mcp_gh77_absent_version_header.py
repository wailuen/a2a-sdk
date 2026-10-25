"""GH-77 / GH-200: MCP-Protocol-Version handling on Streamable HTTP POST /mcp.

GH-200 reverses GH-77's absent-header 400: the spec only requires 400 for an
invalid/unsupported value. An absent header on a non-initialize request is
dispatched using the version negotiated at initialize for that session, else
2025-03-26. Present-but-unrecognized still 400s.
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
# Integration: POST /mcp — absent header on non-initialize (GH-200 reverses the
# GH-77 400: dispatch, echoing the session's negotiated version)
# ---------------------------------------------------------------------------


async def _init(client: httpx.AsyncClient, version: str) -> str:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {}},
        },
    )
    assert r.status_code == 200, r.text
    session_id = r.headers.get("mcp-session-id")
    assert session_id, "Expected Mcp-Session-Id from initialize"
    return session_id


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18"])
@pytest.mark.parametrize("method", ["ping", "tools/list"])
async def test_absent_version_header_echoes_session_version(
    client: httpx.AsyncClient, version: str, method: str
) -> None:
    session_id = await _init(client, version)
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": method, "params": {}},
        headers={"Mcp-Session-Id": session_id},
    )
    assert r.status_code == 200, r.text
    assert "result" in r.json()
    assert r.headers.get("mcp-protocol-version") == version


async def test_absent_version_header_no_session_falls_back_to_2025_03_26(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("mcp-protocol-version") == "2025-03-26"


async def test_absent_version_header_unknown_session_still_404(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        headers={"Mcp-Session-Id": "deadbeef"},
    )
    assert r.status_code == 404


async def test_absent_version_header_missing_session_id_with_live_session_dispatches(
    client: httpx.AsyncClient,
) -> None:
    """GH-201: a missing Mcp-Session-Id is not an error, even with live sessions."""
    await _init(client, "2025-06-18")
    r = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
    )
    assert r.status_code == 200
    assert "result" in r.json()
    assert r.headers.get("mcp-protocol-version") == "2025-03-26"


async def test_present_unrecognized_version_header_returns_400(
    client: httpx.AsyncClient,
) -> None:
    session_id = await _init(client, "2025-06-18")
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        headers={"Mcp-Session-Id": session_id, "MCP-Protocol-Version": "1999-01-01"},
    )
    assert r.status_code == 400
    assert "unsupported MCP-Protocol-Version" in r.text
    assert "required" not in r.text
    assert "1999" not in r.headers.get("mcp-protocol-version", "")


async def test_present_supported_version_header_echoed(
    client: httpx.AsyncClient,
) -> None:
    """A present header that matches the session's negotiated version is
    dispatched and echoed. GH-273 made a valid-but-different header on a known
    session a 400 (tests/test_gh273_mcp_session_version.py), so this test
    negotiates 2025-03-26 and sends the matching header."""
    session_id = await _init(client, "2025-03-26")
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        headers={"Mcp-Session-Id": session_id, "MCP-Protocol-Version": "2025-03-26"},
    )
    assert r.status_code == 200
    assert r.headers.get("mcp-protocol-version") == "2025-03-26"


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
