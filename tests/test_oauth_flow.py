"""OAuth 2.1 flow tests — token endpoint, DCR, and scope/error shapes.

Covers:
  C3-O1  Token endpoint is not auth-gated (public PKCE client)
  C3-O2  Token endpoint: missing grant_type → 400 invalid_request
  C3-O3  Token endpoint: unsupported grant type → 400 unsupported_grant_type
  C3-O4  Token success helper omits scope key when scope is empty
  C3-O5  DCR with valid https redirect_uri → 201 + client_id + auth_method "none"
  C3-O6  DCR with non-loopback http redirect_uri → 400 invalid_redirect_uri
  C3-O7  DCR with localhost http redirect_uri → 201 (loopback allowed)

Token endpoint body is application/x-www-form-urlencoded (per RFC 6749 §4.1.3).
All tests use the shared async httpx client from conftest (asyncio_mode=auto).
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _form(data: dict[str, str]) -> bytes:
    """Encode a dict as application/x-www-form-urlencoded bytes."""
    from urllib.parse import urlencode

    return urlencode(data).encode()


_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


# ===========================================================================
# C3-O1 — Token endpoint is not auth-gated
# ===========================================================================


async def test_token_endpoint_no_auth_required(client):
    """POST /oauth/token with no Authorization header and a bad authorization
    code must NOT return 401.

    The token endpoint is public by design: PKCE provides the security
    (RFC 7636) so no client secret or Bearer is needed.  A bad code means
    400 invalid_grant, not 401."""
    r = await client.post(
        "/oauth/token",
        content=_form(
            {
                "grant_type": "authorization_code",
                "code": "no-such-code",
                "client_id": "no-such-client",
                "redirect_uri": "https://example.com/cb",
                "code_verifier": "A" * 43,
            }
        ),
        headers={**_FORM_HEADERS, "Authorization": ""},
    )
    # Must NOT be 401 — the endpoint is public.
    assert r.status_code != 401, (
        f"/oauth/token should not require auth (got 401); body: {r.text}"
    )
    # Expected: 400 with error=invalid_grant or invalid_request (missing params).
    assert r.status_code == 400, (
        f"/oauth/token with bad code expected 400; got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert body.get("error") in ("invalid_grant", "invalid_request"), (
        f"Expected invalid_grant or invalid_request; got: {body}"
    )


# ===========================================================================
# C3-O2 — Missing grant_type → 400 invalid_request
# ===========================================================================


async def test_token_endpoint_missing_grant_type(client):
    """POST /oauth/token with no grant_type must return 400 invalid_request
    (RFC 6749 §5.2)."""
    r = await client.post(
        "/oauth/token",
        content=_form({"code": "abc"}),
        headers=_FORM_HEADERS,
    )
    assert r.status_code == 400, f"Expected 400; got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("error") == "invalid_request", (
        f"Expected error=invalid_request; got: {body}"
    )


# ===========================================================================
# C3-O3 — Unsupported grant type → 400 unsupported_grant_type
# ===========================================================================


async def test_token_endpoint_unknown_grant_type(client):
    """POST /oauth/token with grant_type=client_credentials must return 400
    unsupported_grant_type — the server only supports authorization_code and
    refresh_token (RFC 6749 §5.2)."""
    r = await client.post(
        "/oauth/token",
        content=_form({"grant_type": "client_credentials"}),
        headers=_FORM_HEADERS,
    )
    assert r.status_code == 400, f"Expected 400; got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("error") == "unsupported_grant_type", (
        f"Expected error=unsupported_grant_type; got: {body}"
    )


# ===========================================================================
# C3-O4 — Token success omits scope when scope is empty
# ===========================================================================


def test_token_response_no_empty_scope():
    """_token_success must omit the ``scope`` key entirely when scope is empty.

    Claude.ai rejects responses that carry ``"scope": ""`` — the key must
    not appear at all when there is no scope (§5.5).  This is a pure unit
    test of the helper function."""
    from agent_sdk.routes.oauth import _token_success

    # Pair with empty scope — scope key must be absent.
    pair_empty: dict[str, object] = {
        "access_token": "test-access-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "test-refresh-token",
        "scope": "",
    }
    response = _token_success(pair_empty)
    body = response.body
    import json

    decoded = json.loads(body)
    assert "scope" not in decoded, (
        f"scope key must be absent when empty; got: {decoded}"
    )

    # Pair with no scope key — must also produce no scope in output.
    pair_missing: dict[str, object] = {
        "access_token": "test-access-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "test-refresh-token",
    }
    response2 = _token_success(pair_missing)
    decoded2 = json.loads(response2.body)
    assert "scope" not in decoded2, (
        f"scope key must be absent when not set; got: {decoded2}"
    )

    # Pair with a real scope — must be present.
    pair_scoped: dict[str, object] = {
        "access_token": "test-access-token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "test-refresh-token",
        "scope": "read write",
    }
    response3 = _token_success(pair_scoped)
    decoded3 = json.loads(response3.body)
    assert decoded3.get("scope") == "read write", (
        f"scope must be present when non-empty; got: {decoded3}"
    )


# ===========================================================================
# C3-O5 — DCR valid https redirect_uri → 201
# ===========================================================================


async def test_dcr_valid_redirect_uri(client):
    """POST /oauth/register with a valid https redirect_uri must return 201
    and include ``client_id`` and ``token_endpoint_auth_method: "none"``."""
    import json

    r = await client.post(
        "/oauth/register",
        content=json.dumps({"redirect_uris": ["https://example.com/cb"]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201, f"DCR expected 201; got {r.status_code}: {r.text}"
    body = r.json()
    assert "client_id" in body, (
        f"DCR response must include client_id; got keys: {list(body.keys())}"
    )
    assert body.get("token_endpoint_auth_method") == "none", (
        f"DCR must set token_endpoint_auth_method=none; got: {body}"
    )


# ===========================================================================
# C3-O6 — DCR non-loopback http redirect_uri → 400 invalid_redirect_uri
# ===========================================================================


async def test_dcr_invalid_redirect_uri(client):
    """POST /oauth/register with a non-loopback http:// redirect_uri must
    return 400 invalid_redirect_uri.

    Only https (and http://localhost / http://127.0.0.1) are permitted;
    plain http to a remote host leaks the auth code (RFC 6749 §10.3)."""
    import json

    r = await client.post(
        "/oauth/register",
        content=json.dumps({"redirect_uris": ["http://example.com/cb"]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400, (
        f"Non-loopback http redirect_uri expected 400; got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert body.get("error") == "invalid_redirect_uri", (
        f"Expected error=invalid_redirect_uri; got: {body}"
    )


# ===========================================================================
# C3-O7 — DCR localhost http redirect_uri → 201 (loopback is allowed)
# ===========================================================================


async def test_dcr_loopback_redirect_uri_allowed(client):
    """POST /oauth/register with http://localhost/... must return 201.

    Loopback http is a security exception for native-app flows (RFC 8252 §7.3);
    the SDK must not reject it."""
    import json

    r = await client.post(
        "/oauth/register",
        content=json.dumps({"redirect_uris": ["http://localhost:8080/cb"]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201, (
        f"localhost http redirect_uri expected 201; got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert "client_id" in body, (
        f"DCR response must include client_id; got keys: {list(body.keys())}"
    )
