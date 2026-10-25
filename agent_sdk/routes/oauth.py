"""OAuth 2.1 authorization-server routes (DESIGN.md §5.5, §6, §10.3).

The Claude.ai-connector-compatible chain, mounted at the app root:

- ``GET /.well-known/oauth-protected-resource`` and the path-suffixed
  ``/.well-known/oauth-protected-resource/mcp`` (Claude probes the suffixed
  form first) — RFC 9728, ETagged.
- ``GET /.well-known/oauth-authorization-server`` — RFC 8414, ETagged.
  ``code_challenge_methods_supported: ["S256"]`` is load-bearing for
  Claude.ai's PKCE probe.
- ``POST /oauth/register`` — RFC 7591 DCR, unauthenticated + per-IP
  rate-limited (``unauth_limiter``; failed bearers on ``/oauth/revoke`` count
  in the separate ``bearer_limiter``, GH-265/GH-272). The security gate is the admin-gated /authorize, not DCR.
- ``GET/POST /oauth/authorize`` — minimal inline consent page (no template
  dependency; ``frame-ancestors 'none'`` + ``X-Frame-Options: DENY``).
  ``form-action`` is dynamically widened from a bare ``'self'`` to include
  the validated ``redirect_uri``'s origin (``_redirect_security_headers``,
  GH-122/RT-001) — required because Chromium/Electron enforces
  ``form-action`` from the CSP of the form-owning document, not a later 30x
  hop's headers (crbug.com/932518), so the consent-page render and both
  redirects (error + success) all need the widened policy for the Approve
  button to actually reach the OAuth client. Only the unknown-client /
  unregistered-redirect_uri error page keeps the bare ``form-action 'self'``
  — it has no trusted destination to widen to. Approval requires a REAL
  admin API key (header- or form-borne); oauth-kind tokens never verify on
  this path (§5.5 surface assertion).
- ``POST /oauth/token`` — PKCE S256 exchange + single-use refresh rotation.
  RFC 8707 ``resource`` is NOT re-required here (Claude.ai omits it); the
  audience bound at authorize travels via the code/refresh metadata.
- ``POST /oauth/revoke`` — RFC 7009; oauth-kind self-revoke only; admin api_key callers may revoke any token.

Every advertised URL derives from PUBLIC_URL via the OAuthTokenStore's
``issuer``/``canonical_resource`` (one-origin topology, §10.3) — never from
the Host header, so a malformed Host can never 503 this surface. 401s carry
``WWW-Authenticate`` pointing at the PRM (``AuthRuntime.prm_url``). A 429 is
JSON (``temporarily_unavailable``) with ``Retry-After`` and ``no-store`` on API
routes and the branded HTML page on the four browser routes.

Errors never echo caller-supplied values (codes, verifiers, tokens, URIs).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import logging
import re
import secrets
from typing import Any
from urllib.parse import ParseResult, parse_qsl, unquote_plus, urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..auth.middleware import (
    AuthRuntime,
    _client_key,
    _rate_limited,
    _prm_challenge,
    unauth_rate_limit,
)
from ..auth.oauth_tokens import OAuthTokenStore
from ..auth.oidc import IdpDenied, IdpFlowStore, IdpUnavailable, OidcRelyingParty
from ..common.body import BodyTooLarge, read_capped_body
from ..common.etag import etag_for, matches
from ..common.json_strict import loads_strict
from ..credentials.store import NS_OAUTH_IDP
from ..models.errors import AgentError
from ._consent_ui import render_consent_page, render_notice_page

logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])

_MAX_BODY_BYTES = 16 * 1024
_MAX_REDIRECT_URI_LEN = 2048
_MAX_PARAM_LEN = 2048
_MAX_CLIENT_NAME_LEN = 256

# Consent page is the one HTML surface here: framing denied outright, inline
# styles only (no scripts — plain form POST, CSP-clean with no 'unsafe-inline'
# script source).
_CONSENT_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


BROWSER_OAUTH_ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/oauth/authorize"),
    ("GET", "/oauth/idp/callback"),
    ("POST", "/oauth/idp/consent"),
    ("POST", "/oauth/authorize"),
})
RATE_LIMITED_PAGE_TEXT = "Too many attempts. Wait a minute, then start again from the app."


def _agent_name(request: Request) -> str:
    """The agent's public name for the consent pages (settings.display_name
    normalizes a blank/placeholder AGENT_NAME)."""
    return str(request.app.state.settings.display_name)


def _oauth(request: Request) -> OAuthTokenStore:
    return request.app.state.oauth


def _runtime(request: Request) -> AuthRuntime:
    return request.app.state.auth


_IDP_COOKIE = "__Host-agent_sdk_idp"
_IDP_COOKIE_MAX_AGE = 600
_IDP_MAX_FLOW_COOKIES = 8


def _flow_id(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()[:16]


def _flow_cookie_name(flow_id: str) -> str:
    return f"{_IDP_COOKIE}_{flow_id}"


def _set_flow_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=_IDP_COOKIE_MAX_AGE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _clear_flow_cookie(response: Response, name: str) -> Response:
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
    return response


def _split_ticket(raw: str) -> tuple[str, str]:
    flow_id, _, ticket = raw.partition(".")
    if len(flow_id) != 16 or not ticket:
        return "", ""
    return flow_id, ticket


def _idp(request: Request) -> tuple[OidcRelyingParty, IdpFlowStore] | None:
    rp = getattr(request.app.state, "idp_rp", None)
    flows = getattr(request.app.state, "idp_flows", None)
    if rp is None or flows is None:
        return None
    return rp, flows


def _require_idp(request: Request) -> tuple[OidcRelyingParty, IdpFlowStore]:
    found = _idp(request)
    if found is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return found


# ---------------------------------------------------------------------------
# Discovery — RFC 9728 PRM (plain + path-suffixed) and RFC 8414 AS metadata
# ---------------------------------------------------------------------------


def _etag_json(request: Request, payload: dict[str, Any]) -> Response:
    etag = etag_for(payload)
    if matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(content=payload, headers={"ETag": etag})


def _prm_payload(store: OAuthTokenStore) -> dict[str, Any]:
    return {
        # MCP-scoped resource — canonical_resource is base_url/mcp (§5.5).
        "resource": store.canonical_resource,
        "authorization_servers": [store.issuer],
        "bearer_methods_supported": ["header"],
    }


def _bare_prm_payload(store: OAuthTokenStore) -> dict[str, Any]:
    return {
        # Agent-root resource — used by A2A (/v1/) and AG-UI (/ag-ui/) surfaces.
        "resource": store.issuer,
        "authorization_servers": [store.issuer],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(request: Request) -> Response:
    return _etag_json(request, _bare_prm_payload(_oauth(request)))


@router.get("/.well-known/oauth-protected-resource/mcp")
async def oauth_protected_resource_mcp(request: Request) -> Response:
    """Path-suffixed PRM (RFC 9728 §3.1) — Claude.ai probes this form first."""
    return _etag_json(request, _prm_payload(_oauth(request)))


@router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server(request: Request) -> Response:
    store = _oauth(request)
    issuer = store.issuer
    return _etag_json(
        request,
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "revocation_endpoint": f"{issuer}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": list(_AUTH_METHODS),
            "scopes_supported": [],
            "resource_indicators_supported": True,
        },
    )


# ---------------------------------------------------------------------------
# Dynamic Client Registration — RFC 7591
# ---------------------------------------------------------------------------


def _has_control_char(value: str) -> bool:
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)


# Hostname/IPv4 charset — deliberately excludes ``;`` ``'`` ``"`` space and
# everything else CSP-significant. ``urlparse().hostname`` does NOT validate
# against the URI authority grammar (RFC 3986 reg-name permits sub-delims
# like ``;``), so a control-char-free redirect_uri such as
# ``https://evil.com;frame-ancestors *;/cb`` parses with that whole string
# as ``hostname`` — this is the enforcement point that rejects it.
#
# Deliberately wider than strict RFC 1123: each label also permits ``_``
# (common in internal/dev hostnames — e.g. ``my_host.example.com``) and the
# whole host permits one trailing ``.`` (absolute FQDN — e.g.
# ``client.example.com.``). Neither character is CSP-significant, so
# admitting them does not reopen the injection this regex exists to close
# (RT-002); it only widens accepted charset back toward pre-RT-002 client
# compatibility (RT-002 follow-up).
#
# IPv6-literal hosts (e.g. the ``2001:db8::1`` that ``urlparse().hostname``
# returns, bracket-stripped, for ``https://[2001:db8::1]/cb``) are
# INTENTIONALLY rejected here: ``:`` is outside this charset, and
# _validated_origin has no bracket-aware reconstruction to re-emit a valid
# ``https://[2001:db8::1]`` origin, so a widened charset alone would let a
# validated IPv6 redirect_uri fall through to an unbracketed, malformed CSP
# origin. Fail-closed (reject the whole redirect_uri) is preferred over
# emitting a broken origin (RT-003). OAuth clients targeting this endpoint
# use hostnames or loopback (127.0.0.1/localhost), so this is not expected
# to affect real registrations; do not "fix" by loosening the charset
# without also adding bracket-aware IPv6 origin reconstruction.
_HOSTNAME_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?)*\.?$"
)


def _validated_origin(parsed: ParseResult) -> str | None:
    """Rebuild ``scheme://host[:port]`` from sanitized components only.

    Never interpolate ``parsed.netloc`` (or ``parsed.hostname``
    unvalidated) into a header or CSP — RFC 3986 reg-name permits
    characters (``;`` among them) that are significant to CSP, and a
    malformed port substring can smuggle the same characters through
    while ``hostname`` itself stays clean (RT-002). Returns ``None`` when
    the origin cannot be safely reconstructed — including for IPv6-literal
    hosts, which ``_HOSTNAME_RE`` rejects intentionally (RT-003: this
    function has no bracket-aware reconstruction, so it fails closed
    rather than risk emitting an unbracketed, malformed origin).

    The https-or-loopback-http scheme contract is enforced HERE, at the
    reconstruction boundary, not left to callers (RT-002 follow-up). This
    origin is emitted verbatim into a ``form-action`` CSP security header,
    so the function must never hand back a scheme it would not itself vouch
    for — a scheme-downgraded plain-http non-loopback origin (which would
    weaken the CSP to permit form submission over cleartext) or a non-http(s)
    scheme (``ftp://``, ``javascript://``, …). A caller that forgets to
    pre-run ``_valid_redirect_uri`` therefore still cannot widen the CSP to
    an unsafe origin; reconstruction fails closed to ``None`` and the header
    builder falls back to the bare ``form-action 'self'``.
    """
    hostname = parsed.hostname
    if not hostname or not _HOSTNAME_RE.fullmatch(hostname):
        return None
    # Scheme contract: https anywhere, or http only on the loopback hosts
    # (RFC 8252 §7.3 native-app callbacks). Everything else fails closed.
    if parsed.scheme == "http":
        if hostname not in ("localhost", "127.0.0.1"):
            return None
    elif parsed.scheme != "https":
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    origin = f"{parsed.scheme}://{hostname}"
    if port is not None:
        origin += f":{port}"
    return origin


def _valid_redirect_uri(uri: str) -> bool:
    """https required, except http for localhost/127.0.0.1 loopback callbacks.
    Fragments are forbidden on a redirect endpoint (RFC 6749 §3.1.2)."""
    if len(uri) > _MAX_REDIRECT_URI_LEN or _has_control_char(uri):
        return False
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    if parsed.fragment or not parsed.hostname:
        return False
    # _validated_origin is the single source of truth for the https-or-loopback-http
    # scheme/host contract (RT-001): a non-None return already guarantees scheme is
    # https (any valid host) or http on the localhost/127.0.0.1 loopback, with a
    # HOSTNAME_RE-clean host and a parseable port. The former trailing scheme+host
    # re-check here was provably always-True once this passed; collapsed to one return
    # so the loopback set cannot silently drift between two copies of the invariant.
    return _validated_origin(parsed) is not None


_AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")


def _too_large() -> HTTPException:
    return HTTPException(status_code=413, detail="request body too large")


@router.post("/oauth/register", dependencies=[Depends(unauth_rate_limit)])
async def oauth_register(request: Request) -> JSONResponse:
    """Unauthenticated DCR (rate-limited per §6). ``token_endpoint_auth_method``
    ∈ {none (default), client_secret_post, client_secret_basic}; PKCE S256 is
    mandatory for all. A confidential registration returns ``client_secret``
    exactly once (only its sha256 is stored). Open-DCR secrets are a
    compatibility measure, not a trust boundary — consent at /authorize is
    the real gate (GH-222)."""

    def _reg_error(code: str, description: str) -> JSONResponse:
        # RFC 7591 §3.2.2 error shape; never echoes the offending value.
        return JSONResponse(
            status_code=400, content={"error": code, "error_description": description}
        )

    try:
        raw = await read_capped_body(request, _MAX_BODY_BYTES)
    except BodyTooLarge:
        return _reg_error("invalid_client_metadata", "request body too large")
    try:
        body = loads_strict(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        return _reg_error("invalid_client_metadata", "request body must be valid JSON")
    if not isinstance(body, dict):
        return _reg_error("invalid_client_metadata", "request body must be a JSON object")

    redirect_uris = body.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return _reg_error(
            "invalid_redirect_uri", "redirect_uris must be a non-empty array"
        )
    for uri in redirect_uris:
        if not isinstance(uri, str) or not _valid_redirect_uri(uri):
            return _reg_error(
                "invalid_redirect_uri",
                "each redirect_uri must be https (or http://localhost / "
                "http://127.0.0.1) without a fragment",
            )

    client_name = body.get("client_name")
    if client_name is not None:
        if (
            not isinstance(client_name, str)
            or _has_control_char(client_name)
            or len(client_name) > _MAX_CLIENT_NAME_LEN
        ):
            return _reg_error("invalid_client_metadata", "client_name is invalid")

    method = body.get("token_endpoint_auth_method")
    if method is None:
        method = "none"
    if not isinstance(method, str) or method not in _AUTH_METHODS:
        return _reg_error(
            "invalid_client_metadata", "unsupported token_endpoint_auth_method"
        )
    client_secret = secrets.token_urlsafe(32) if method != "none" else None

    try:
        record = _oauth(request).register_client(
            list(redirect_uris),
            client_name=client_name,
            token_endpoint_auth_method=method,
            client_secret=client_secret,
        )
    except AgentError:
        return _reg_error("invalid_client_metadata", "registration capacity reached")

    response: dict[str, Any] = {
        "client_id": record["client_id"],
        "client_id_issued_at": int(record["created_at"]),
        "redirect_uris": record["redirect_uris"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
    }
    if client_name is not None:
        response["client_name"] = client_name
    if client_secret is not None:
        response["client_secret"] = client_secret
        response["client_secret_expires_at"] = 0
    return JSONResponse(
        status_code=201, content=response, headers={"Cache-Control": "no-store"}
    )


# ---------------------------------------------------------------------------
# Authorization endpoint — consent gated on a real admin API key
# ---------------------------------------------------------------------------

_AUTHORIZE_PARAMS = (
    "client_id",
    "redirect_uri",
    "response_type",
    "code_challenge",
    "code_challenge_method",
    "resource",
    "state",
    "scope",
)


def _clean_params(source: Any) -> dict[str, str]:
    """Extract + hygiene-bound the authorize params (query or form source).
    Oversized / control-char values are dropped to empty (treated as absent)."""
    cleaned: dict[str, str] = {}
    for name in _AUTHORIZE_PARAMS:
        value = source.get(name)
        if (
            isinstance(value, str)
            and len(value) <= _MAX_PARAM_LEN
            and not _has_control_char(value)
        ):
            cleaned[name] = value.strip()
        else:
            cleaned[name] = ""
    return cleaned


# Exact redirect_uri origins whose callback is itself a 30x hop to another
# origin, and the fixed sources that hop can land on. form-action is enforced
# across the whole form-submission redirect chain, so the hop's target must be
# allowed too. Microsoft Power Platform / Copilot Studio registers
# https://global.consent.azure-apim.net/redirect/<connector> and that endpoint
# 302s to a regional host (e.g. asia-001.consent.azure-apim.net). Keyed by the
# exact validated origin, so no client-supplied value ever reaches the CSP.
_KNOWN_REDIRECT_HOPS: dict[str, tuple[str, ...]] = {
    "https://global.consent.azure-apim.net": ("https://*.consent.azure-apim.net",),
}


def _redirect_security_headers(redirect_uri: str) -> dict[str, str]:
    """Consent-page CSP, but with ``form-action`` widened to include the
    validated ``redirect_uri``'s origin.

    Chromium/Electron enforces ``form-action`` across a form-submission
    redirect chain using the CSP of the form-owning *document*, not the CSP
    delivered on a later 30x hop — a 30x response never commits as a
    rendered document, so its CSP header is inert there (crbug.com/932518).
    That means this must be applied both to the redirect responses AND to
    the consent-page render itself (``_consent_page``, which hosts the
    ``<form>`` the user submits) — a bare ``form-action 'self'`` on either
    silently blocks the redirect to the OAuth client and the Approve button
    appears to do nothing. Only call this with a ``redirect_uri`` that has
    already passed ``_valid_redirect_uri`` (https, or http on the
    localhost/127.0.0.1 loopback) — never for the unknown-client /
    unregistered-redirect_uri error page, which has no trusted destination
    to widen to. Non-http(s) custom schemes (e.g. ``claude://``) are
    rejected by ``_valid_redirect_uri`` at registration and re-validation
    time, so this never sees one.

    The origin is rebuilt from sanitized host+port via
    ``_validated_origin`` — never spliced from ``parsed.netloc`` directly
    (RT-002) — and ``_validated_origin`` self-enforces the
    https-or-loopback-http scheme contract, so even a value that reaches
    this function without having passed ``_valid_redirect_uri`` can neither
    inject an extra CSP directive nor downgrade the origin to an insecure
    (plain-http non-loopback) or non-http(s) scheme; it just falls back to
    the bare ``form-action 'self'``.

    Widened by substituting the ``form-action 'self'`` token inside the
    shared ``_CONSENT_SECURITY_HEADERS`` policy string, never by
    re-spelling a second copy of the full policy (RT-001) — a hand-
    maintained duplicate can silently drift from the base (e.g. a future
    edit to ``default-src``/``frame-ancestors``/``base-uri`` on the base
    constant that forgets the copy here) with nothing to catch it.
    """
    parsed = urlparse(redirect_uri)
    origin = _validated_origin(parsed)
    headers = dict(_CONSENT_SECURITY_HEADERS)
    if origin is not None:
        sources = " ".join([origin, *_KNOWN_REDIRECT_HOPS.get(origin, ())])
        headers["Content-Security-Policy"] = _CONSENT_SECURITY_HEADERS[
            "Content-Security-Policy"
        ].replace("form-action 'self'", f"form-action 'self' {sources}")
    return headers


# Exact redirect_uri origins whose callback forwards across further origins the
# client picks at run time. Copilot Studio: global.consent.azure-apim.net ->
# <region>.consent.azure-apim.net -> copilotstudio.microsoft.com (seen 17 Oct
# 2026, GH-198). form-action covers every hop of a form submission's redirect
# chain, so no fixed allow-list can be complete. For these origins a form POST
# ends on our own origin with a 200 page that moves on by meta refresh: a new
# navigation, outside the form-submission chain and so outside form-action.
_HANDOFF_REDIRECT_ORIGINS: frozenset[str] = frozenset(
    {"https://global.consent.azure-apim.net"}
)


def _client_redirect(url: str, redirect_uri: str, status: int) -> Response:
    """Send the browser back to the OAuth client after a form POST: a plain
    30x, or the meta-refresh hand-off page for ``_HANDOFF_REDIRECT_ORIGINS``.
    ``redirect_uri`` must already be validated; ``url`` is built from it."""
    headers = _redirect_security_headers(redirect_uri)
    if _validated_origin(urlparse(redirect_uri)) not in _HANDOFF_REDIRECT_ORIGINS:
        return RedirectResponse(url=url, status_code=status, headers=headers)
    body = render_notice_page(
        title="Returning to the app",
        message="You’re being sent back to the app now.",
        hint="If nothing happens in a few seconds, choose Continue.",
        continue_url=url,
    )
    return HTMLResponse(content=body, status_code=200, headers=headers)


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    body = render_notice_page(
        title="Sign-in couldn’t continue",
        message=message,
        hint="Close this page and start again from the app you came from.",
    )
    return HTMLResponse(content=body, status_code=status, headers=_CONSENT_SECURITY_HEADERS)


def _error_redirect(redirect_uri: str, error: str, state: str) -> Response:
    """RFC 6749 §4.1.2.1 — once the redirect_uri is validated, errors go back
    to the client via redirect, not as a local error page."""
    query: dict[str, str] = {"error": error}
    if state:
        query["state"] = state
    sep = "&" if urlparse(redirect_uri).query else "?"
    return _client_redirect(f"{redirect_uri}{sep}{urlencode(query)}", redirect_uri, 302)


def _validate_authorize(
    store: OAuthTokenStore, params: dict[str, str]
) -> tuple[dict[str, Any] | None, Response | None]:
    """Validate authorize params; returns (cleaned, error_response).

    Two failure modes per RFC 6749 §4.1.2.1: an unknown client or an
    unregistered redirect_uri must NEVER cause a redirect (400 page — we
    cannot trust the destination); every later failure redirects back to the
    validated redirect_uri with an ``error`` param.
    """
    client_id = params["client_id"]
    redirect_uri = params["redirect_uri"]
    if not client_id or not redirect_uri:
        return None, _error_page("The sign-in link is missing details (client_id or redirect_uri).")
    client = store.get_client(client_id)
    if client is None:
        return None, _error_page("This app isn’t registered with this agent (unknown client).")
    registered = client.get("redirect_uris")
    if not isinstance(registered, list) or redirect_uri not in registered:
        return None, _error_page(
            "The address this app asked to return to isn’t one it registered (redirect_uri)."
        )
    if not _valid_redirect_uri(redirect_uri):
        # Defense in depth — never trust the DCR record alone.
        return None, _error_page(
            "The address this app asked to return to isn’t allowed (redirect_uri)."
        )

    state = params["state"]
    if params["response_type"] != "code":
        return None, _error_redirect(redirect_uri, "unsupported_response_type", state)
    # PKCE S256 required; an S256 challenge is exactly 43 unpadded base64url
    # chars — reject any other shape before it can reach the token exchange.
    challenge = params["code_challenge"]
    if params["code_challenge_method"] != "S256" or not challenge:
        return None, _error_redirect(redirect_uri, "invalid_request", state)
    if len(challenge) != 43 or any(
        ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for ch in challenge
    ):
        return None, _error_redirect(redirect_uri, "invalid_request", state)

    # RFC 8707 resource: defaulted to the canonical MCP URI when omitted;
    # validated against the two-value audience set otherwise (§5.5).
    audience = store.validate_audience(params["resource"] or None)
    if audience is None:
        return None, _error_redirect(redirect_uri, "invalid_target", state)

    client_name = client.get("client_name")
    return (
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "scope": params["scope"],
            "state": state,
            "audience": audience,
            "client_name": client_name if isinstance(client_name, str) else client_id[:8],
        },
        None,
    )


def _consent_page(
    cleaned: dict[str, Any],
    params: dict[str, str],
    *,
    agent_name: str,
    error: str | None = None,
    status: int = 200,
) -> HTMLResponse:
    """Inline consent form (no template dependency; layout in _consent_ui).
    The admin API key is form-borne (password field, autocomplete off); all
    round-tripped OAuth params ride as hidden fields, attribute-escaped."""
    hidden = "\n".join(
        f'<input type="hidden" name="{name}" value="{html.escape(params[name], quote=True)}">'
        for name in _AUTHORIZE_PARAMS
    )
    form_html = (
        f"{hidden}\n"
        '<p class="note">Approval requires an admin API key.</p>\n'
        '<input type="password" name="api_key" placeholder="Admin API key"'
        ' aria-label="Admin API key" autocomplete="off" autofocus required>\n'
        '<div class="actions one">'
        '<button type="submit" class="primary">Approve</button></div>'
    )
    body = render_consent_page(
        agent_name=agent_name,
        client_name=str(cleaned["client_name"]),
        return_host=urlparse(cleaned["redirect_uri"]).hostname or "",
        audience=str(cleaned["audience"]),
        form_action="/oauth/authorize",
        form_html=form_html,
        allow_label="Approve",
        error=error,
    )
    headers = _redirect_security_headers(str(cleaned["redirect_uri"]))
    return HTMLResponse(content=body, status_code=status, headers=headers)


@router.get("/oauth/authorize", dependencies=[Depends(unauth_rate_limit)])
async def oauth_authorize_page(request: Request) -> Response:
    """Render the consent page. The page itself is unauthenticated (it only
    reflects validated registration data); approval (the POST) is the gate.

    One-time consent (GH-136): when ``oauth_one_time_consent`` is enabled
    AND this client has already been approved by an admin (``consented``, set
    only by the admin-key POST path and ``provision-org-oauth-client`` — IdP
    user consent writes ``user_consented_at`` instead and never reaches this
    shortcut), skip the page and issue the code directly.

    This is a SHORT-CIRCUIT, never a bypass of validation: ``_validate_authorize``
    has already run, so an unknown client, an unregistered ``redirect_uri``, a
    malformed PKCE challenge or a bad audience is refused exactly as before,
    and the code can only ever be delivered to a URI this client registered.
    A never-approved client still gets the admin gate — DCR mints a fresh
    ``client_id`` with ``consented: False`` on every registration, so a
    self-registered client can never authorize itself.

    Trust is bound to the *registration* (``client_id``), not to a person or
    an org (GH-138): everyone who reaches the server through an approved
    client_id inherits that approval, but each connector's own DCR call
    mints its OWN client_id — this does not, by itself, make a second user's
    independent registration skip the gate. Two scopes fall out of that:

    - per-registration (default behavior, no extra setup): a RETURNING
      client skips repeat approval; a brand-new registration still hits the
      gate once.
    - per-org (opt-in, see ``python -m agent_sdk provision-org-oauth-client``):
      an admin pre-mints and pre-approves ONE ``client_id`` offline, then
      pins it into the connector platform's static/pre-registered OAuth
      Client ID field so every org member shares that single registration
      instead of each performing their own DCR call.

    The auto-approval is logged at INFO for audit either way.
    """
    params = _clean_params(request.query_params)
    store = _oauth(request)
    cleaned, error = _validate_authorize(store, params)
    if error is not None:
        return error
    assert cleaned is not None

    idp = _idp(request)
    if idp is not None:
        return await _federate(request, idp, params, cleaned)

    runtime = _runtime(request)
    client = store.get_client(cleaned["client_id"])
    if runtime.oauth_one_time_consent and (client or {}).get("consented"):
        code = store.mint_code(
            client_id=cleaned["client_id"],
            redirect_uri=cleaned["redirect_uri"],
            code_challenge=cleaned["code_challenge"],
            scope=cleaned["scope"],
            audience=cleaned["audience"],
        )
        query: dict[str, str] = {"code": code}
        if cleaned["state"]:
            query["state"] = cleaned["state"]
        sep = "&" if urlparse(cleaned["redirect_uri"]).query else "?"
        logger.info(
            "oauth authorize auto-approved (one-time consent) client_id=%s...",
            cleaned["client_id"][:8],
        )
        return RedirectResponse(
            url=f"{cleaned['redirect_uri']}{sep}{urlencode(query)}",
            status_code=303,
            headers=_redirect_security_headers(cleaned["redirect_uri"]),
        )

    return _consent_page(cleaned, params, agent_name=_agent_name(request))


# ---------------------------------------------------------------------------
# Upstream IdP sign-in (opt-in, GH-152 / ADR-003) — only live when
# AGENT_SDK_OAUTH_IDP=oidc; both routes 404 otherwise.
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _redirect_with(redirect_uri: str, query: dict[str, str], status: int) -> Response:
    sep = "&" if urlparse(redirect_uri).query else "?"
    return _client_redirect(f"{redirect_uri}{sep}{urlencode(query)}", redirect_uri, status)


async def _federate(
    request: Request,
    idp: tuple[OidcRelyingParty, IdpFlowStore],
    params: dict[str, str],
    cleaned: dict[str, Any],
) -> Response:
    rp, flows = idp
    redirect_uri, state = cleaned["redirect_uri"], cleaned["state"]
    # Read per request, never cached (SI-4): rotation needs no restart.
    if not request.app.state.credential_store.get(NS_OAUTH_IDP, "client_secret"):
        return _error_redirect(redirect_uri, "temporarily_unavailable", state)
    verifier, challenge = _pkce_pair()
    nonce = secrets.token_urlsafe(24)
    binding = secrets.token_urlsafe(32)
    try:
        flow_state = flows.put(
            params=params,
            code_verifier=verifier,
            nonce=nonce,
            binding=binding,
            source=_client_key(request, _runtime(request)),
        )
    except IdpUnavailable:
        return _error_redirect(redirect_uri, "temporarily_unavailable", state)
    try:
        url = await rp.build_authorize_url(flow_state, nonce, challenge)
    except IdpUnavailable:
        flows.pop(flow_state, binding)
        return _error_redirect(redirect_uri, "temporarily_unavailable", state)
    response = RedirectResponse(
        url=url,
        status_code=302,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    new_name = _flow_cookie_name(_flow_id(flow_state))
    prefix = f"{_IDP_COOKIE}_"
    existing = [n for n in request.cookies if n.startswith(prefix) and n != new_name]
    for stale in existing[: max(0, len(existing) - (_IDP_MAX_FLOW_COOKIES - 1))]:
        _clear_flow_cookie(response, stale)
    _set_flow_cookie(response, new_name, binding)
    logger.info("oauth authorize federated client_id=%s...", cleaned["client_id"][:8])
    return response


def _idp_local_error() -> HTMLResponse:
    return _error_page("This sign-in link is invalid or has expired. Start again from the app.")


def _idp_consent_page(
    cleaned: dict[str, Any], label: str | None, ticket: str, *, agent_name: str
) -> HTMLResponse:
    form_html = (
        f'<input type="hidden" name="ticket" value="{html.escape(ticket, quote=True)}">\n'
        '<div class="actions">'
        '<button type="submit" name="decision" value="deny" class="secondary">Deny</button>'
        '<button type="submit" name="decision" value="allow" class="primary">Allow</button>'
        "</div>"
    )
    body = render_consent_page(
        agent_name=agent_name,
        client_name=str(cleaned["client_name"]),
        return_host=urlparse(cleaned["redirect_uri"]).hostname or "",
        audience=str(cleaned["audience"]),
        form_action="/oauth/idp/consent",
        form_html=form_html,
        signed_in_as=label or "your account",
    )
    return HTMLResponse(
        content=body,
        status_code=200,
        headers=_redirect_security_headers(str(cleaned["redirect_uri"])),
    )


@router.get("/oauth/idp/callback", dependencies=[Depends(unauth_rate_limit)])
async def oauth_idp_callback(request: Request) -> Response:
    """Unauthenticated by design (ADR-003 D12): gated by single-use ``state``
    bound to the per-flow ``__Host-agent_sdk_idp_<id>`` browser cookie."""
    rp, flows = _require_idp(request)
    state = request.query_params.get("state", "")
    flow_id = _flow_id(state)
    name = _flow_cookie_name(flow_id)
    cookie = request.cookies.get(name, "")
    flow = flows.pop(state, cookie) if state and cookie else None
    if flow is None:
        return _clear_flow_cookie(_idp_local_error(), name) if cookie else _idp_local_error()
    cleaned, error = _validate_authorize(_oauth(request), flow.params)
    if error is not None or cleaned is None:
        return _clear_flow_cookie(_idp_local_error(), name)
    redirect_uri, client_state = cleaned["redirect_uri"], cleaned["state"]

    if request.query_params.get("error"):
        return _clear_flow_cookie(_error_redirect(redirect_uri, "access_denied", client_state), name)
    code = request.query_params.get("code", "")
    if not code or len(code) > _MAX_PARAM_LEN * 4:
        return _clear_flow_cookie(_error_redirect(redirect_uri, "access_denied", client_state), name)
    try:
        id_token = await rp.exchange_code(code, flow.code_verifier)
        user, label = await rp.validate_id_token(id_token, flow.nonce)
    except IdpDenied:
        logger.info("oauth idp sign-in denied client_id=%s...", cleaned["client_id"][:8])
        return _clear_flow_cookie(_error_redirect(redirect_uri, "access_denied", client_state), name)
    except IdpUnavailable:
        return _clear_flow_cookie(
            _error_redirect(redirect_uri, "temporarily_unavailable", client_state), name
        )
    ticket = flows.put_consent(flow, user=user, label=label, binding=cookie)
    return _idp_consent_page(
        cleaned, label, f"{flow_id}.{ticket}", agent_name=_agent_name(request)
    )


@router.post("/oauth/idp/consent", dependencies=[Depends(unauth_rate_limit)])
async def oauth_idp_consent(request: Request) -> Response:
    """Unauthenticated by design (ADR-003 D12): gated by a single-use consent
    ticket bound to the same browser cookie as the callback."""
    _, flows = _require_idp(request)
    form = await _parse_form(request)
    flow_id, ticket = _split_ticket(form.get("ticket", ""))
    name = _flow_cookie_name(flow_id)
    cookie = request.cookies.get(name, "") if flow_id else ""
    found = flows.pop_consent(ticket, cookie) if ticket and cookie else None
    if found is None:
        return _idp_local_error()
    store = _oauth(request)
    cleaned, error = _validate_authorize(store, found.flow.params)
    if error is not None or cleaned is None:
        return _clear_flow_cookie(_idp_local_error(), name)
    redirect_uri, client_state = cleaned["redirect_uri"], cleaned["state"]
    if form.get("decision") != "allow":
        return _clear_flow_cookie(_error_redirect(redirect_uri, "access_denied", client_state), name)
    # User consent, NOT admin approval: never set ``consented`` here, or a
    # later switch to oauth_idp=none + one-time consent would auto-approve
    # every client any directory user ever allowed (RT-001).
    store.mark_user_consented(cleaned["client_id"])
    code = store.mint_code(
        client_id=cleaned["client_id"],
        redirect_uri=redirect_uri,
        code_challenge=cleaned["code_challenge"],
        scope=cleaned["scope"],
        audience=cleaned["audience"],
        user=found.user,
        label=found.label,
    )
    query: dict[str, str] = {"code": code}
    if client_state:
        query["state"] = client_state
    logger.info("oauth idp consent allowed client_id=%s...", cleaned["client_id"][:8])
    return _clear_flow_cookie(_redirect_with(redirect_uri, query, 303), name)


async def _parse_form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded body → dict, size-capped. Avoids the
    python-multipart dependency ``request.form()`` would require."""
    try:
        raw = await read_capped_body(request, _MAX_BODY_BYTES)
    except BodyTooLarge:
        raise _too_large() from None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="invalid request body") from None
    return dict(parse_qsl(decoded, keep_blank_values=True))


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


@router.post("/oauth/authorize", dependencies=[Depends(unauth_rate_limit)])
async def oauth_authorize_approve(request: Request) -> Response:
    """Consent approval: re-validates everything (never trust the round-trip),
    requires a REAL admin API key (header- or form-borne), marks the client
    consented, mints a single-use code and redirects with ``code`` (+state).

    oauth-kind tokens are rejected structurally: only ``ApiKeyStore.verify``
    is consulted, and it can only ever resolve ``kind="api_key"`` identities
    (§5.5 — a connector token can never approve a new authorization).
    """
    if _idp(request) is not None:
        return _error_page("This sign-in method is not available.")
    store = _oauth(request)
    runtime = _runtime(request)

    form = await _parse_form(request)
    params = _clean_params(form)
    cleaned, error = _validate_authorize(store, params)
    if error is not None:
        return error
    assert cleaned is not None

    presented = _bearer(request) or form.get("api_key", "").strip()
    identity = (
        await asyncio.to_thread(runtime.api_keys.verify, presented) if presented else None
    )
    if identity is None or identity.kind != "api_key" or not identity.admin:
        # Re-render the consent form with a generic failure; the PRM-pointing
        # challenge rides along for programmatic callers (§5.5).
        page = _consent_page(
            cleaned,
            params,
            agent_name=_agent_name(request),
            error="Invalid or non-admin API key.",
            status=401,
        )
        page.headers["WWW-Authenticate"] = _prm_challenge(runtime.prm_url)
        return page

    store.mark_consented(cleaned["client_id"])
    code = store.mint_code(
        client_id=cleaned["client_id"],
        redirect_uri=cleaned["redirect_uri"],
        code_challenge=cleaned["code_challenge"],
        scope=cleaned["scope"],
        audience=cleaned["audience"],
    )
    query: dict[str, str] = {"code": code}
    if cleaned["state"]:
        query["state"] = cleaned["state"]
    # A loopback redirect_uri may already carry a query — join with '&' then.
    sep = "&" if urlparse(cleaned["redirect_uri"]).query else "?"
    logger.info("oauth authorize approved client_id=%s...", cleaned["client_id"][:8])
    return _client_redirect(
        f"{cleaned['redirect_uri']}{sep}{urlencode(query)}", cleaned["redirect_uri"], 303
    )


# ---------------------------------------------------------------------------
# Token endpoint — PKCE exchange + refresh rotation
# ---------------------------------------------------------------------------


_TOKEN_NO_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _token_error(error: str, description: str) -> JSONResponse:
    """RFC 6749 §5.2 shape. Descriptions are generic constants — a failed
    exchange never learns WHY (unknown vs expired vs replayed vs PKCE)."""
    return JSONResponse(
        status_code=400,
        content={"error": error, "error_description": description},
        headers=_TOKEN_NO_CACHE,
    )


def _token_success(pair: dict[str, Any]) -> JSONResponse:
    body: dict[str, Any] = {
        "access_token": pair["access_token"],
        "token_type": "Bearer",
        "expires_in": pair["expires_in"],
        "refresh_token": pair["refresh_token"],
    }
    # OMIT the scope key entirely when empty — never `"scope": ""` (§5.5;
    # Claude.ai chokes on the empty-string form).
    if pair.get("scope"):
        body["scope"] = pair["scope"]
    return JSONResponse(content=body, headers=_TOKEN_NO_CACHE)


def _invalid_client(basic: bool) -> JSONResponse:
    headers = dict(_TOKEN_NO_CACHE)
    if basic:
        headers["WWW-Authenticate"] = 'Basic realm="oauth"'
    return JSONResponse(
        status_code=401,
        content={
            "error": "invalid_client",
            "error_description": "client authentication failed",
        },
        headers=headers,
    )


def _basic_credentials(request: Request) -> tuple[str, str] | None:
    """``Authorization: Basic`` → (client_id, secret), each form-urldecoded
    (RFC 6749 §2.3.1). None when absent or malformed."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value.strip():
        return None
    try:
        decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    cid, sep, secret = decoded.partition(":")
    if not sep:
        return None
    return unquote_plus(cid), unquote_plus(secret)


def _basic_used(request: Request) -> bool:
    """True when the caller sent HTTP Basic, so a 401 names the Basic scheme."""
    return request.headers.get("authorization", "").split(" ", 1)[0].lower() == "basic"


def _authenticate_client(
    request: Request, form: dict[str, str], store: OAuthTokenStore
) -> tuple[str, JSONResponse | None]:
    """Authenticate the calling client against its STORED registration.

    The required method comes from the stored record, never from the
    request. Returns ``(client_id, error)``. An unknown client_id that
    presents no secret passes through (the grant lookup rejects it, so client
    existence is not disclosed). A secret presented for an unknown, evicted
    or malformed client record fails closed with ``invalid_client``: a
    secret is never accepted unchecked. An empty ``client_secret`` (form or
    Basic) counts as not presented, so public clients from generic OAuth
    libraries keep working.
    """
    basic = _basic_credentials(request)
    client_id = form.get("client_id") or (basic[0] if basic else "")
    if basic and form.get("client_id") and basic[0] != form["client_id"]:
        return client_id, _invalid_client(False)
    form_secret = form.get("client_secret") or None
    if basic is not None and not basic[1]:
        basic = None if basic[0] == client_id else basic
    method = store.client_auth_method(client_id) if client_id else None
    if method is None:
        if form_secret is not None or basic is not None:
            return client_id, _invalid_client(_basic_used(request))
        return client_id, None
    if method == "none":
        if form_secret is not None or basic is not None:
            return client_id, _invalid_client(_basic_used(request))
        return client_id, None
    if method == "client_secret_post":
        ok = form_secret is not None and basic is None
        secret = form_secret
    elif method == "client_secret_basic":
        ok = basic is not None and form_secret is None
        secret = basic[1] if basic else None
    else:
        return client_id, _invalid_client(False)
    if not ok or not secret or not store.verify_client_secret(client_id, secret):
        return client_id, _invalid_client(method == "client_secret_basic" or _basic_used(request))
    return client_id, None


@router.post("/oauth/token", dependencies=[Depends(unauth_rate_limit)])
async def oauth_token(request: Request) -> JSONResponse:
    """No Bearer needed (PKCE; confidential clients also present their
    registered ``client_secret``, GH-222), per-IP rate-limited.
    ``resource`` is NOT required here — the audience bound at authorize rides
    the code metadata and survives refresh rotation (§5.5)."""
    store = _oauth(request)
    try:
        form = await _parse_form(request)
    except HTTPException:
        return _token_error("invalid_request", "malformed request body")

    grant_type = form.get("grant_type")

    if grant_type in ("authorization_code", "refresh_token"):
        client_id, auth_error = _authenticate_client(request, form, store)
        if auth_error is not None:
            return auth_error

    if grant_type == "authorization_code":
        code = form.get("code", "")
        redirect_uri = form.get("redirect_uri", "")
        code_verifier = form.get("code_verifier", "")
        if not (code and client_id and redirect_uri and code_verifier):
            return _token_error("invalid_request", "missing required parameter")
        meta = store.consume_code(
            code,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        if meta is None:
            return _token_error("invalid_grant", "code is invalid, expired, or used")
        client = store.get_client(client_id) or {}
        label = meta.get("label") or client.get("client_name")
        pair = store.mint_token_pair(
            client_id=meta["client_id"],
            scope=meta["scope"],
            audience=meta["audience"],
            label=label if isinstance(label, str) else None,
            user=meta.get("user"),
        )
        logger.info("oauth token issued grant=code client_id=%s...", client_id[:8])
        return _token_success(pair)

    if grant_type == "refresh_token":
        refresh_token = form.get("refresh_token", "")
        if not (refresh_token and client_id):
            return _token_error("invalid_request", "missing required parameter")
        pair2 = store.rotate_refresh(refresh_token, client_id=client_id)
        if pair2 is None:
            return _token_error("invalid_grant", "token is invalid, expired, or rotated")
        logger.info("oauth token issued grant=refresh client_id=%s...", client_id[:8])
        return _token_success(pair2)

    if not grant_type:
        return _token_error("invalid_request", "grant_type is required")
    return _token_error(
        "unsupported_grant_type",
        "grant_type must be authorization_code or refresh_token",
    )


# ---------------------------------------------------------------------------
# Revocation — RFC 7009
# ---------------------------------------------------------------------------


@router.post("/oauth/revoke", dependencies=[Depends(unauth_rate_limit)])
async def oauth_revoke(request: Request) -> JSONResponse:
    """RFC 7009 revocation — authenticated and public-client paths.
    admin api_key callers may revoke any token; oauth-kind, user and service
    callers self-revoke (silent no-op for tokens they do not own);
    clients (no Bearer) authenticate via client_id in the body — public
    clients by client_id alone, confidential ones with their secret.
    Always 200 for a well-formed request — existence never disclosed."""
    runtime = _runtime(request)
    store = _oauth(request)
    try:
        form = await _parse_form(request)
    except HTTPException:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "malformed body"},
        )
    token = form.get("token", "")
    if not token:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "token is required"},
        )
    # Try Bearer auth first (api_key or oauth-kind callers).
    presented = _bearer(request)
    if presented is not None:
        identity = await asyncio.to_thread(runtime.api_keys.verify, presented)
        if identity is None:
            identity = store.verify(presented)
        if identity is None:
            if not runtime.bearer_limiter.allow(_client_key(request, runtime)):
                raise _rate_limited()
            # Bad Bearer — reject; do NOT fall through to client_id path.
            raise HTTPException(
                status_code=401,
                detail="invalid credentials",
                headers={
                    "WWW-Authenticate": _prm_challenge(runtime.prm_url, invalid_token=True)
                },
            )
        store.revoke_by_value(token, caller=identity)
        return JSONResponse(content={})
    # No Bearer — client path: client_id in body (or Basic); confidential
    # clients must authenticate with their secret (RFC 7009 §2.1).
    client_id, auth_error = _authenticate_client(request, form, store)
    if auth_error is not None:
        return auth_error  # type: ignore[return-value]
    if not client_id:
        raise HTTPException(
            status_code=401,
            detail="missing bearer credentials",
            headers={"WWW-Authenticate": _prm_challenge(runtime.prm_url)},
        )
    store.revoke_by_client_id(token, client_id=client_id)
    return JSONResponse(content={})
