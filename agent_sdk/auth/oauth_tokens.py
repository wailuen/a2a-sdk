"""OAuth 2.1 token + client store (DESIGN.md §5.5, §6).

The front-door credential layer for the Claude.ai connector chain. Implements
the ``TokenVerifier`` protocol consumed by ``auth/middleware.py`` so OAuth
access tokens resolve through the same identity path as API keys.

Persistence split (DESIGN §6):

- **Client registrations** (RFC 7591 DCR) → ``NS_OAUTH_CLIENTS`` in the
  encrypted store — restarts never wipe Claude.ai connector registrations.
  Bounded at ``MAX_CLIENTS`` with LRU eviction of *never-consented* clients
  only (a consented client is a live connector; evicting it would orphan its
  refresh tokens).
- **Refresh tokens** → ``NS_OAUTH_REFRESH``, sha256-hashed row keys, SINGLE-USE
  rotation: every refresh mints a new access+refresh pair and tombstones the
  presented token (``rotated: true``). Presenting a rotated token again is
  treated as theft and revokes the whole token family (RFC 6749 §10.4).
- **Auth codes and access tokens** → memory only (short-lived, single-process
  invariant per DESIGN §2). Codes are single-use with a ~5 min TTL; access
  tokens live ~1h. Both maps are bounded LRU (no memory-exhaustion vector).

Audience (documented deviation from strict RFC 8707 single-URI matching): the
accepted audience set is EXACTLY ``{issuer origin, {issuer}/mcp}`` — Claude.ai
sends the bare origin as ``resource`` in some flows. Anything outside that
two-value set is a hard reject, never log-and-allow. The real privilege
boundary is kind-based surface assertion (oauth-kind rejected on /admin/*,
/oauth/authorize, key management).

Secrets hygiene: tokens are opaque ``secrets.token_urlsafe`` values, hashed
(sha256) before any map/store access; hash equality where two digests are
compared directly uses ``hmac.compare_digest``. No token value ever reaches a
log or an error body.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from ..credentials.store import NS_OAUTH_CLIENTS, NS_OAUTH_REFRESH, CredentialStore
from ..models.errors import AgentError, ErrorCategory
from .identity import Identity

logger = logging.getLogger(__name__)

CODE_TTL_SECONDS = 5 * 60
ACCESS_TTL_SECONDS = 60 * 60
REFRESH_TTL_SECONDS = 90 * 24 * 60 * 60  # connector-friendly; rotation bounds exposure
MAX_CLIENTS = 200

_MAX_CODES = 1_000
_MAX_ACCESS_TOKENS = 10_000

# RFC 7636: code_verifier is 43-128 chars from the unreserved set; an S256
# code_challenge is exactly 43 unpadded base64url chars.
_VERIFIER_ALPHABET = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> float:
    return time.time()


@dataclass(slots=True)
class _AuthCode:
    client_id: str
    redirect_uri: str
    code_challenge: str
    scope: str
    audience: str
    expires_at: float


@dataclass(slots=True)
class _AccessToken:
    client_id: str
    scope: str
    audience: str
    family_id: str
    label: str | None
    expires_at: float


def verify_pkce_s256(code_verifier: str, code_challenge: str) -> bool:
    """RFC 7636 S256 check — compute base64url(sha256(verifier)) independently,
    then constant-time compare against the separately-sourced challenge."""
    if not (43 <= len(code_verifier) <= 128):
        return False
    if any(ch not in _VERIFIER_ALPHABET for ch in code_verifier):
        return False
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return hmac.compare_digest(expected, code_challenge)


class OAuthTokenStore:
    """Implements ``TokenVerifier`` (auth/middleware.py). Lives at
    ``app.state.oauth``; constructed by build_app() with the PUBLIC_URL-derived
    issuer (DESIGN §10.3 — advertised URLs never derive from Host headers)."""

    def __init__(
        self,
        credential_store: CredentialStore,
        *,
        issuer: str,
        canonical_resource: str,
    ) -> None:
        self._store = credential_store
        self.issuer = issuer.rstrip("/")
        self.canonical_resource = canonical_resource.rstrip("/")
        # The exact two-value audience equivalence set (§5.5).
        self.accepted_audiences = frozenset({self.issuer, self.canonical_resource})
        # Memory-only maps; all methods are synchronous (no await points), so
        # read-decide-mutate sequences are atomic on the single event loop —
        # no locks needed (DESIGN §2 single-process invariant).
        self._codes: OrderedDict[str, _AuthCode] = OrderedDict()
        self._access: OrderedDict[str, _AccessToken] = OrderedDict()

    # ── audience ──

    def validate_audience(self, resource: str | None) -> str | None:
        """Normalize + validate an RFC 8707 resource. None/empty defaults to
        the canonical MCP URI; outside the two-value set → None (reject)."""
        if not resource:
            return self.canonical_resource
        candidate = resource.rstrip("/")
        if candidate in self.accepted_audiences:
            return candidate
        return None

    # ── client registrations (RFC 7591, persisted) ──

    def register_client(
        self, redirect_uris: list[str], *, client_name: str | None = None
    ) -> dict[str, Any]:
        """Persist a public-client registration; returns the stored record.
        Enforces the registration cap with LRU eviction of never-consented
        clients (a flood of junk DCRs can never displace a live connector)."""
        self._evict_clients_if_needed()
        client_id = secrets.token_urlsafe(16)
        record: dict[str, Any] = {
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": list(redirect_uris),
            "token_endpoint_auth_method": "none",
            "consented": False,
            "created_at": _now(),
        }
        self._store.set(NS_OAUTH_CLIENTS, client_id, json.dumps(record))
        logger.info("oauth client registered client_id=%s...", client_id[:8])
        return record

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        raw = self._store.get(NS_OAUTH_CLIENTS, client_id)
        if raw is None:
            return None
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return record if isinstance(record, dict) else None

    def mark_consented(self, client_id: str) -> None:
        """Consent flips the client out of the LRU-evictable pool."""
        record = self.get_client(client_id)
        if record is not None and not record.get("consented"):
            record["consented"] = True
            self._store.set(NS_OAUTH_CLIENTS, client_id, json.dumps(record))

    def _evict_clients_if_needed(self) -> None:
        client_ids = self._store.list_fields(NS_OAUTH_CLIENTS)
        if len(client_ids) < MAX_CLIENTS:
            return
        evictable: list[tuple[float, str]] = []
        for cid in client_ids:
            record = self.get_client(cid)
            if record is None:
                # Corrupt row — unusable, treat as evictable immediately.
                evictable.append((0.0, cid))
            elif not record.get("consented"):
                evictable.append((float(record.get("created_at") or 0.0), cid))
        if not evictable:
            # Every registered client has consent — refuse rather than evict a
            # live connector. Operationally near-impossible at MAX_CLIENTS=200.
            raise AgentError(
                ErrorCategory.RATE_LIMITED, "client registration capacity reached"
            )
        evictable.sort()
        overflow = len(client_ids) - MAX_CLIENTS + 1
        for _, cid in evictable[:overflow]:
            self._store.delete(NS_OAUTH_CLIENTS, cid)
            logger.info("oauth client evicted (never consented) client_id=%s...", cid[:8])

    # ── authorization codes (memory-only, single-use) ──

    def mint_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        scope: str,
        audience: str,
    ) -> str:
        code = secrets.token_urlsafe(32)
        self._codes[_hash(code)] = _AuthCode(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            audience=audience,
            expires_at=_now() + CODE_TTL_SECONDS,
        )
        while len(self._codes) > _MAX_CODES:
            self._codes.popitem(last=False)
        return code

    def consume_code(
        self,
        code: str,
        *,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, Any] | None:
        """Single-use redemption: the code is popped FIRST, so any failure
        (binding mismatch, PKCE) burns it — replay after a failed attempt is
        impossible (OAuth 2.1 single-use guarantee). Returns the code's bound
        metadata on success, None on any failure (route maps to invalid_grant
        without disclosing why)."""
        record = self._codes.pop(_hash(code), None)
        if record is None:
            return None
        if record.expires_at <= _now():
            return None
        if record.client_id != client_id or record.redirect_uri != redirect_uri:
            return None
        if not verify_pkce_s256(code_verifier, record.code_challenge):
            return None
        return {
            "client_id": record.client_id,
            "scope": record.scope,
            "audience": record.audience,
        }

    # ── access tokens (memory-only) + refresh tokens (persisted) ──

    def mint_token_pair(
        self,
        *,
        client_id: str,
        scope: str,
        audience: str,
        label: str | None = None,
        family_id: str | None = None,
    ) -> dict[str, Any]:
        """Mint an access+refresh pair sharing one rotation family. The
        audience travels from the code metadata into both tokens and survives
        every subsequent rotation (§5.5)."""
        family = family_id or secrets.token_urlsafe(16)

        access = secrets.token_urlsafe(32)
        self._prune_access()
        self._access[_hash(access)] = _AccessToken(
            client_id=client_id,
            scope=scope,
            audience=audience,
            family_id=family,
            label=label,
            expires_at=_now() + ACCESS_TTL_SECONDS,
        )
        while len(self._access) > _MAX_ACCESS_TOKENS:
            self._access.popitem(last=False)

        refresh = secrets.token_urlsafe(32)
        self._store.set(
            NS_OAUTH_REFRESH,
            _hash(refresh),
            json.dumps(
                {
                    "client_id": client_id,
                    "scope": scope,
                    "audience": audience,
                    "family_id": family,
                    "label": label,
                    "rotated": False,
                    "created_at": _now(),
                    "expires_at": _now() + REFRESH_TTL_SECONDS,
                }
            ),
        )
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": ACCESS_TTL_SECONDS,
            "scope": scope,
        }

    def _get_refresh(self, token_hash: str) -> dict[str, Any] | None:
        raw = self._store.get(NS_OAUTH_REFRESH, token_hash)
        if raw is None:
            return None
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return record if isinstance(record, dict) else None

    def rotate_refresh(self, refresh_token: str, *, client_id: str) -> dict[str, Any] | None:
        """Single-use rotation. The presented token is tombstoned
        (``rotated: true``, retained until expiry for reuse detection); a new
        pair is minted in the same family. Presenting an already-rotated token
        revokes the entire family — the canonical stolen-token response.
        Synchronous end-to-end, so concurrent redemptions cannot interleave."""
        token_hash = _hash(refresh_token)
        record = self._get_refresh(token_hash)
        if record is None:
            return None
        family_id = str(record.get("family_id") or "")
        if record.get("rotated"):
            # Reuse of a rotated token: someone holds a stale copy. Kill the
            # family so neither the thief nor the victim keeps access.
            logger.warning("oauth refresh reuse detected — revoking token family")
            if family_id:
                self.revoke_family(family_id)
            return None
        if float(record.get("expires_at") or 0.0) <= _now():
            self._store.delete(NS_OAUTH_REFRESH, token_hash)
            return None
        if record.get("client_id") != client_id:
            # Bound-client mismatch — a stolen token must not be redeemable
            # under a different client_id (pitchbook RT-OA-002, kept).
            return None

        record["rotated"] = True
        record["rotated_at"] = _now()
        self._store.set(NS_OAUTH_REFRESH, token_hash, json.dumps(record))
        self._prune_refresh()

        return self.mint_token_pair(
            client_id=str(record.get("client_id") or ""),
            scope=str(record.get("scope") or ""),
            audience=str(record.get("audience") or self.canonical_resource),
            label=record.get("label"),
            family_id=family_id or None,
        )

    def revoke_family(self, family_id: str) -> None:
        """Drop every access + refresh token in a rotation family."""
        for token_hash in list(self._store.list_fields(NS_OAUTH_REFRESH)):
            record = self._get_refresh(token_hash)
            if record is not None and record.get("family_id") == family_id:
                self._store.delete(NS_OAUTH_REFRESH, token_hash)
        for token_hash in [
            h for h, rec in self._access.items() if rec.family_id == family_id
        ]:
            self._access.pop(token_hash, None)

    # ── verification (TokenVerifier protocol) ──

    def verify(self, token: str) -> Identity | None:
        """Resolve an access token to an oauth-kind identity, or None.
        Expiry and audience are both enforced — an out-of-set audience is a
        hard reject even though the mint path validates it (defense in depth,
        never log-and-allow)."""
        record = self._access.get(_hash(token))
        if record is None:
            return None
        if record.expires_at <= _now():
            self._access.pop(_hash(token), None)
            return None
        if record.audience not in self.accepted_audiences:
            logger.warning("oauth access token rejected: audience outside accepted set")
            return None
        return Identity(
            kind="oauth",
            subject=record.client_id,
            admin=False,
            label=record.label or f"oauth:{record.client_id[:8]}",
        )

    # ── revocation (RFC 7009) ──

    def revoke_by_value(self, token: str, *, caller: Identity) -> None:
        """Revoke an access or refresh token by value. oauth-kind callers may
        revoke only tokens minted to their own client_id; api_key identities
        may revoke any. Silent no-op otherwise — RFC 7009 §2.2: the caller
        never learns whether the token existed or who owned it."""

        def _owned(owner_client_id: str) -> bool:
            return caller.kind == "api_key" or owner_client_id == caller.subject

        token_hash = _hash(token)

        access = self._access.get(token_hash)
        if access is not None:
            if _owned(access.client_id):
                self._access.pop(token_hash, None)
                logger.info("oauth access token revoked")
            return

        refresh = self._get_refresh(token_hash)
        if refresh is not None and _owned(str(refresh.get("client_id") or "")):
            # Revoking a refresh token kills its family (RFC 7009 §2.1 SHOULD:
            # related access tokens go with it).
            family_id = str(refresh.get("family_id") or "")
            self._store.delete(NS_OAUTH_REFRESH, token_hash)
            if family_id:
                self.revoke_family(family_id)
            logger.info("oauth refresh token + family revoked")

    # ── housekeeping ──

    def _prune_access(self) -> None:
        now = _now()
        for token_hash in [h for h, rec in self._access.items() if rec.expires_at <= now]:
            self._access.pop(token_hash, None)

    def _prune_refresh(self) -> None:
        """Drop expired refresh rows (including rotation tombstones whose
        reuse-detection value has lapsed). Called on rotation — O(n) over a
        usage-bounded namespace."""
        now = _now()
        for token_hash in list(self._store.list_fields(NS_OAUTH_REFRESH)):
            record = self._get_refresh(token_hash)
            if record is None or float(record.get("expires_at") or 0.0) <= now:
                self._store.delete(NS_OAUTH_REFRESH, token_hash)
