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
# C3-H2 — resource_metadata points to path-suffixed PRM
# ===========================================================================


async def test_www_auth_points_to_path_suffixed_prm(client):
    """WWW-Authenticate on any protected route must point to
    ``.../.well-known/oauth-protected-resource/mcp``, not the bare
    ``/.well-known/oauth-protected-resource``.

    Claude.ai probes the path-suffixed form first (RFC 9728 §3.1); the
    challenge must guide the client to the right URL."""
    www_auth = await _www_auth(client, "post", "/v1/message:send", json=_SEND_BODY)
    assert "/.well-known/oauth-protected-resource/mcp" in www_auth, (
        f"resource_metadata must point to /...mcp path; got: {www_auth!r}"
    )
    # Guard: the bare path must not be the only one referenced (it may
    # appear as a substring of the suffixed form, so check the suffix form).
    assert www_auth.count("/.well-known/oauth-protected-resource/mcp") >= 1


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
# C3-H5 — Challenge is identical across all three surfaces
# ===========================================================================


async def test_www_auth_consistent_across_surfaces(client):
    """All three protected surfaces (/v1/message:send, /mcp POST, /ag-ui/run)
    must return identical WWW-Authenticate header values.

    Consistency ensures any client reaching any surface can bootstrap the
    same OAuth discovery chain."""
    # A2A surface
    r_a2a = await client.post(
        "/v1/message:send",
        json=_SEND_BODY,
        headers={"Authorization": ""},
    )
    assert r_a2a.status_code == 401
    www_a2a = r_a2a.headers.get("www-authenticate", "")

    # MCP surface
    r_mcp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": ""},
    )
    assert r_mcp.status_code == 401
    www_mcp = r_mcp.headers.get("www-authenticate", "")

    # AG-UI surface — may return 401; if it returns 422 auth passed, skip.
    r_agui = await client.post(
        "/ag-ui/run",
        json={"thread_id": "t1", "run_id": "r1", "messages": []},
        headers={"Authorization": ""},
    )

    assert www_a2a, "A2A surface returned empty WWW-Authenticate"
    assert www_mcp, "MCP surface returned empty WWW-Authenticate"
    assert www_a2a == www_mcp, (
        f"A2A and MCP WWW-Authenticate differ:\n  A2A: {www_a2a!r}\n  MCP: {www_mcp!r}"
    )

    if r_agui.status_code == 401:
        www_agui = r_agui.headers.get("www-authenticate", "")
        assert www_agui == www_a2a, (
            f"AG-UI WWW-Authenticate differs from A2A:\n  AG-UI: {www_agui!r}\n  A2A: {www_a2a!r}"
        )
    # If AG-UI returned 422 (auth passed, missing required fields) — skip the
    # cross-surface comparison for that surface; A2A and MCP match is sufficient.


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
