"""OBO token exchange — MSAL on-behalf-of, generalized (DESIGN.md §9).

``OboExchanger`` wraps an MSAL ``ConfidentialClientApplication`` and exchanges an
inbound user-assertion JWT for a delegated downstream access token
(``acquire_token_on_behalf_of``). It is a faithful generalization of the m365
``TokenManager``: the MSAL access-token cache supplies the "cached" half of
DESIGN §9 (repeated exchanges of the same assertion return the cached token
until expiry); ``expiry_buffer_seconds`` (default 300) supplies the buffer — an
assertion within the buffer of its own ``exp`` is refused so the worker re-auths
rather than minting a token that dies mid-flight.

Decoupled from any one credential store: the caller supplies a
``credentials_provider`` (resolved lazily, so missing config surfaces as
``AgentError(AUTH)`` at first use, not at import) and, for tests, an injectable
``app_factory`` so no real MSAL/network is needed. ``msal`` is only imported by
the default factory — importing this module never requires the ``obo`` extra.

**Secrets hygiene (non-negotiable, DESIGN §6 / standing instruction):** the user
assertion and every minted token are NEVER logged or placed in an error/detail.
MSAL ``error_description`` strings can embed assertion fragments for
audience/scope errors, so every description is run through
:func:`_sanitize_msal_desc` before it can reach an ``AgentError.detail``. Only
the granted ``scp`` claim, the MSAL ``error`` code, and the error *category* are
ever logged.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ...models.errors import AgentError, ErrorCategory

logger = logging.getLogger("agent_sdk.contrib.obo")

# Tenant id is interpolated into the authority URL — validate it as a GUID or a
# named tenant (e.g. "contoso.onmicrosoft.com") before use so a malformed store
# value cannot inject path/query/CRLF into the URL. 8–64 chars, must contain at
# least one alphanumeric (rejects dot-only strings).
_TENANT_ID_RE = re.compile(r"^(?=[A-Za-z0-9.\-]*[A-Za-z0-9])[A-Za-z0-9.\-]{8,64}$")

# A JWT-shaped run (three base64url segments). Used to scrub assertion fragments
# out of MSAL error descriptions before they can be logged or returned.
_JWT_SHAPE_RE = re.compile(r"[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")

# MSAL/AAD transient-failure markers — the only errors worth one retry.
_RETRYABLE_SUBSTRINGS = (
    "temporarily_unavailable",
    "service unavailable",
    "timeout",
    "connection",
)

_DEFAULT_EXPIRY_BUFFER_SECONDS = 30  # canonical OBO buffer (DESIGN §9); m365-validated


def _sanitize_msal_desc(desc: str) -> str:
    """Replace any JWT-shaped substring in an MSAL ``error_description`` with a
    placeholder, so an assertion fragment can never escape into a log line or an
    ``AgentError.detail``. The input is capped first: ``_JWT_SHAPE_RE.sub`` is
    super-linear on long no-dot input, and ``error_description`` is not otherwise
    length-bounded (latent ReDoS/CPU-DoS guard)."""
    return _JWT_SHAPE_RE.sub("<redacted-jwt>", desc[:4096])


@dataclass(frozen=True, slots=True, repr=False)
class OboCredentials:
    """Confidential-client credentials for the OBO exchange. ``client_secret`` is
    a value, not a SecretStr — it lives only inside the exchanger and the MSAL
    app, is never logged, and never crosses a wire boundary."""

    tenant_id: str
    client_id: str
    client_secret: str
    authority_host: str = "https://login.microsoftonline.com"

    def __repr__(self) -> str:
        # Structural secrets hygiene: the secret never renders, even if an
        # instance reaches a log line, a debugger, or an exception repr.
        return (
            f"OboCredentials(tenant_id={self.tenant_id!r}, "
            f"client_id={self.client_id!r}, client_secret='[redacted]', "
            f"authority_host={self.authority_host!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class OboToken:
    """Result of an exchange. ``home_account_id`` (``"{oid}.{tid}"``) is a
    NON-secret MSAL cache key safe to persist (e.g. by contrib.commitments) so a
    fresh token can be re-minted later without storing the token itself.

    ``scopes`` is the set REQUESTED; ``granted_scopes`` is the ``scp`` Entra
    actually granted (it may downscope) — check ``granted_scopes`` to know what
    the token can do, not ``scopes``."""

    access_token: str
    home_account_id: str
    scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...] = ()

    def __repr__(self) -> str:
        # The token never renders (DESIGN §6 / "no credentials in logs, ever").
        return (
            f"OboToken(access_token='[redacted]', "
            f"home_account_id={self.home_account_id!r}, scopes={self.scopes!r}, "
            f"granted_scopes={self.granted_scopes!r})"
        )


class _MsalApp(Protocol):
    """The slice of ``msal.ConfidentialClientApplication`` the exchanger uses —
    a Protocol so tests inject a fake without importing msal."""

    def acquire_token_on_behalf_of(
        self, user_assertion: str, scopes: list[str]
    ) -> dict[str, Any]: ...

    def get_accounts(self) -> list[dict[str, Any]]: ...

    def acquire_token_silent(
        self, scopes: list[str], account: dict[str, Any]
    ) -> dict[str, Any] | None: ...


CredentialsProvider = Callable[[], OboCredentials | None]
AppFactory = Callable[[OboCredentials], _MsalApp]


class TokenExpiredError(AgentError):
    """The user assertion is within the expiry buffer of its own ``exp`` — the
    user must re-authenticate. Never retried (a retry cannot un-expire it)."""

    def __init__(self, seconds_remaining: float) -> None:
        super().__init__(
            ErrorCategory.AUTH,
            "user assertion is expiring — re-authentication required",
            source="obo",
        )
        self.seconds_remaining = seconds_remaining


def _default_app_factory(token_cache: Any | None) -> AppFactory:
    """Build the real-MSAL factory. ``msal`` is imported HERE (lazily) so the
    module imports without the ``obo`` extra installed."""

    def _factory(creds: OboCredentials) -> _MsalApp:
        try:
            import msal  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise AgentError(
                ErrorCategory.AUTH,
                "the 'msal' package is required for OBO — install agent-sdk[obo]",
                source="obo",
            ) from exc
        authority = f"{creds.authority_host.rstrip('/')}/{creds.tenant_id}"
        return msal.ConfidentialClientApplication(
            client_id=creds.client_id,
            client_credential=creds.client_secret,
            authority=authority,
            token_cache=token_cache,
        )

    return _factory


class OboExchanger:
    """Holds the MSAL confidential-client app and performs OBO exchanges.

    Parameters
    ----------
    credentials_provider:
        Returns :class:`OboCredentials` or ``None`` (not yet configured).
        Called once, lazily, on first exchange; the built MSAL app is then
        cached for the process lifetime (matching m365 — runtime credential
        rotation requires a new exchanger).
    scopes:
        Delegated scopes to request. Least-privilege is the caller's job.
    expiry_buffer_seconds:
        Refuse an assertion expiring within this many seconds (default 300).
    app_factory:
        Test seam — builds an :class:`_MsalApp` from credentials. Defaults to a
        real ``msal.ConfidentialClientApplication`` (lazy import).
    token_cache:
        Optional MSAL token cache (e.g. a serializable/persistent one) passed to
        the default factory; enables :meth:`token_for_account` re-mint to survive
        restarts. Ignored when ``app_factory`` is supplied.
    expected_audiences:
        Audiences the inbound assertion's ``aud`` claim MUST match before it is
        forwarded to Entra (confused-deputy guard at the AS boundary — a token
        minted for a *different* resource is refused locally, never relayed). If
        omitted, defaults to ``{client_id, "api://{client_id}"}`` (the common v1/v2
        forms). Deployments whose app registration uses a custom App ID URI must
        pass it explicitly. The check reads an UNVERIFIED claim — MSAL remains the
        cryptographic gate; this only prevents relaying a wrong-audience token.
    """

    def __init__(
        self,
        *,
        credentials_provider: CredentialsProvider,
        scopes: list[str],
        expiry_buffer_seconds: int = _DEFAULT_EXPIRY_BUFFER_SECONDS,
        app_factory: AppFactory | None = None,
        token_cache: Any | None = None,
        expected_audiences: list[str] | set[str] | None = None,
    ) -> None:
        if not scopes:
            raise ValueError("scopes must be a non-empty list (request least privilege)")
        self._provider = credentials_provider
        self._scopes = list(scopes)
        self._buffer = max(0, int(expiry_buffer_seconds))
        self._app_factory = app_factory or _default_app_factory(token_cache)
        self._app: _MsalApp | None = None
        self._lock = asyncio.Lock()
        self._configured_audiences: set[str] | None = (
            set(expected_audiences) if expected_audiences else None
        )
        self._audiences: set[str] | None = None  # resolved in _get_app

    @property
    def scopes(self) -> tuple[str, ...]:
        return tuple(self._scopes)

    async def _get_app(self) -> _MsalApp:
        async with self._lock:
            if self._app is not None:
                return self._app
            creds = self._provider()
            if creds is None:
                raise AgentError(
                    ErrorCategory.AUTH,
                    "OBO is not configured — set the Azure tenant/client/secret "
                    "credentials for this agent",
                    source="obo",
                )
            if not _TENANT_ID_RE.fullmatch(creds.tenant_id):
                # Generic message: never echo the offending value.
                raise AgentError(
                    ErrorCategory.AUTH, "invalid Azure tenant id format", source="obo"
                )
            # Resolve the audience allow-list now that we know client_id: an
            # explicit override, else the two common v1/v2 forms for this app.
            self._audiences = self._configured_audiences or {
                creds.client_id,
                f"api://{creds.client_id}",
            }
            self._app = self._app_factory(creds)
            return self._app

    def _check_audience(self, assertion: str) -> None:
        """Confused-deputy guard at the AS boundary: refuse — *before* relaying to
        Entra — an assertion whose ``aud`` is not one this app expects. The claim
        is UNVERIFIED (MSAL is still the cryptographic gate); this only stops us
        from forwarding a token minted for a different resource. ``aud`` may be a
        string or a list. A missing ``aud`` is left for MSAL to reject (we do not
        invent one). Generic message — never echoes the offending audience."""
        if not self._audiences:
            return
        payload = _decode_jwt_payload(assertion)
        aud = payload.get("aud")
        if aud is None:
            return
        auds = {aud} if isinstance(aud, str) else set(aud) if isinstance(aud, list) else set()
        if not (auds & self._audiences):
            logger.warning("obo: assertion audience not accepted (refused before MSAL)")
            raise AgentError(
                ErrorCategory.AUTH,
                "user assertion audience is not accepted by this agent",
                source="obo",
            )

    async def _call_msal(self, fn: Callable[[], Any]) -> Any:
        """Run a (blocking) MSAL call in the default executor, converting any
        *exception* it raises into a generic ``AgentError(AUTH)`` so an MSAL
        stack trace — which can embed the assertion or secret — never propagates.
        MSAL's own error *dicts* (``{"error": ...}``) are not exceptions and are
        handled by the callers, which sanitize the description."""
        try:
            return await asyncio.get_running_loop().run_in_executor(None, fn)
        except Exception:
            # Suppress the original: its message/stack may carry the assertion or
            # the client secret. Only the category is recorded.
            logger.warning("obo: MSAL call raised (suppressed)")
            err = AgentError(
                ErrorCategory.AUTH, "OBO token exchange failed", source="obo"
            )
        # Raise OUTSIDE the except block, on purpose: raising inside it would chain
        # the original MSAL exception onto __context__ (whose message can embed the
        # assertion or client secret), and `from None` only sets __suppress_context__
        # — it does not clear __context__, so a serializer that walks the chain would
        # still surface it. Out here there is no active exception to chain.
        raise err

    def _check_assertion_expiry(self, assertion: str) -> None:
        """Raise :class:`TokenExpiredError` if the assertion expires within the
        buffer. A missing/unparseable ``exp`` is left for MSAL to judge (we do
        not invent an expiry)."""
        payload = _decode_jwt_payload(assertion)
        exp = payload.get("exp")
        if exp is None:
            return
        try:
            exp_f = float(exp)
        except (TypeError, ValueError):
            return
        if not math.isfinite(exp_f):
            # NaN/±inf exp is not a usable expiry — treat as already expired
            # rather than letting NaN comparisons silently pass the buffer check.
            raise TokenExpiredError(seconds_remaining=0.0)
        remaining = exp_f - time.time()
        if remaining <= self._buffer:
            raise TokenExpiredError(seconds_remaining=max(remaining, 0.0))

    async def exchange(self, assertion: str) -> OboToken:
        """Exchange a user-assertion JWT for a delegated token. Raises
        ``AgentError(AUTH)`` on any failure; ``TokenExpiredError`` if the
        assertion is within the expiry buffer. Logs only the granted ``scp``."""
        if not assertion:
            raise AgentError(
                ErrorCategory.AUTH, "no user assertion to exchange", source="obo"
            )
        self._check_assertion_expiry(assertion)
        app = await self._get_app()
        self._check_audience(assertion)  # refuse wrong-audience BEFORE relaying
        result = await self._call_msal(
            lambda: app.acquire_token_on_behalf_of(
                user_assertion=assertion, scopes=self._scopes
            )
        )
        if not isinstance(result, dict) or "access_token" not in result:
            error = (result or {}).get("error", "unknown") if isinstance(result, dict) else "unknown"
            desc = (result or {}).get("error_description", "") if isinstance(result, dict) else ""
            # error_description may carry an assertion fragment → sanitize.
            logger.warning("obo: exchange failed error=%s", error)
            raise AgentError(
                ErrorCategory.AUTH,
                "OBO token exchange failed",
                source="obo",
                detail={"error": str(error), "error_description": _sanitize_msal_desc(str(desc))},
            )
        token = result["access_token"]
        home_account_id = _home_account_id(token)
        granted = _granted_scp(token)
        logger.info("obo: granted scp=%s", granted)
        return OboToken(
            access_token=token,
            home_account_id=home_account_id,
            scopes=tuple(self._scopes),
            granted_scopes=tuple(granted.split()) if granted else (),
        )

    async def exchange_with_retry(self, assertion: str) -> OboToken:
        """:meth:`exchange` with one transient retry (2s backoff).
        ``TokenExpiredError`` is never retried."""
        last: AgentError | None = None
        for attempt in range(2):
            try:
                return await self.exchange(assertion)
            except TokenExpiredError:
                raise
            except AgentError as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                blob = (
                    str(detail.get("error", "")) + " " + str(detail.get("error_description", ""))
                ).lower()
                if any(s in blob for s in _RETRYABLE_SUBSTRINGS):
                    last = exc
                    if attempt == 0:
                        await asyncio.sleep(2.0)
                    continue
                raise
        assert last is not None  # loop only continues on a retryable AgentError
        raise last

    async def token_for_account(self, home_account_id: str) -> str:
        """Silently re-mint a token for a cached account (no fresh assertion) —
        used by durable executors (contrib.commitments) at fire time. Requires a
        persistent ``token_cache`` to survive restarts. Raises ``AgentError(AUTH)``
        if no cached account/refresh token is available.

        **Caller's identity-binding contract (SECURITY — this method cannot
        enforce it):** ``home_account_id`` is a bearer-grade capability. Anyone
        who can name a cached account can mint a delegated token *for that user*
        with no fresh assertion. A durable executor MUST bind the
        ``home_account_id`` to the task's authenticated identity at task-creation
        time and re-verify that binding at fire time, so a task created by user A
        can never re-mint a token for user B. ``OboExchanger`` is given only an
        opaque id and has no way to know whose task is calling — passing an
        unvalidated/attacker-influenced ``home_account_id`` here is a
        privilege-escalation bug in the caller."""
        app = await self._get_app()
        accounts = await self._call_msal(app.get_accounts)
        account = next(
            (a for a in accounts if a.get("home_account_id") == home_account_id), None
        )
        if account is None:
            raise AgentError(
                ErrorCategory.AUTH,
                "no cached account for re-mint — the user must re-authenticate",
                source="obo",
            )
        result = await self._call_msal(
            lambda: app.acquire_token_silent(scopes=self._scopes, account=account)
        )
        if not isinstance(result, dict) or "access_token" not in result:
            raise AgentError(
                ErrorCategory.AUTH,
                "silent token re-mint failed — the user must re-authenticate",
                source="obo",
            )
        return result["access_token"]


# ── module-level JWT helpers (no verification — claims read for non-secret use) ──


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Best-effort decode of a JWT payload segment. Returns ``{}`` on any error.
    No signature verification — the IdP/MSAL verifies; we read only non-secret
    claims (exp/scp/oid/tid)."""
    try:
        parts = token.split(".")
        if len(parts) < 2 or not parts[1]:
            return {}
        segment = parts[1]
        padded = segment + "=" * (-len(segment) % 4)
        obj = json.loads(base64.urlsafe_b64decode(padded))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _granted_scp(access_token: str) -> str:
    """The space-separated ``scp`` claim, for operator visibility. Returned as-is
    (it is a scope list, not an error string — do NOT sanitize, or scope names
    with three dotted segments would be clobbered)."""
    scp = _decode_jwt_payload(access_token).get("scp", "")
    return scp if isinstance(scp, str) else ""


def _home_account_id(access_token: str) -> str:
    """``"{oid}.{tid}"`` MSAL cache key, or ``""`` when oid/tid are absent. A
    non-secret identifier (not a token) — safe to persist."""
    payload = _decode_jwt_payload(access_token)
    oid = payload.get("oid", "")
    tid = payload.get("tid", "")
    return f"{oid}.{tid}" if oid and tid else ""


__all__ = [
    "OboExchanger",
    "OboCredentials",
    "OboToken",
    "TokenExpiredError",
]
