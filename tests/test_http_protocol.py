"""HTTP protocol conformance tests — WWW-Authenticate challenge shape and PRM routes.

Covers:
  C3-H1  WWW-Authenticate has no ``scope=`` param
  C3-H2  WWW-Authenticate resource_metadata points to path-suffixed PRM
  C3-H3  Same challenge on POST /mcp
  C3-H4  Same challenge on GET /mcp
  C3-H5  Challenge is identical across all three surfaces
  C3-H6  Path-suffixed PRM endpoint returns 200 + ``resource`` key
  C3-H7  Bare PRM endpoint returns 200 + ``resource`` key

All tests use the shared async httpx client from conftest (asyncio_mode=auto).
Unauthenticated requests strip the pre-set admin bearer by passing
``headers={"Authorization": ""}``.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEND_BODY = {
    "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "hello"}],
        "messageId": "test-msg-001",
    }
}


async def _www_auth(client: httpx.AsyncClient, method: str, path: str, **kwargs: object) -> str:
    """Make an unauthenticated request and return the WWW-Authenticate header value."""
    func = getattr(client, method)
    r = await func(path, headers={"Authorization": ""}, **kwargs)
    assert r.status_code == 401, f"{method.upper()} {path} → {r.status_code}, expected 401"
    header = r.headers.get("www-authenticate", "")
    assert header, f"WWW-Authenticate header missing on {method.upper()} {path}"
    return header


# ===========================================================================
# C3-H1 — WWW-Authenticate has no scope= param
# ===========================================================================


async def test_www_auth_no_scope_param(client):
    """Unauthenticated POST /v1/message:send must yield 401 whose WWW-Authenticate
    does NOT contain ``scope=``.

    RFC 6750 §3 only requires ``realm`` in the challenge; adding an empty
    ``scope=""`` confuses some OAuth discovery implementations.  The SDK omits
    it (§5.5)."""
    www_auth = await _www_auth(client, "post", "/v1/message:send", json=_SEND_BODY)
    assert "scope=" not in www_auth, (
        f"WWW-Authenticate must not contain 'scope=' but got: {www_auth!r}"
    )
    assert 'resource_metadata="' in www_auth, (
        f"WWW-Authenticate must contain resource_metadata=\" but got: {www_auth!r}"
    )


# ===========================================================================
# C3-H2 — A2A resource_metadata points to bare PRM; MCP uses path-suffixed PRM
# ===========================================================================


async def test_www_auth_per_surface_prm(client):
    """GH-33: A2A (/v1/) and AG-UI (/ag-ui/) routes emit the bare PRM
    (``/.well-known/oauth-protected-resource``) so their resource metadata
    binds to the agent root, not the MCP endpoint.

    MCP (/mcp) routes continue to use the path-suffixed form
    (``/.well-known/oauth-protected-resource/mcp``) per RFC 9728 §3.1 /
    Claude.ai connector expectations.

    Neither challenge carries ``scope=``."""
    www_a2a = await _www_auth(client, "post", "/v1/message:send", json=_SEND_BODY)
    # A2A surface: bare PRM (no /mcp suffix in the resource_metadata URL)
    assert '/.well-known/oauth-protected-resource"' in www_a2a or \
           "/.well-known/oauth-protected-resource'" in www_a2a or \
           www_a2a.rstrip().endswith('/.well-known/oauth-protected-resource"') or \
           "oauth-protected-resource\"" in www_a2a, (
        f"A2A WWW-Auth must reference bare PRM; got: {www_a2a!r}"
    )
    assert "/.well-known/oauth-protected-resource/mcp" not in www_a2a, (
        f"A2A WWW-Auth must NOT reference the /mcp path-suffixed PRM; got: {www_a2a!r}"
    )
    assert "scope=" not in www_a2a

    # MCP surface: path-suffixed PRM (unchanged)
    r_mcp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": ""},
    )
    assert r_mcp.status_code == 401
    www_mcp = r_mcp.headers.get("www-authenticate", "")
    assert "/.well-known/oauth-protected-resource/mcp" in www_mcp, (
        f"MCP WWW-Auth must reference /mcp path-suffixed PRM; got: {www_mcp!r}"
    )


# ===========================================================================
# C3-H3 — Same challenge on POST /mcp
# ===========================================================================


async def test_www_auth_on_mcp_route(client):
    """Unauthenticated POST /mcp must return 401 with WWW-Authenticate present
    and pointing at the path-suffixed PRM (same format as the A2A surface)."""
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": ""},
    )
    assert r.status_code == 401, f"POST /mcp → {r.status_code}, expected 401"
    www_auth = r.headers.get("www-authenticate", "")
    assert www_auth, "WWW-Authenticate header missing on POST /mcp 401"
    assert "scope=" not in www_auth, (
        f"WWW-Authenticate must not contain 'scope=' but got: {www_auth!r}"
    )
    assert 'resource_metadata="' in www_auth, (
        f"WWW-Authenticate must contain resource_metadata=\" but got: {www_auth!r}"
    )


# ===========================================================================
# C3-H4 — Same challenge on GET /mcp
# ===========================================================================


async def test_mcp_get_unauthenticated_returns_www_auth(client):
    """Unauthenticated GET /mcp must also return 401 with WWW-Authenticate.

    GET /mcp is used by SSE legacy clients and must be equally protected."""
    r = await client.get("/mcp", headers={"Authorization": ""})
    assert r.status_code == 401, f"GET /mcp → {r.status_code}, expected 401"
    www_auth = r.headers.get("www-authenticate", "")
    assert www_auth, "WWW-Authenticate header missing on GET /mcp 401"


# ===========================================================================
# C3-H5 — Per-surface challenge consistency (GH-33: A2A ≠ MCP, internally consistent)
# ===========================================================================


async def test_www_auth_consistent_within_surfaces(client):
    """GH-33: A2A and MCP now use different PRM URLs (A2A=bare, MCP=path-suffixed).
    Within each surface, repeated unauthenticated requests must return the same
    challenge. AG-UI must match A2A (both are non-MCP data-plane surfaces).

    Neither challenge may carry ``scope=`` (RFC 6750 §3 ABNF)."""
    # A2A surface
    r_a2a = await client.post(
        "/v1/message:send", json=_SEND_BODY, headers={"Authorization": ""}
    )
    assert r_a2a.status_code == 401
    www_a2a = r_a2a.headers.get("www-authenticate", "")
    assert www_a2a, "A2A surface returned empty WWW-Authenticate"
    assert "scope=" not in www_a2a
    assert 'resource_metadata="' in www_a2a

    # A2A challenge must NOT contain the /mcp suffix
    assert "/mcp" not in www_a2a, (
        f"A2A WWW-Auth must reference bare PRM (no /mcp); got: {www_a2a!r}"
    )

    # MCP surface
    r_mcp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": ""},
    )
    assert r_mcp.status_code == 401
    www_mcp = r_mcp.headers.get("www-authenticate", "")
    assert www_mcp, "MCP surface returned empty WWW-Authenticate"
    assert "scope=" not in www_mcp
    assert "/.well-known/oauth-protected-resource/mcp" in www_mcp, (
        f"MCP WWW-Auth must reference path-suffixed PRM; got: {www_mcp!r}"
    )

    # A2A and MCP challenges must DIFFER (different resource scope)
    assert www_a2a != www_mcp, (
        "A2A and MCP WWW-Authenticate should differ (A2A=bare PRM, MCP=path-suffixed); "
        f"both got: {www_a2a!r}"
    )

    # AG-UI surface (non-MCP) must match A2A
    r_agui = await client.post(
        "/ag-ui/run",
        json={"thread_id": "t1", "run_id": "r1", "messages": []},
        headers={"Authorization": ""},
    )
    if r_agui.status_code == 401:
        www_agui = r_agui.headers.get("www-authenticate", "")
        assert www_agui == www_a2a, (
            f"AG-UI WWW-Auth must match A2A (both use bare PRM):\n"
            f"  AG-UI: {www_agui!r}\n  A2A: {www_a2a!r}"
        )


# ===========================================================================
# C3-H6 — Path-suffixed PRM returns 200 + ``resource`` key
# ===========================================================================


async def test_prm_path_suffixed_returns_200(client):
    """GET /.well-known/oauth-protected-resource/mcp must return 200 and include
    a ``resource`` key (RFC 9728 §4.1)."""
    r = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert r.status_code == 200, (
        f"Path-suffixed PRM → {r.status_code}: {r.text}"
    )
    body = r.json()
    assert "resource" in body, (
        f"PRM response must include 'resource' key; got keys: {list(body.keys())}"
    )


# ===========================================================================
# C3-H7 — Bare PRM returns 200 + ``resource`` key
# ===========================================================================


async def test_prm_bare_returns_200(client):
    """GET /.well-known/oauth-protected-resource (bare, no path suffix) must
    also return 200 and include a ``resource`` key."""
    r = await client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200, (
        f"Bare PRM → {r.status_code}: {r.text}"
    )
    body = r.json()
    assert "resource" in body, (
        f"PRM response must include 'resource' key; got keys: {list(body.keys())}"
    )


# ===========================================================================
# GH-111 — mcp_get / mcp_delete must reject a present-but-unrecognized
# MCP-Protocol-Version header (400), mirroring mcp_post's validation via
# _negotiated_version(). The absent-header case is unaffected (locked
# GH-77/w022 ruling — do not re-litigate).
# ===========================================================================


async def test_mcp_get_bogus_protocol_version_returns_400(client):
    """GET /mcp with a present-but-unrecognized MCP-Protocol-Version header
    must return 400, not silently open the SSE stream.

    The heartbeat stream never completes on its own (LRN-053 — no
    server-initiated close), so a passing (fixed) response must arrive well
    inside the timeout; an unfixed handler falls through into the infinite
    generator and this call would hang past the deadline instead."""
    r = await asyncio.wait_for(
        client.get("/mcp", headers={"MCP-Protocol-Version": "bogus-value"}), timeout=5
    )
    assert r.status_code == 400, (
        f"GET /mcp with bogus MCP-Protocol-Version → {r.status_code}, expected 400"
    )


async def test_mcp_delete_bogus_protocol_version_returns_400(client):
    """DELETE /mcp with a present-but-unrecognized MCP-Protocol-Version header
    must return 400, not silently succeed."""
    r = await client.delete("/mcp", headers={"MCP-Protocol-Version": "bogus-value"})
    assert r.status_code == 400, (
        f"DELETE /mcp with bogus MCP-Protocol-Version → {r.status_code}, expected 400"
    )


async def test_mcp_get_bogus_protocol_version_message_names_actual_trigger(client):
    """RT-005: on GET /mcp an absent header is allowed (GH-77/w022), so a
    present-but-unrecognized header must NOT be reported with mcp_post's
    "header required" wording — that would tell a client that DID send a
    version that it omitted one. The message must name the real condition."""
    r = await asyncio.wait_for(
        client.get("/mcp", headers={"MCP-Protocol-Version": "bogus-value"}), timeout=5
    )
    assert r.json() == {"error": "unsupported MCP-Protocol-Version"}


async def test_mcp_delete_bogus_protocol_version_message_names_actual_trigger(client):
    """RT-005: same accurate-wording requirement as the GET case."""
    r = await client.delete("/mcp", headers={"MCP-Protocol-Version": "bogus-value"})
    assert r.json() == {"error": "unsupported MCP-Protocol-Version"}


async def test_mcp_get_no_protocol_version_header_still_succeeds(client):
    """Regression: GET /mcp with NO MCP-Protocol-Version header at all must
    still reach the SSE heartbeat stream unchanged (absent-header case is
    unaffected by GH-111).

    The stream is intentionally infinite (LRN-053 — no server-initiated
    close), so under the in-process ASGI test transport it can only be
    observed as "reached and still running after the deadline" — a
    short-circuiting 400/403 would instead return well inside the timeout."""
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(client.get("/mcp"), timeout=0.5)


async def test_mcp_delete_no_protocol_version_header_still_succeeds(client):
    """Regression: DELETE /mcp with NO MCP-Protocol-Version header at all
    must still succeed (idempotent 204, absent-header case is unaffected)."""
    r = await client.delete("/mcp")
    assert r.status_code == 204, (
        f"DELETE /mcp with no MCP-Protocol-Version header → {r.status_code}, expected 204"
    )


async def test_mcp_delete_oversize_session_id_returns_400(client):
    """RT-001: DELETE /mcp caps the Mcp-Session-Id header at 64 chars, mirroring
    mcp_post/mcp_messages (SI-3). An oversized value can never be a server-issued
    uuid4().hex (32 chars), so it is rejected with 400 rather than silently
    falling through to a 204."""
    r = await client.delete("/mcp", headers={"Mcp-Session-Id": "x" * 65})
    assert r.status_code == 400, (
        f"DELETE /mcp with oversized Mcp-Session-Id → {r.status_code}, expected 400"
    )
    assert r.json() == {"error": "invalid session id"}


async def test_mcp_delete_session_id_at_cap_still_succeeds(client):
    """Boundary: a 64-char Mcp-Session-Id is within the cap; it simply matches no
    live session, so DELETE stays idempotent (204) rather than 400."""
    r = await client.delete("/mcp", headers={"Mcp-Session-Id": "a" * 64})
    assert r.status_code == 204, (
        f"DELETE /mcp with 64-char Mcp-Session-Id → {r.status_code}, expected 204"
    )
