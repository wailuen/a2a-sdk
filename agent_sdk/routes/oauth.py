"""OAuth 2.1 authorization-server routes (DESIGN.md §5.5, §6, §10.3).

The Claude.ai-connector-compatible chain, mounted at the app root:

- ``GET /.well-known/oauth-protected-resource`` and the path-suffixed
  ``/.well-known/oauth-protected-resource/mcp`` (Claude probes the suffixed
  form first) — RFC 9728, ETagged.
- ``GET /.well-known/oauth-authorization-server`` — RFC 8414, ETagged.
  ``code_challenge_methods_supported: ["S256"]`` is load-bearing for
  Claude.ai's PKCE probe.
- ``POST /oauth/register`` — RFC 7591 DCR, unauthenticated + per-IP
  rate-limited. The security gate is the admin-gated /authorize, not DCR.
- ``GET/POST /oauth/authorize`` — minimal inline consent page (no template
  dependency; ``frame-ancestors 'none'`` + ``X-Frame-Options: DENY``).
  Approval requires a REAL admin API key (header- or form-borne); oauth-kind
  tokens never verify on this path (§5.5 surface assertion).
- ``POST /oauth/token`` — PKCE S256 exchange + single-use refresh rotation.
  RFC 8707 ``resource`` is NOT re-required here (Claude.ai omits it); the
  audience bound at authorize travels via the code/refresh metadata.
- ``POST /oauth/revoke`` — RFC 7009; oauth-kind self-revoke only.

Every advertised URL derives from PUBLIC_URL via the OAuthTokenStore's
``issuer``/``canonical_resource`` (one-origin topology, §10.3) — never from
the Host header, so a malformed Host can never 503 this surface. 401s carry
``WWW-Authenticate`` pointing at the PRM (``AuthRuntime.prm_url``).

Errors never echo caller-supplied values (codes, verifiers, tokens, URIs).
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..auth.middleware import AuthRuntime, require_identity, unauth_rate_limit
from ..auth.oauth_tokens import OAuthTokenStore
from ..common.etag import etag_for, matches
from ..models.errors import AgentError

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


def _oauth(request: Request) -> OAuthTokenStore:
    return request.app.state.oauth


def _runtime(request: Request) -> AuthRuntime:
    return request.app.state.auth


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
        # The canonical resource string — the same exact value used in the
        # authorize-time resource validation and the token audience (§5.5).
        "resource": store.canonical_resource,
        "authorization_servers": [store.issuer],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource(request: Request) -> Response:
    return _etag_json(request, _prm_payload(_oauth(request)))


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
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [],
        },
    )


# ---------------------------------------------------------------------------
# Dynamic Client Registration — RFC 7591
# ---------------------------------------------------------------------------


def _has_control_char(value: str) -> bool:
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)


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
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")


def _too_large() -> HTTPException:
    return HTTPException(status_code=413, detail="request body too large")


@router.post("/oauth/register", dependencies=[Depends(unauth_rate_limit)])
async def oauth_register(request: Request) -> JSONResponse:
    """Unauthenticated DCR (rate-limited per §6). Public clients only —
    ``token_endpoint_auth_method: "none"`` + PKCE; no client secrets exist."""

    def _reg_error(code: str, description: str) -> JSONResponse:
        # RFC 7591 §3.2.2 error shape; never echoes the offending value.
        return JSONResponse(
            status_code=400, content={"error": code, "error_description": description}
        )

    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return _reg_error("invalid_client_metadata", "request body too large")
    try:
        body = json.loads(raw.decode("utf-8")) if raw else {}
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

    try:
        record = _oauth(request).register_client(
            list(redirect_uris), client_name=client_name
        )
    except AgentError:
        return _reg_error("invalid_client_metadata", "registration capacity reached")

    response: dict[str, Any] = {
        "client_id": record["client_id"],
        "client_id_issued_at": int(record["created_at"]),
        "redirect_uris": record["redirect_uris"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if client_name is not None:
        response["client_name"] = client_name
    return JSONResponse(status_code=201, content=response)


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


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    body = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Authorization error</title></head>"
        f"<body><h1>Authorization error</h1><p>{html.escape(message)}</p>"
        "</body></html>"
    )
    return HTMLResponse(content=body, status_code=status, headers=_CONSENT_SECURITY_HEADERS)


def _error_redirect(redirect_uri: str, error: str, state: str) -> RedirectResponse:
    """RFC 6749 §4.1.2.1 — once the redirect_uri is validated, errors go back
    to the client via redirect, not as a local error page."""
    query: dict[str, str] = {"error": error}
    if state:
        query["state"] = state
    sep = "&" if urlparse(redirect_uri).query else "?"
    return RedirectResponse(
        url=f"{redirect_uri}{sep}{urlencode(query)}",
        status_code=302,
        headers=_CONSENT_SECURITY_HEADERS,
    )


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
        return None, _error_page("missing client_id or redirect_uri")
    client = store.get_client(client_id)
    if client is None:
        return None, _error_page("unknown client")
    registered = client.get("redirect_uris")
    if not isinstance(registered, list) or redirect_uri not in registered:
        return None, _error_page("redirect_uri is not registered for this client")
    if not _valid_redirect_uri(redirect_uri):
        # Defense in depth — never trust the DCR record alone.
        return None, _error_page("redirect_uri is not acceptable")

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
    cleaned: dict[str, Any], params: dict[str, str], *, error: str | None = None, status: int = 200
) -> HTMLResponse:
    """Minimal inline consent form (no template dependency). The admin API key
    is form-borne (password field, autocomplete off); all round-tripped OAuth
    params ride as hidden fields, attribute-escaped."""
    hidden = "\n".join(
        f'<input type="hidden" name="{name}" value="{html.escape(params[name], quote=True)}">'
        for name in _AUTHORIZE_PARAMS
    )
    error_html = f'<p class="err">{html.escape(error)}</p>' if error else ""
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Authorize access</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background: #f5f6fa; color: #333; display: flex; min-height: 100vh;
       align-items: center; justify-content: center; margin: 0; }}
.box {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
        padding: 28px; width: 380px; max-width: 90vw; }}
h1 {{ font-size: 1.2rem; margin: 0 0 8px; }}
p {{ font-size: 0.9rem; color: #555; margin: 0 0 14px; }}
code {{ background: #f0f1f4; padding: 1px 5px; border-radius: 3px; }}
input {{ width: 100%; box-sizing: border-box; padding: 10px; margin-bottom: 12px;
         border: 1px solid #ccc; border-radius: 4px; font-size: 0.95rem; }}
button {{ width: 100%; padding: 10px; border: none; border-radius: 4px;
          background: #1565c0; color: #fff; font-size: 0.95rem; cursor: pointer; }}
.err {{ color: #c62828; }}
</style>
</head>
<body>
<div class="box">
<h1>Authorize access</h1>
<p><strong>{html.escape(str(cleaned["client_name"]))}</strong> is requesting access to
<code>{html.escape(str(cleaned["audience"]))}</code>.</p>
<p>Approval requires an admin API key.</p>
{error_html}
<form method="post" action="/oauth/authorize">
{hidden}
<input type="password" name="api_key" placeholder="Admin API key"
       autocomplete="off" autofocus required>
<button type="submit">Approve</button>
</form>
</div>
</body>
</html>
"""
    return HTMLResponse(content=body, status_code=status, headers=_CONSENT_SECURITY_HEADERS)


@router.get("/oauth/authorize", dependencies=[Depends(unauth_rate_limit)])
async def oauth_authorize_page(request: Request) -> Response:
    """Render the consent page. The page itself is unauthenticated (it only
    reflects validated registration data); approval (the POST) is the gate."""
    params = _clean_params(request.query_params)
    cleaned, error = _validate_authorize(_oauth(request), params)
    if error is not None:
        return error
    assert cleaned is not None
    return _consent_page(cleaned, params)


async def _parse_form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded body → dict, size-capped. Avoids the
    python-multipart dependency ``request.form()`` would require."""
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise _too_large()
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
    store = _oauth(request)
    runtime = _runtime(request)

    form = await _parse_form(request)
    params = _clean_params(form)
    cleaned, error = _validate_authorize(store, params)
    if error is not None:
        return error
    assert cleaned is not None

    presented = _bearer(request) or form.get("api_key", "").strip()
    identity = runtime.api_keys.verify(presented) if presented else None
    if identity is None or identity.kind != "api_key" or not identity.admin:
        # Re-render the consent form with a generic failure; the PRM-pointing
        # challenge rides along for programmatic callers (§5.5).
        page = _consent_page(
            cleaned, params, error="Invalid or non-admin API key.", status=401
        )
        page.headers["WWW-Authenticate"] = (
            f'Bearer resource_metadata="{runtime.prm_url}"'
        )
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
    return RedirectResponse(
        url=f"{cleaned['redirect_uri']}{sep}{urlencode(query)}",
        status_code=303,
        headers=_CONSENT_SECURITY_HEADERS,
    )


# ---------------------------------------------------------------------------
# Token endpoint — PKCE exchange + refresh rotation
# ---------------------------------------------------------------------------


def _token_error(error: str, description: str) -> JSONResponse:
    """RFC 6749 §5.2 shape. Descriptions are generic constants — a failed
    exchange never learns WHY (unknown vs expired vs replayed vs PKCE)."""
    return JSONResponse(
        status_code=400, content={"error": error, "error_description": description}
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
    return JSONResponse(content=body, headers={"Cache-Control": "no-store"})


@router.post("/oauth/token", dependencies=[Depends(unauth_rate_limit)])
async def oauth_token(request: Request) -> JSONResponse:
    """Unauthenticated by design (public client + PKCE), per-IP rate-limited.
    ``resource`` is NOT required here — the audience bound at authorize rides
    the code metadata and survives refresh rotation (§5.5)."""
    store = _oauth(request)
    try:
        form = await _parse_form(request)
    except HTTPException:
        return _token_error("invalid_request", "malformed request body")

    grant_type = form.get("grant_type")

    if grant_type == "authorization_code":
        code = form.get("code", "")
        client_id = form.get("client_id", "")
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
        label = client.get("client_name")
        pair = store.mint_token_pair(
            client_id=meta["client_id"],
            scope=meta["scope"],
            audience=meta["audience"],
            label=label if isinstance(label, str) else None,
        )
        logger.info("oauth token issued grant=code client_id=%s...", client_id[:8])
        return _token_success(pair)

    if grant_type == "refresh_token":
        refresh_token = form.get("refresh_token", "")
        client_id = form.get("client_id", "")
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
    api_key callers may revoke any token; oauth-kind callers self-revoke;
    public clients (no Bearer) authenticate via client_id in the body.
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
        identity = runtime.api_keys.verify(presented)
        if identity is None:
            identity = store.verify(presented)
        if identity is None:
            # Bad Bearer — reject; do NOT fall through to client_id path.
            raise HTTPException(
                status_code=401,
                detail="invalid credentials",
                headers={"WWW-Authenticate": f'Bearer resource_metadata="{runtime.prm_url}"'},
            )
        store.revoke_by_value(token, caller=identity)
        return JSONResponse(content={})
    # No Bearer — try public-client path: client_id in body.
    client_id = form.get("client_id", "")
    if not client_id:
        raise HTTPException(
            status_code=401,
            detail="missing bearer credentials",
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{runtime.prm_url}"'},
        )
    store.revoke_by_client_id(token, client_id=client_id)
    return JSONResponse(content={})
