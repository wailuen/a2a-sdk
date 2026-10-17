"""OAuth 2.1 flow tests — token endpoint, DCR, and scope/error shapes.

Covers:
  C3-O1  Token endpoint is not auth-gated (public PKCE client)
  C3-O2  Token endpoint: missing grant_type → 400 invalid_request
  C3-O3  Token endpoint: unsupported grant type → 400 unsupported_grant_type
  C3-O4  Token success helper omits scope key when scope is empty
  C3-O5  DCR with valid https redirect_uri → 201 + client_id + auth_method "none"
  C3-O6  DCR with non-loopback http redirect_uri → 400 invalid_redirect_uri
  C3-O7  DCR with localhost http redirect_uri → 201 (loopback allowed)
  GH-122 form-action CSP is widened to the redirect_uri's origin on every
         response that carries the form the browser evaluates the redirect
         chain against or that itself redirects there: the consent-page
         render (GET, and the 401 re-render on bad credentials), the
         success 303, and the error 302 — never on the 400 error page,
         which has no trusted redirect destination.
  RT-001 the consent-page render (not just the 30x redirects) must widen
         form-action too — Chromium/Electron enforces form-action across a
         form-submission redirect chain using the CSP of the form-owning
         document, not the CSP delivered on the 30x hop (crbug.com/932518).

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


# ===========================================================================
# GH-122 / RT-001 — form-action CSP widened on the consent-page render (the
# form-owning document) as well as the redirects to the OAuth client's
# redirect_uri. Chromium/Electron enforces form-action across a
# form-submission redirect chain using the CSP of the form-owning document,
# not the CSP delivered on the 30x hop — a 30x never commits as a rendered
# document, so its CSP header is inert (crbug.com/932518).
# ===========================================================================

_CODE_CHALLENGE = "A" * 43

_BARE_FORM_ACTION_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)

# RT-001: full-value pin (not just a form-action substring) for the widened
# CSP against a "https://client.example.com" redirect_uri — the shape
# widening MUST produce, verbatim, so a regression to default-src,
# style-src, frame-ancestors, or base-uri on the widened path (as opposed to
# a redirect_uri-origin change, which is expected to vary) fails CI instead
# of shipping unnoticed.
_WIDENED_FORM_ACTION_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; "
    "form-action 'self' https://client.example.com; "
    "frame-ancestors 'none'; base-uri 'none'"
)


async def _register_client(client, redirect_uri: str) -> str:
    import json

    r = await client.post(
        "/oauth/register",
        content=json.dumps({"redirect_uris": [redirect_uri]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201, f"DCR failed: {r.status_code}: {r.text}"
    body: dict = r.json()
    return body["client_id"]


async def test_authorize_approve_widens_form_action_to_https_redirect(client):
    """The success 303 redirect to an https:// OAuth client redirect_uri must
    widen the CSP form-action to include that origin, or Chromium/Electron
    silently blocks the redirect and Approve appears to do nothing (GH-122)."""
    redirect_uri = "https://client.example.com/callback"
    client_id = await _register_client(client, redirect_uri)
    r = await client.post(
        "/oauth/authorize",
        content=_form(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": _CODE_CHALLENGE,
                "code_challenge_method": "S256",
            }
        ),
        headers=_FORM_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 303, f"Expected 303 redirect; got {r.status_code}: {r.text}"
    csp = r.headers.get("content-security-policy", "")
    assert "form-action 'self' https://client.example.com" in csp, (
        f"CSP form-action must widen to the redirect_uri's origin; got: {csp}"
    )
    # RT-001: pin the whole policy, not just the form-action substring, so a
    # regression to default-src/style-src/frame-ancestors/base-uri on this
    # security-sensitive surface fails CI.
    assert csp == _WIDENED_FORM_ACTION_CSP, (
        f"Success-redirect CSP must equal the base policy with only "
        f"form-action widened; got: {csp}"
    )


async def test_authorize_approve_widens_form_action_to_loopback_redirect(client):
    """Same widening for a loopback http://127.0.0.1:<port>/callback
    redirect_uri — the native-app / Claude Desktop flow (RFC 8252 §7.3)."""
    redirect_uri = "http://127.0.0.1:51872/callback"
    client_id = await _register_client(client, redirect_uri)
    r = await client.post(
        "/oauth/authorize",
        content=_form(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": _CODE_CHALLENGE,
                "code_challenge_method": "S256",
            }
        ),
        headers=_FORM_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 303, f"Expected 303 redirect; got {r.status_code}: {r.text}"
    csp = r.headers.get("content-security-policy", "")
    assert "form-action 'self' http://127.0.0.1:51872" in csp, (
        f"CSP form-action must widen to the loopback origin; got: {csp}"
    )


async def _approve_csp(client, redirect_uri: str) -> str:
    client_id = await _register_client(client, redirect_uri)
    r = await client.post(
        "/oauth/authorize",
        content=_form(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": _CODE_CHALLENGE,
                "code_challenge_method": "S256",
            }
        ),
        headers=_FORM_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 303, f"Expected 303 redirect; got {r.status_code}: {r.text}"
    return r.headers.get("content-security-policy", "")


async def test_authorize_approve_allows_azure_apim_regional_hop(client):
    """Copilot Studio registers global.consent.azure-apim.net, which 302s to a
    regional host (asia-001.consent.azure-apim.net). form-action covers the
    whole chain, so the regional hop must be allowed or the browser blocks it
    after Approve and the connection fails."""
    csp = await _approve_csp(
        client, "https://global.consent.azure-apim.net/redirect/cr123-5fteamwork"
    )
    assert csp == (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "form-action 'self' https://global.consent.azure-apim.net "
        "https://*.consent.azure-apim.net; "
        "frame-ancestors 'none'; base-uri 'none'"
    ), f"got: {csp}"


async def test_regional_hop_not_added_for_lookalike_origin(client):
    """The extra source is keyed by the exact origin: a client on any other
    host (even another azure-apim.net subdomain) gets only its own origin."""
    csp = await _approve_csp(
        client, "https://global.consent.azure-apim.net.evil.example/redirect/x"
    )
    assert "*.consent.azure-apim.net" not in csp, f"got: {csp}"
    csp = await _approve_csp(client, "https://asia-001.consent.azure-apim.net/redirect/x")
    assert "*.consent.azure-apim.net" not in csp, f"got: {csp}"


async def test_authorize_error_redirect_widens_form_action(client):
    """An error redirect (e.g. unsupported_response_type) also redirects to
    the OAuth client's redirect_uri once it has been validated, so its CSP
    must be widened identically to the success path."""
    redirect_uri = "https://client.example.com/callback"
    client_id = await _register_client(client, redirect_uri)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "token",  # unsupported -> error redirect, not a page
            "code_challenge": _CODE_CHALLENGE,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302, f"Expected 302 error redirect; got {r.status_code}: {r.text}"
    csp = r.headers.get("content-security-policy", "")
    assert "form-action 'self' https://client.example.com" in csp, (
        f"Error-redirect CSP must widen to the redirect_uri's origin; got: {csp}"
    )
    # RT-001: pin the whole policy, not just the form-action substring, so a
    # regression to default-src/style-src/frame-ancestors/base-uri on this
    # security-sensitive surface fails CI.
    assert csp == _WIDENED_FORM_ACTION_CSP, (
        f"Error-redirect CSP must equal the base policy with only "
        f"form-action widened; got: {csp}"
    )


async def test_authorize_approve_error_redirect_post_widens_form_action(client):
    """RT-002: the GET variant above is not load-bearing — a GET is not a
    form submission, so the browser never enforces form-action on that
    redirect. The scenario that actually matters is a POST /oauth/authorize
    consent-form submission (with the admin bearer the ``client`` fixture
    pre-sets) carrying a tampered/unsupported response_type in the hidden
    fields — re-validation still hits ``_error_redirect`` before the admin
    key is even checked, and its CSP must widen identically to the GET
    error-redirect and the success 303 (GH-122/RT-001; shared
    ``_error_redirect`` code path, but this is the form-submission chain a
    browser actually enforces form-action across)."""
    redirect_uri = "https://client.example.com/callback"
    client_id = await _register_client(client, redirect_uri)
    r = await client.post(
        "/oauth/authorize",
        content=_form(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "token",  # tampered hidden field -> error redirect
                "code_challenge": _CODE_CHALLENGE,
                "code_challenge_method": "S256",
            }
        ),
        headers=_FORM_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 302, f"Expected 302 error redirect; got {r.status_code}: {r.text}"
    csp = r.headers.get("content-security-policy", "")
    assert "form-action 'self' https://client.example.com" in csp, (
        f"POST error-redirect CSP must widen to the redirect_uri's origin; got: {csp}"
    )


async def test_authorize_consent_page_widens_form_action(client):
    """RT-001: the GET consent-page render — the document that actually hosts
    the <form> the user submits — must widen form-action to the validated
    redirect_uri's origin too. Chromium/Electron enforces form-action across
    a form-submission redirect chain using the CSP of the form-owning
    document, not the CSP delivered on the later 30x hop, so a bare
    ``form-action 'self'`` here silently blocks the redirect to the OAuth
    client and Approve appears to do nothing (crbug.com/932518)."""
    redirect_uri = "https://client.example.com/callback"
    client_id = await _register_client(client, redirect_uri)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "code_challenge": _CODE_CHALLENGE,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200, f"Expected 200 consent page; got {r.status_code}: {r.text}"
    csp = r.headers.get("content-security-policy", "")
    assert "form-action 'self' https://client.example.com" in csp, (
        f"Consent-page CSP must widen to the redirect_uri's origin; got: {csp}"
    )
    # RT-001: pin the whole policy, not just the form-action substring, so a
    # regression to default-src/style-src/frame-ancestors/base-uri on this
    # security-sensitive surface fails CI.
    assert csp == _WIDENED_FORM_ACTION_CSP, (
        f"Consent-page CSP must equal the base policy with only form-action "
        f"widened; got: {csp}"
    )


async def test_authorize_approve_bad_api_key_rerender_widens_form_action(client):
    """RT-001: the 401 re-render (bad/missing admin API key) also serves the
    same form-owning document — it must widen form-action identically to the
    initial GET render, not fall back to bare 'self'."""
    redirect_uri = "https://client.example.com/callback"
    client_id = await _register_client(client, redirect_uri)
    r = await client.post(
        "/oauth/authorize",
        content=_form(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "code_challenge": _CODE_CHALLENGE,
                "code_challenge_method": "S256",
                "api_key": "not-a-real-key",
            }
        ),
        headers={**_FORM_HEADERS, "Authorization": ""},
        follow_redirects=False,
    )
    assert r.status_code == 401, f"Expected 401 re-render; got {r.status_code}: {r.text}"
    csp = r.headers.get("content-security-policy", "")
    assert "form-action 'self' https://client.example.com" in csp, (
        f"401 re-render CSP must widen to the redirect_uri's origin; got: {csp}"
    )


async def test_authorize_unknown_client_error_page_stays_bare_self(client):
    """The unknown-client / unregistered-redirect_uri 400 error page has no
    trusted redirect destination (RFC 6749 §4.1.2.1) — its CSP form-action
    must stay bare 'self', never widened to the caller-supplied redirect_uri."""
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": "no-such-client",
            "redirect_uri": "https://client.example.com/callback",
            "response_type": "code",
            "code_challenge": _CODE_CHALLENGE,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400, f"Expected 400 error page; got {r.status_code}: {r.text}"
    csp = r.headers.get("content-security-policy", "")
    assert csp == _BARE_FORM_ACTION_CSP, (
        f"Unknown-client error page CSP must stay bare form-action 'self'; got: {csp}"
    )


async def test_authorize_unregistered_redirect_uri_error_page_stays_bare_self(client):
    """RT-006: a real, registered client_id combined with a redirect_uri that
    was never registered for it is the more security-relevant bare-CSP case
    (GH-122 AC (f)) — an attacker can supply a real client_id and their own
    redirect_uri, so _validate_authorize's 'redirect_uri is not registered
    for this client' branch must stay bare form-action 'self' too, never
    widened to the attacker-supplied redirect_uri."""
    registered_uri = "https://client.example.com/callback"
    attacker_uri = "https://evil.example.com/callback"
    client_id = await _register_client(client, registered_uri)
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": attacker_uri,
            "response_type": "code",
            "code_challenge": _CODE_CHALLENGE,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400, f"Expected 400 error page; got {r.status_code}: {r.text}"
    csp = r.headers.get("content-security-policy", "")
    assert csp == _BARE_FORM_ACTION_CSP, (
        f"Unregistered-redirect_uri error page CSP must stay bare form-action "
        f"'self', never widened to the attacker-supplied redirect_uri; got: {csp}"
    )


def test_valid_redirect_uri_rejects_custom_scheme():
    """Non-http(s) custom schemes (e.g. a Claude Desktop-style ``claude://``
    callback) are already rejected at registration/validation time — the
    GH-122 form-action widening never needs to special-case a scheme other
    than https or loopback http, because such a redirect_uri can never pass
    _validate_authorize to reach _error_redirect or the success redirect."""
    from agent_sdk.routes.oauth import _valid_redirect_uri

    assert _valid_redirect_uri("claude://callback") is False


# ===========================================================================
# RT-002 — CSP directive injection via raw netloc interpolation
# ===========================================================================


def test_valid_redirect_uri_rejects_csp_significant_netloc():
    """A redirect_uri whose host component carries CSP-significant
    characters (``;`` ``'`` `` `` in the hostname, or in a malformed port
    field that still parses to a truthy ``hostname``) must be rejected
    outright — ``_has_control_char`` alone does not catch these, since
    none of them are control characters."""
    from agent_sdk.routes.oauth import _valid_redirect_uri

    assert _valid_redirect_uri("https://evil.com;frame-ancestors *;/cb") is False
    assert _valid_redirect_uri("https://evil.com'onmouseover=alert(1)/cb") is False
    assert _valid_redirect_uri("https://evil.com frame-ancestors */cb") is False
    # host itself is clean but the port field carries the injection —
    # parsed.hostname alone ('x.com') would previously pass unnoticed.
    assert _valid_redirect_uri("https://x.com:1234;frame-ancestors *;/cb") is False


async def test_dcr_rejects_csp_injection_redirect_uri(client):
    """POST /oauth/register with a redirect_uri crafted to inject a CSP
    directive via the netloc must be rejected at registration time, the
    same as any other invalid redirect_uri."""
    import json

    r = await client.post(
        "/oauth/register",
        content=json.dumps(
            {"redirect_uris": ["https://evil.com;frame-ancestors *;/cb"]}
        ),
        headers={"Content-Type": "application/json"},
    )
    body = r.json()
    assert r.status_code == 400, f"Expected 400; got {r.status_code}: {r.text}"
    assert body.get("error") == "invalid_redirect_uri", f"Expected invalid_redirect_uri; got: {body}"


def test_validated_origin_enforces_scheme_at_boundary():
    """RT-002 follow-up: the https-or-loopback-http scheme contract must live
    at the reconstruction boundary (``_validated_origin``), not only in the
    higher-level ``_valid_redirect_uri`` gate. A plain-http non-loopback host,
    or any non-http(s) scheme, must fail closed to None regardless of whether
    a caller remembered to pre-validate — the origin is emitted verbatim into
    a CSP security header, so the boundary must never hand back one it would
    not itself vouch for."""
    from urllib.parse import urlparse

    from agent_sdk.routes.oauth import _validated_origin

    # Scheme-downgrade: plain http to a non-loopback host must not reconstruct.
    assert _validated_origin(urlparse("http://evil.com/cb")) is None
    # Non-http(s) schemes must not reconstruct either.
    assert _validated_origin(urlparse("ftp://evil.com/cb")) is None
    assert _validated_origin(urlparse("javascript://evil.com/cb")) is None
    # The allowed schemes still reconstruct.
    assert _validated_origin(urlparse("https://ok.example.com/cb")) == "https://ok.example.com"
    assert _validated_origin(urlparse("http://localhost:8080/cb")) == "http://localhost:8080"
    assert _validated_origin(urlparse("http://127.0.0.1:51872/cb")) == "http://127.0.0.1:51872"


def test_redirect_security_headers_falls_back_for_insecure_scheme():
    """RT-002 follow-up: called directly with a non-loopback plain-http (or
    any non-http(s)) redirect_uri, the header builder must NOT widen the CSP
    to an insecure origin — it must fall back to the bare ``form-action
    'self'``. This is the self-enforcing boundary the finding requires, so a
    future call site that forgets to pre-validate cannot silently emit an
    insecure http origin into a security header."""
    from agent_sdk.routes.oauth import _redirect_security_headers

    for uri in ("http://evil.com/cb", "ftp://evil.com/cb", "javascript://evil.com/cb"):
        csp = _redirect_security_headers(uri)["Content-Security-Policy"]
        assert csp == _BARE_FORM_ACTION_CSP, (
            f"insecure/non-http(s) scheme must fall back to bare form-action "
            f"'self'; got for {uri!r}: {csp}"
        )


def test_redirect_security_headers_never_reflects_raw_netloc():
    """Defense in depth (RT-002): even called directly, the header builder
    must reconstruct the origin from sanitized host+port — never splice
    ``parsed.netloc`` straight into the CSP — so a value that somehow
    reaches this function with CSP-significant characters in its netloc
    cannot inject a duplicate/extra directive."""
    from agent_sdk.routes.oauth import _redirect_security_headers

    headers = _redirect_security_headers("https://evil.com;frame-ancestors *;/cb")
    csp = headers["Content-Security-Policy"]
    assert csp.count("frame-ancestors") == 1, f"expected exactly one frame-ancestors directive; got: {csp}"
    assert "frame-ancestors 'none'" in csp
    assert ";frame-ancestors *" not in csp.replace(" ", "")


# ===========================================================================
# RT-003 — SI-2 AC-named regression: a control char, or a ``;``/space
# smuggled through the netloc, must be rejected before it ever reaches
# _redirect_security_headers's form-action interpolation.
# ===========================================================================


def test_valid_redirect_uri_rejects_control_char():
    """A newline (or other C0/DEL control char) embedded in a redirect_uri
    must be rejected by _valid_redirect_uri before it can ever reach
    _redirect_security_headers — the control-char half of the SI-2
    CSP-injection guard (the ``;``/space half is covered by
    test_valid_redirect_uri_rejects_csp_significant_netloc and
    test_redirect_security_headers_rejects_space_injected_netloc)."""
    from agent_sdk.routes.oauth import _valid_redirect_uri

    assert _valid_redirect_uri("https://example.com/cb\nSet-Cookie:x") is False
    assert _valid_redirect_uri("https://example.com/cb\rSet-Cookie:x") is False
    assert _valid_redirect_uri("https://example.com/cb\x00") is False


def test_redirect_security_headers_rejects_space_injected_netloc():
    """A space-poisoned netloc (the other CSP directive/value separator
    alongside ``;``) must also fail to widen _redirect_security_headers's
    form-action — it must fall back to the bare CSP, never emit a second
    frame-ancestors (or any other) directive."""
    from agent_sdk.routes.oauth import _redirect_security_headers

    headers = _redirect_security_headers("https://evil.com frame-ancestors */cb")
    csp = headers["Content-Security-Policy"]
    assert csp == _BARE_FORM_ACTION_CSP, (
        f"space-poisoned netloc must fall back to bare form-action 'self'; got: {csp}"
    )
    assert csp.count("frame-ancestors") == 1, f"expected exactly one frame-ancestors directive; got: {csp}"


# ===========================================================================
# RT-002 (follow-up) — the RFC 1123 hostname charset must not be stricter
# than the SI-2 CSP-injection goal requires: underscores and a trailing
# FQDN dot are not CSP-significant and must stay accepted.
# ===========================================================================


def test_valid_redirect_uri_accepts_underscore_host():
    """A host label containing ``_`` (common in internal/dev hostnames) is
    not CSP-significant and must not be rejected by the RFC 1123 charset
    tightened for RT-002."""
    from agent_sdk.routes.oauth import _valid_redirect_uri

    assert _valid_redirect_uri("https://my_host.example.com/cb") is True


def test_valid_redirect_uri_accepts_trailing_dot_fqdn():
    """A trailing-dot absolute FQDN host is not CSP-significant and must
    not be rejected by the RFC 1123 charset tightened for RT-002."""
    from agent_sdk.routes.oauth import _valid_redirect_uri

    assert _valid_redirect_uri("https://client.example.com./cb") is True


def test_valid_redirect_uri_still_rejects_csp_significant_netloc_after_widening():
    """Widening the charset for underscore/trailing-dot must not reopen the
    original RT-002 CSP-injection hole."""
    from agent_sdk.routes.oauth import _valid_redirect_uri

    assert _valid_redirect_uri("https://evil.com;frame-ancestors *;/cb") is False
    assert _valid_redirect_uri("https://evil.com'onmouseover=alert(1)/cb") is False
    assert _valid_redirect_uri("https://evil.com frame-ancestors */cb") is False
    assert _valid_redirect_uri("https://x.com:1234;frame-ancestors *;/cb") is False


# ===========================================================================
# RT-003 (2026-07-19 pass) — IPv6-literal redirect_uris are intentionally
# fail-closed, not a lingering CSP-injection gap. _validated_origin cannot
# safely re-bracket ``urlparse().hostname``'s bracket-stripped IPv6 form
# into a valid ``https://[::1]`` origin, so it (correctly) refuses to
# reconstruct one rather than emit a malformed CSP directive. Locking this
# in so a future change doesn't "fix" it by loosening _HOSTNAME_RE alone,
# which would let a validated IPv6 redirect_uri fall through to a broken
# origin instead of being rejected.
# ===========================================================================


def test_valid_redirect_uri_rejects_ipv6_literal():
    """A bracketed IPv6-literal https redirect_uri must be rejected —
    _HOSTNAME_RE has no ``:`` in its charset and _validated_origin has no
    bracket-aware reconstruction, so this fails closed by design."""
    from agent_sdk.routes.oauth import _valid_redirect_uri

    assert _valid_redirect_uri("https://[2001:db8::1]/cb") is False
    assert _valid_redirect_uri("https://[::1]/cb") is False
    assert _valid_redirect_uri("https://[::1]:8443/cb") is False


def test_validated_origin_rejects_ipv6_literal():
    """Defense in depth: _validated_origin itself (not just the higher-level
    _valid_redirect_uri gate) must refuse to reconstruct an origin for an
    IPv6-literal host rather than emit an unbracketed, malformed one."""
    from urllib.parse import urlparse

    from agent_sdk.routes.oauth import _validated_origin

    assert _validated_origin(urlparse("https://[2001:db8::1]/cb")) is None


async def test_dcr_rejects_ipv6_literal_redirect_uri(client):
    """POST /oauth/register with an IPv6-literal redirect_uri must be
    rejected the same as any other unacceptable redirect_uri (RT-003)."""
    import json

    r = await client.post(
        "/oauth/register",
        content=json.dumps({"redirect_uris": ["https://[2001:db8::1]/cb"]}),
        headers={"Content-Type": "application/json"},
    )
    body = r.json()
    assert r.status_code == 400, f"Expected 400; got {r.status_code}: {r.text}"
    assert body.get("error") == "invalid_redirect_uri", f"Expected invalid_redirect_uri; got: {body}"
