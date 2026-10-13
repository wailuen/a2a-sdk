"""OIDC relying party + flow-state store for opt-in upstream IdP sign-in
(GH-152, ADR-003 D8/D11). Component C-023 ``OidcRelyingParty`` / ``IdpFlowStore``.

SDK auth infrastructure, not a ``SourceAdapter``: its one outbound client is the
sanctioned SI-1 exception from ADR-003 D8. Every error message is a fixed
constant (SI-2): nothing from httpx, PyJWT or the IdP body reaches a message or
log line. ``jwt`` is imported lazily so the ``[oidc]`` extra stays optional.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from agent_sdk.common.http import _is_non_public_ip
from agent_sdk.common.redact import sanitize_text

logger = logging.getLogger("agent_sdk.auth.oidc")

_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 512 * 1024
_CACHE_TTL = 3600.0
_STALE_MAX = 24 * 3600.0
_FORCED_REFETCH_MIN_INTERVAL = 60.0
_LEEWAY_SECONDS = 60
_FLOW_TTL = 600.0
_CONSENT_TTL = 300.0
_MAX_FLOWS = 1000
_MAX_FLOWS_PER_SOURCE = 50
_MAX_TOKEN_LEN = 16 * 1024
_LABEL_MAX_LEN = 128


def _now() -> float:
    return time.time()


class IdpError(Exception):
    """Base for IdP failures. Messages are constants (SI-2)."""


class IdpUnavailable(IdpError):
    def __init__(self) -> None:
        super().__init__("identity provider unavailable")


class IdpDenied(IdpError):
    def __init__(self, reason_code: str) -> None:
        super().__init__("identity provider denied sign-in")
        self.reason_code = reason_code


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    tenant_id: str | None
    required_role: str | None
    required_group: str | None
    redirect_uri: str


@dataclass
class _Cached:
    value: Any
    fetched_at: float


def _host_of(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password:
            return None
        return parts.hostname
    except ValueError:
        return None


class OidcRelyingParty:
    def __init__(
        self,
        config: OidcConfig,
        secret_provider: Callable[[], str | None],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._secret_provider = secret_provider
        self._transport = transport
        self._issuer_host = _host_of(config.issuer)
        self._discovery: _Cached | None = None
        self._jwks: _Cached | None = None
        self._last_forced_jwks: float | None = None
        self._discovery_lock = asyncio.Lock()
        self._jwks_lock = asyncio.Lock()

    async def _check_issuer_host(self) -> None:
        host = self._issuer_host
        if host is None:
            raise IdpUnavailable()
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            if _is_non_public_ip(literal):
                raise IdpUnavailable()
            return
        if self._transport is not None:
            return
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None)
        except OSError:
            raise IdpUnavailable() from None
        for info in infos:
            if _is_non_public_ip(ipaddress.ip_address(info[4][0])):
                raise IdpUnavailable()

    async def _request(
        self, method: str, url: str, *, data: dict[str, str] | None = None
    ) -> tuple[int, bytes]:
        await self._check_issuer_host()
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=_TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                async with client.stream(method, url, data=data) as resp:
                    declared = resp.headers.get("content-length")
                    if declared is not None and declared.isdigit() and int(declared) > _MAX_RESPONSE_BYTES:
                        raise IdpUnavailable()
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            raise IdpUnavailable()
                    return resp.status_code, bytes(body)
        except IdpUnavailable:
            raise
        except Exception as exc:
            logger.warning("idp request failed: %s", type(exc).__name__)
            raise IdpUnavailable() from None

    async def _get_json(self, url: str) -> dict[str, Any]:
        status, body = await self._request("GET", url)
        if status != 200:
            raise IdpUnavailable()
        try:
            doc = json.loads(body)
        except ValueError:
            raise IdpUnavailable() from None
        if not isinstance(doc, dict):
            raise IdpUnavailable()
        return doc

    async def _refresh(
        self, cached: _Cached | None, fetch: Callable[[], Any], what: str
    ) -> _Cached:
        try:
            return _Cached(await fetch(), _now())
        except IdpUnavailable:
            if cached is not None and _now() - cached.fetched_at < _STALE_MAX:
                logger.warning("idp %s refresh failed; serving stale copy", what)
                return cached
            raise

    async def _fetch_discovery(self) -> dict[str, str]:
        issuer = self._config.issuer
        doc = await self._get_json(f"{issuer.rstrip('/')}/.well-known/openid-configuration")
        if doc.get("issuer") != issuer:
            raise IdpUnavailable()
        out: dict[str, str] = {}
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            value = doc.get(name)
            if not isinstance(value, str) or _host_of(value) != self._issuer_host:
                raise IdpUnavailable()
            out[name] = value
        return out

    async def _discover(self) -> dict[str, str]:
        async with self._discovery_lock:
            cached = self._discovery
            if cached is None or _now() - cached.fetched_at >= _CACHE_TTL:
                cached = self._discovery = await self._refresh(
                    cached, self._fetch_discovery, "discovery"
                )
            return cached.value  # type: ignore[no-any-return]

    async def _fetch_jwks(self) -> dict[str, Any]:
        jwt = _import_jwt()
        endpoints = await self._discover()
        doc = await self._get_json(endpoints["jwks_uri"])
        try:
            keyset = jwt.PyJWKSet.from_dict(doc)
        except Exception:
            raise IdpUnavailable() from None
        return {k.key_id: k.key for k in keyset.keys if k.key_id}

    async def _key_for(self, kid: str) -> Any:
        async with self._jwks_lock:
            cached = self._jwks
            if cached is None or _now() - cached.fetched_at >= _CACHE_TTL:
                cached = self._jwks = await self._refresh(cached, self._fetch_jwks, "jwks")
            if kid in cached.value:
                return cached.value[kid]
            last = self._last_forced_jwks
            if last is not None and _now() - last < _FORCED_REFETCH_MIN_INTERVAL:
                raise IdpDenied("unknown_kid")
            self._last_forced_jwks = _now()
            cached = self._jwks = await self._refresh(cached, self._fetch_jwks, "jwks")
            if kid not in cached.value:
                raise IdpDenied("unknown_kid")
            return cached.value[kid]

    async def build_authorize_url(self, state: str, nonce: str, code_challenge: str) -> str:
        endpoint = (await self._discover())["authorization_endpoint"]
        query = urlencode(
            {
                "response_type": "code",
                "response_mode": "query",
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{endpoint}{'&' if '?' in endpoint else '?'}{query}"

    async def exchange_code(self, code: str, code_verifier: str) -> str:
        """Return the ID token only; IdP access/refresh tokens are discarded."""
        client_secret = self._secret_provider()
        if not client_secret:
            raise IdpUnavailable()
        endpoint = (await self._discover())["token_endpoint"]
        status, body = await self._request(
            "POST",
            endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._config.redirect_uri,
                "client_id": self._config.client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        if 400 <= status < 500:
            raise IdpDenied("token_rejected")
        if status != 200:
            raise IdpUnavailable()
        try:
            doc = json.loads(body)
        except ValueError:
            raise IdpUnavailable() from None
        id_token = doc.get("id_token") if isinstance(doc, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise IdpUnavailable()
        return id_token

    async def validate_id_token(self, token: str, nonce: str) -> tuple[str, str | None]:
        """Verify the ID token; return ``(user, label)`` or raise ``IdpDenied``."""
        jwt = _import_jwt()
        cfg = self._config
        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LEN:
            raise IdpDenied("malformed")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise IdpDenied("malformed") from None
        kid = header.get("kid")
        if header.get("alg") != "RS256":
            raise IdpDenied("bad_alg")
        if not isinstance(kid, str) or not kid:
            raise IdpDenied("unknown_kid")
        key = await self._key_for(kid)

        required = ["exp", "iat", "iss", "aud", "sub", "nonce"]
        if cfg.tenant_id:
            required += ["nbf", "tid", "oid"]
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=cfg.client_id,
                issuer=cfg.issuer,
                leeway=_LEEWAY_SECONDS,
                options={"require": required},
            )
        except jwt.ExpiredSignatureError:
            raise IdpDenied("expired") from None
        except jwt.ImmatureSignatureError:
            raise IdpDenied("not_yet_valid") from None
        except jwt.InvalidAudienceError:
            raise IdpDenied("bad_aud") from None
        except jwt.InvalidIssuerError:
            raise IdpDenied("bad_iss") from None
        except jwt.MissingRequiredClaimError:
            raise IdpDenied("missing_claim") from None
        except jwt.InvalidSignatureError:
            raise IdpDenied("bad_signature") from None
        except jwt.PyJWTError:
            raise IdpDenied("invalid_token") from None

        aud = claims.get("aud")
        if isinstance(aud, list) and claims.get("azp") != cfg.client_id:
            raise IdpDenied("bad_azp")
        if "azp" in claims and claims["azp"] != cfg.client_id:
            raise IdpDenied("bad_azp")

        got_nonce = claims.get("nonce")
        if not isinstance(got_nonce, str) or not hmac.compare_digest(
            got_nonce.encode(), nonce.encode()
        ):
            raise IdpDenied("bad_nonce")

        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise IdpDenied("missing_claim")
        if cfg.tenant_id:
            tid, oid = claims.get("tid"), claims.get("oid")
            if not isinstance(tid, str) or not hmac.compare_digest(
                tid.encode(), cfg.tenant_id.encode()
            ):
                raise IdpDenied("bad_tid")
            if not isinstance(oid, str) or not oid:
                raise IdpDenied("missing_claim")
            user = f"{tid}:{oid}"
        else:
            user = sub

        if cfg.required_role:
            roles = claims.get("roles")
            if not isinstance(roles, list) or cfg.required_role not in roles:
                raise IdpDenied("missing_role")
        if cfg.required_group:
            names = claims.get("_claim_names")
            if isinstance(names, dict) and "groups" in names:
                raise IdpDenied("group_overage")
            groups = claims.get("groups")
            if not isinstance(groups, list) or cfg.required_group not in groups:
                raise IdpDenied("missing_group")

        raw_label = claims.get("preferred_username") or claims.get("email")
        label = (
            sanitize_text(raw_label, max_len=_LABEL_MAX_LEN)
            if isinstance(raw_label, str) and raw_label
            else None
        )
        return user, label


def _import_jwt() -> Any:
    import jwt

    return jwt


def _bind(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class FlowState:
    params: dict[str, str]
    code_verifier: str = field(repr=False)
    nonce: str = field(repr=False)
    binding_hash: str = field(repr=False)
    expires_at: float
    source: str = field(default="", repr=False)


@dataclass
class ConsentTicket:
    flow: FlowState
    user: str
    label: str | None
    binding_hash: str = field(repr=False)
    expires_at: float


class IdpFlowStore:
    """Memory-only, bounded-LRU, single-use state for the IdP round trip."""

    def __init__(
        self,
        *,
        max_entries: int = _MAX_FLOWS,
        flow_ttl: float = _FLOW_TTL,
        consent_ttl: float = _CONSENT_TTL,
        per_source_max: int = _MAX_FLOWS_PER_SOURCE,
    ) -> None:
        self._max = max_entries
        self._per_source = max(1, per_source_max)
        self._flow_ttl = flow_ttl
        self._consent_ttl = consent_ttl
        self._flows: OrderedDict[str, FlowState] = OrderedDict()
        self._tickets: OrderedDict[str, ConsentTicket] = OrderedDict()

    def __len__(self) -> int:
        return len(self._flows)

    def _insert(self, table: OrderedDict, entry: Any) -> str:
        key = secrets.token_urlsafe(32)
        table[key] = entry
        while len(table) > self._max:
            table.popitem(last=False)
        return key

    @staticmethod
    def _take(table: OrderedDict, key: str, binding: str) -> Any:
        entry = table.pop(key, None) if isinstance(key, str) and len(key) <= 256 else None
        if entry is None or _now() >= entry.expires_at:
            return None
        if not hmac.compare_digest(entry.binding_hash.encode(), _bind(binding).encode()):
            return None
        return entry

    @staticmethod
    def _source_key(source: str) -> str:
        try:
            addr = ipaddress.ip_address(source)
        except ValueError:
            return source
        if isinstance(addr, ipaddress.IPv6Address):
            if addr.ipv4_mapped is not None:
                return str(addr.ipv4_mapped)
            return str(ipaddress.ip_network(f"{addr}/64", strict=False))
        return str(addr)

    def _evict_for(self, source: str) -> None:
        now = _now()
        for key in [k for k, f in self._flows.items() if now >= f.expires_at]:
            del self._flows[key]
        counts: dict[str, int] = {}
        for flow in self._flows.values():
            counts[flow.source] = counts.get(flow.source, 0) + 1
        own = counts.get(source, 0)
        if own >= self._per_source:
            victim = source
        elif len(self._flows) >= self._max:
            if own == 0:
                raise IdpUnavailable()
            victim = source
        else:
            return
        for key, flow in self._flows.items():
            if flow.source == victim:
                del self._flows[key]
                return

    def put(
        self,
        *,
        params: dict[str, str],
        code_verifier: str,
        nonce: str,
        binding: str,
        source: str = "",
    ) -> str:
        source = self._source_key(source)
        self._evict_for(source)
        return self._insert(
            self._flows,
            FlowState(
                dict(params),
                code_verifier,
                nonce,
                _bind(binding),
                _now() + self._flow_ttl,
                source,
            ),
        )

    def pop(self, state: str, binding: str) -> FlowState | None:
        flow: FlowState | None = self._take(self._flows, state, binding)
        return flow

    def put_consent(
        self, flow: FlowState, *, user: str, label: str | None, binding: str
    ) -> str:
        return self._insert(
            self._tickets,
            ConsentTicket(flow, user, label, _bind(binding), _now() + self._consent_ttl),
        )

    def pop_consent(self, ticket: str, binding: str) -> ConsentTicket | None:
        found: ConsentTicket | None = self._take(self._tickets, ticket, binding)
        return found

    def drop_user(self, user: str) -> int:
        """Drop every pending consent ticket for ``user`` (operator revoke,
        GH-163). Returns how many were dropped."""
        keys = [k for k, t in self._tickets.items() if t.user == user]
        for key in keys:
            self._tickets.pop(key, None)
        return len(keys)
