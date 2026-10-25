"""Auth dependencies (DESIGN.md §6, §10.3).

SDK auth is per-route FastAPI dependencies, never global middleware — team
routes mounted after ``build_app()`` are unauthenticated until they add
``Depends(require_identity)`` themselves (stated loudly in docs; the
self-check screen lists unprotected mounted routes).

Bearer is header-borne only. Three rate-limit windows: per-identity after
auth (``identity_limiter``); per-IP for failed bearers (``bearer_limiter``,
GH-265); per-IP for intrinsically unauthenticated paths (``unauth_limiter``,
OAuth endpoints). Bearer-less requests are never counted (GH-260). 401s carry
``WWW-Authenticate`` pointing at that surface's PRM; a failed-bearer 429
carries the same ``invalid_token`` challenge plus ``Retry-After`` (GH-272).
"""

from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import HTTPException, Request

from ..common.limits import RateLimiter, client_ip
from .api_keys import ApiKeyStore, BootstrapManager
from .identity import Identity


class TokenVerifier(Protocol):
    """Implemented by the OAuth token store (auth/oauth_tokens.py)."""

    def verify(self, token: str) -> Identity | None: ...


@dataclass(slots=True)
class AuthRuntime:
    """Lives at ``app.state.auth``; constructed by build_app()."""

    api_keys: ApiKeyStore
    bootstrap: BootstrapManager
    oauth: TokenVerifier | None
    trusted_proxies: list[str]
    prm_url: str       # path-suffixed /.well-known/oauth-protected-resource/mcp (for /mcp routes)
    bare_prm_url: str  # bare /.well-known/oauth-protected-resource (for /v1/, /ag-ui/ routes)
    # GH-136: when True, an already-consented DCR client re-authorizes without
    # the admin-key consent page (settings.oauth_one_time_consent).
    oauth_one_time_consent: bool = False
    # GH-152: when True, require_identity rejects NON-ADMIN api_key identities.
    idp_disable_api_keys: bool = False
    identity_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(100))
    unauth_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(30))
    # GH-265: failed-bearer 401s (and /oauth/revoke with a bad bearer) count here,
    # never in the OAuth-endpoint bucket (unauth_limiter).
    bearer_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(30))


def _runtime(request: Request) -> AuthRuntime:
    return request.app.state.auth


def _client_key(request: Request, runtime: AuthRuntime) -> str:
    peer = request.client.host if request.client else None
    ip = client_ip(peer, request.headers.get("x-forwarded-for"), runtime.trusted_proxies)
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _prm_challenge(prm_url: str, *, invalid_token: bool = False) -> str:
    """RFC 6750 §3-compliant Bearer challenge pointing at the PRM URL.

    ``invalid_token`` adds the §3.1 error code for a presented-but-bad bearer."""
    if invalid_token:
        return f'Bearer error="invalid_token", resource_metadata="{prm_url}"'
    return f'Bearer resource_metadata="{prm_url}"'


def _surface_prm(request: Request, runtime: AuthRuntime) -> str:
    return runtime.prm_url if request.url.path.startswith("/mcp") else runtime.bare_prm_url


def _unauthorized(
    request: Request, runtime: AuthRuntime, detail: str, *, invalid_token: bool = False
) -> HTTPException:
    # P6-03 + GH-33: MCP routes use the path-suffixed PRM; all other protected
    # routes (A2A /v1/*, AG-UI /ag-ui/*) use the bare PRM. Both point to valid
    # RFC 9728 endpoints; the resource value in each matches the accessed surface.
    challenge = _prm_challenge(_surface_prm(request, runtime), invalid_token=invalid_token)
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": challenge}
    )


def _rate_limited() -> HTTPException:
    return HTTPException(
        status_code=429, detail="rate limit exceeded", headers={"Retry-After": "60"}
    )


def _bearer_rate_limited(request: Request, runtime: AuthRuntime) -> HTTPException:
    """GH-272: failed-bearer 429 that also tells the client to re-authenticate."""
    exc = _rate_limited()
    exc.headers = {
        **(exc.headers or {}),
        "WWW-Authenticate": _prm_challenge(_surface_prm(request, runtime), invalid_token=True),
    }
    return exc


def resolve_identity(request: Request) -> Identity | None:
    """Best-effort identity resolution without raising (health/self-check).

    Does blocking credential-store I/O; async callers should run it via
    ``asyncio.to_thread``."""
    runtime = _runtime(request)
    token = _bearer(request)
    if token is None:
        return None
    identity = runtime.api_keys.verify(token)
    if identity is None and runtime.oauth is not None:
        identity = runtime.oauth.verify(token)
    return identity


async def _resolve_identity(request: Request) -> Identity:
    runtime = _runtime(request)
    ip_key = _client_key(request, runtime)
    token = _bearer(request)
    if token is None:
        raise _unauthorized(request, runtime, "missing bearer credentials")

    identity = await asyncio.to_thread(runtime.api_keys.verify, token)
    if identity is None and runtime.oauth is not None:
        identity = runtime.oauth.verify(token)
    if identity is None:
        if not runtime.bearer_limiter.allow(ip_key):
            raise _bearer_rate_limited(request, runtime)
        raise _unauthorized(request, runtime, "invalid credentials", invalid_token=True)

    if not runtime.identity_limiter.allow(identity.principal_key):
        raise _rate_limited()
    request.state.identity = identity
    return identity


async def require_identity(request: Request) -> Identity:
    """Any authenticated caller (api_key or oauth kind). With
    ``idp_disable_api_keys`` non-admin API keys are refused (admin and service
    keys stay valid so the console and automated runs keep working)."""
    identity = await _resolve_identity(request)
    runtime = _runtime(request)
    if (
        runtime.idp_disable_api_keys
        and identity.kind == "api_key"
        and not identity.admin
        and not identity.service
    ):
        # Counts in the failed-bearer bucket, same as an invalid bearer.
        if not runtime.bearer_limiter.allow(_client_key(request, runtime)):
            raise _bearer_rate_limited(request, runtime)
        raise _unauthorized(request, runtime, "invalid credentials", invalid_token=True)
    return identity


async def require_api_key_identity(request: Request) -> Identity:
    """Surfaces that reject oauth-kind callers (/admin/*, /oauth/authorize,
    key management — §5.5)."""
    identity = await _resolve_identity(request)
    if identity.kind != "api_key":
        raise HTTPException(
            status_code=403, detail="this surface requires an API key identity"
        )
    return identity


async def require_admin(request: Request) -> Identity:
    identity = await require_api_key_identity(request)
    if not identity.admin:
        raise HTTPException(status_code=403, detail="admin key required")
    return identity


def unauth_rate_limit(request: Request) -> None:
    """Per-IP ``unauth_limiter`` window for intrinsically unauthenticated paths
    (/oauth/register, /oauth/token, /oauth/revoke, consent POST). Failed bearers
    use ``bearer_limiter`` instead (GH-265)."""
    runtime = _runtime(request)
    if not runtime.unauth_limiter.allow(_client_key(request, runtime)):
        raise _rate_limited()
