"""Graph subscription management — create / renew / reauthorize / delete (§9).

EXPERIMENTAL (DESIGN §4.0).

A Graph subscription is the *outbound* half of webhooks: it tells Graph where to
POST notifications, for which resource and change types, until an expiry you must
keep renewing. This module is the hardened generalization of the m365 reference's
``manage_subscription`` tool:

- :class:`SubscriptionStore` — durable SQLite record of every live subscription
  (house style: one stdlib ``sqlite3`` connection + ``threading.Lock``), so a
  background renewer knows what to keep alive across restarts. It NEVER persists
  the ``clientState`` secret — only a non-secret *reference label*; the secret
  lives in settings and is resolved at compare time by the dispatcher.
- :class:`GraphSubscriptionManager` — create / renew / reauthorize / delete via a
  duck-typed Graph poster (``graph_request(method, path, **kwargs)`` — satisfied
  by :class:`~agent_sdk.contrib.obo.source.GraphSource`, host-pinned to
  graph.microsoft.com). Every input is validated (https-only ``notificationUrl``,
  ``changeType`` enum, GUID id, sanitized ``resource``) with *generic* errors
  that never echo the offending value, and the ``clientState`` secret is never
  logged or placed in an error.
- :func:`webhooks_renewal_lifespan` — an optional background poller that renews
  subscriptions before they expire (the renewal loop the reference lacked).

**SECURITY — background auth.** Renewal/reauthorize run with NO request context,
so the manager they use must be backed by a Graph poster that authenticates with
*application* credentials, not a per-request delegated (OBO) token (which needs an
inbound user assertion that does not exist in the background). Wire the renewer
with an app-cred poster; use the delegated :class:`GraphSource` only for
create/delete done inside a request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import threading
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, List

from ...common.iso8601 import iso_utc
from ...models.errors import AgentError, ErrorCategory
from .backend import SubscriptionBackend

if TYPE_CHECKING:  # avoid importing FastAPI at module import
    from fastapi import FastAPI

logger = logging.getLogger("agent_sdk.contrib.webhooks")

VALID_CHANGE_TYPES = frozenset({"created", "updated", "deleted"})
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_MAX_RESOURCE_LEN = 1024
_MAX_URL_LEN = 2048
_MAX_EXTRA_BYTES = 16 * 1024


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return iso_utc(dt)


# ── input validation (generic errors; never echo the offending value) ──
def validate_guid(value: str, label: str = "subscription_id") -> str:
    if not isinstance(value, str) or not _GUID_RE.match(value):
        raise AgentError(ErrorCategory.VALIDATION, f"{label} must be a GUID")
    return value


def validate_change_type(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise AgentError(ErrorCategory.VALIDATION, "changeType is required")
    parts = [p.strip() for p in value.split(",")]
    if not all(p in VALID_CHANGE_TYPES for p in parts) or not parts:
        raise AgentError(
            ErrorCategory.VALIDATION,
            "changeType must be a comma-separated subset of "
            "created/updated/deleted",
        )
    return ",".join(parts)


def validate_resource(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentError(ErrorCategory.VALIDATION, "resource is required")
    if len(value) > _MAX_RESOURCE_LEN:
        raise AgentError(ErrorCategory.VALIDATION, "resource is too long")
    # A resource is a Graph path (e.g. users/{id}/messages); reject control
    # chars / newlines (header-/log-injection) and absolute URLs (SSRF intent).
    if any(ord(c) < 0x20 for c in value):
        raise AgentError(ErrorCategory.VALIDATION, "resource contains control chars")
    if "://" in value:
        raise AgentError(ErrorCategory.VALIDATION, "resource must be a Graph path")
    return value.strip()


# The prescribed reaction to each lifecycle event (Graph guidance). Surfaced
# here so an integrator wiring a "*" handler sees that a bare 202 is NOT enough
# for subscriptionRemoved / missed — both require a resync to avoid silent loss.
LIFECYCLE_ACTIONS = {
    "reauthorizationRequired": "reauthorize+renew via PATCH /subscriptions/{id} "
    "(expirationDateTime) — do NOT also POST /reauthorize within 10 min",
    "subscriptionRemoved": "recreate the subscription, then delta-resync the "
    "resource to recover changes missed while it was gone",
    "missed": "full delta-resync the resource — notifications were dropped",
}


def recommended_action(lifecycle_event: str) -> str | None:
    """The prescribed reaction to a Graph ``lifecycleEvent`` (or None if
    unknown). A ``subscriptionRemoved`` / ``missed`` handler that merely acks is
    non-conformant — it must resync or it silently loses data."""
    return LIFECYCLE_ACTIONS.get(lifecycle_event)


def validate_notification_url(value: str, label: str = "notificationUrl") -> str:
    from urllib.parse import urlparse

    if not isinstance(value, str) or not value:
        raise AgentError(ErrorCategory.VALIDATION, f"{label} is required")
    if len(value) > _MAX_URL_LEN:
        raise AgentError(ErrorCategory.VALIDATION, f"{label} is too long")
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise AgentError(ErrorCategory.VALIDATION, f"{label} must be https")
    if not parsed.hostname:
        raise AgentError(ErrorCategory.VALIDATION, f"{label} has no host")
    if parsed.username or parsed.password:
        # Credentials embedded in the URL would be persisted/sent — refuse.
        raise AgentError(ErrorCategory.VALIDATION, f"{label} must not embed credentials")
    return value


_DDL = """
CREATE TABLE IF NOT EXISTS webhook_subscriptions(
    id                TEXT PRIMARY KEY,
    resource          TEXT NOT NULL,
    change_type       TEXT NOT NULL,
    notification_url  TEXT NOT NULL,
    lifecycle_url     TEXT,
    expiration        TEXT NOT NULL,
    client_state_ref  TEXT NOT NULL DEFAULT 'default',
    created_at        TEXT NOT NULL,
    extra_json        TEXT NOT NULL DEFAULT '{}'
)
"""
_DDL_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_webhook_subs_expiration "
    "ON webhook_subscriptions(expiration)"
)


class SubscriptionStore(SubscriptionBackend):
    """SQLite record of live Graph subscriptions (house style). No secrets stored."""

    def __init__(self, db_path: str | Path = "webhook_subscriptions.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._closed = False

    def initialize(self) -> None:
        self._ensure_open()
        with self._lock:
            self._conn.execute(_DDL)
            self._conn.execute(_DDL_IDX)
            self._conn.commit()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("subscription store is closed")

    def upsert(
        self,
        *,
        id: str,
        resource: str,
        change_type: str,
        notification_url: str,
        expiration: str,
        lifecycle_url: str | None = None,
        client_state_ref: str = "default",
        extra: dict[str, Any] | None = None,
    ) -> None:
        extra_json = json.dumps(extra or {})
        if len(extra_json.encode("utf-8")) > _MAX_EXTRA_BYTES:
            raise AgentError(ErrorCategory.VALIDATION, "extra exceeds size limit")
        self._ensure_open()
        with self._lock:
            self._conn.execute(
                "INSERT INTO webhook_subscriptions"
                " (id, resource, change_type, notification_url, lifecycle_url,"
                "  expiration, client_state_ref, created_at, extra_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                "  resource=excluded.resource, change_type=excluded.change_type,"
                "  notification_url=excluded.notification_url,"
                "  lifecycle_url=excluded.lifecycle_url,"
                "  expiration=excluded.expiration,"
                "  client_state_ref=excluded.client_state_ref,"
                "  extra_json=excluded.extra_json",
                (
                    id,
                    resource,
                    change_type,
                    notification_url,
                    lifecycle_url,
                    expiration,
                    client_state_ref,
                    _iso(_utcnow()),
                    extra_json,
                ),
            )
            self._conn.commit()

    def set_expiration(self, id: str, expiration: str) -> bool:
        self._ensure_open()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE webhook_subscriptions SET expiration = ? WHERE id = ?",
                (expiration, id),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def delete(self, id: str) -> None:
        self._ensure_open()
        with self._lock:
            self._conn.execute(
                "DELETE FROM webhook_subscriptions WHERE id = ?", (id,)
            )
            self._conn.commit()

    def get(self, id: str) -> dict[str, Any] | None:
        self._ensure_open()
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM webhook_subscriptions WHERE id = ?", (id,)
            )
            row = cur.fetchone()
        return self._row(row) if row is not None else None

    def list(self) -> list[dict[str, Any]]:
        self._ensure_open()
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM webhook_subscriptions ORDER BY expiration"
            )
            rows = cur.fetchall()
        return [self._row(r) for r in rows]

    def due_for_renewal(self, before_iso: str) -> List[dict[str, Any]]:
        """Subscriptions expiring at or before ``before_iso`` (canonical UTC)."""
        self._ensure_open()
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM webhook_subscriptions WHERE expiration <= ?"
                " ORDER BY expiration",
                (before_iso,),
            )
            rows = cur.fetchall()
        return [self._row(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        try:
            d["extra"] = json.loads(d.pop("extra_json", "{}") or "{}")
        except ValueError:
            d["extra"] = {}
        return d


# Duck-typed Graph poster: anything with this method (e.g. GraphSource).
GraphPoster = Any


class GraphSubscriptionManager:
    """Create / renew / reauthorize / delete Graph subscriptions.

    ``graph`` is any object exposing ``async graph_request(method, path, **kwargs)``
    returning an httpx-style response (host-pinned to graph.microsoft.com upstream).
    ``client_state`` is the shared secret sent to Graph at creation and echoed back
    in every notification — it is NEVER persisted or logged. ``client_state_ref``
    is the non-secret label recorded with the subscription so a multi-secret
    deployment can map a subscription back to which secret validates it.
    """

    def __init__(
        self,
        graph: GraphPoster,
        store: SubscriptionBackend,
        *,
        client_state: str,
        client_state_ref: str = "default",
    ) -> None:
        if not client_state:
            raise ValueError("client_state secret is required")
        self._graph = graph
        self._store = store
        self._client_state = client_state
        self._client_state_ref = client_state_ref

    async def create(
        self,
        *,
        resource: str,
        change_type: str,
        notification_url: str,
        expiration: str | datetime,
        lifecycle_url: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resource = validate_resource(resource)
        change_type = validate_change_type(change_type)
        notification_url = validate_notification_url(notification_url)
        if lifecycle_url is not None:
            lifecycle_url = validate_notification_url(lifecycle_url, "lifecycleNotificationUrl")
        exp_iso = _coerce_expiration(expiration)
        body = {
            "changeType": change_type,
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": exp_iso,
            "clientState": self._client_state,  # secret — never logged
        }
        if lifecycle_url is not None:
            body["lifecycleNotificationUrl"] = lifecycle_url
        resp = await self._graph.graph_request("POST", "subscriptions", json=body)
        created = _json_or_empty(resp)
        sub_id = created.get("id")
        if not isinstance(sub_id, str) or not sub_id:
            raise AgentError(
                ErrorCategory.UPSTREAM, "Graph returned a subscription with no id"
            )
        self._store.upsert(
            id=sub_id,
            resource=resource,
            change_type=change_type,
            notification_url=notification_url,
            lifecycle_url=lifecycle_url,
            expiration=created.get("expirationDateTime", exp_iso),
            client_state_ref=self._client_state_ref,
            extra=extra,
        )
        logger.info("webhooks: subscription created sub=%s changeType=%s", sub_id, change_type)
        return created

    async def renew(
        self, subscription_id: str, expiration: str | datetime
    ) -> dict[str, Any]:
        """PATCH a new ``expirationDateTime`` — also re-authorizes the
        subscription in one call (Graph's preferred reauthorize+renew path)."""
        validate_guid(subscription_id)
        exp_iso = _coerce_expiration(expiration)
        resp = await self._graph.graph_request(
            "PATCH",
            f"subscriptions/{subscription_id}",
            json={"expirationDateTime": exp_iso},
        )
        updated = _json_or_empty(resp)
        self._store.set_expiration(
            subscription_id, updated.get("expirationDateTime", exp_iso)
        )
        logger.info("webhooks: subscription renewed sub=%s", subscription_id)
        return updated

    async def reauthorize(self, subscription_id: str) -> None:
        """POST /subscriptions/{id}/reauthorize (no renewal). Prefer
        :meth:`renew` which reauthorizes *and* extends in a single call; do not
        call both within 10 minutes (Graph rejects the redundant reauthorize)."""
        validate_guid(subscription_id)
        await self._graph.graph_request(
            "POST", f"subscriptions/{subscription_id}/reauthorize"
        )
        logger.info("webhooks: subscription reauthorized sub=%s", subscription_id)

    async def delete(self, subscription_id: str) -> None:
        validate_guid(subscription_id)
        await self._graph.graph_request(
            "DELETE", f"subscriptions/{subscription_id}"
        )
        self._store.delete(subscription_id)
        logger.info("webhooks: subscription deleted sub=%s", subscription_id)


def _coerce_expiration(expiration: str | datetime) -> str:
    if isinstance(expiration, datetime):
        dt = expiration
    elif isinstance(expiration, str) and expiration:
        try:
            dt = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
        except ValueError:
            # `from None`: the chained ValueError embeds the raw input
            # ("Invalid isoformat string: '<value>'"); suppress it so a caller
            # that logs the traceback cannot leak the offending value.
            raise AgentError(
                ErrorCategory.VALIDATION, "expiration must be an ISO 8601 instant"
            ) from None
    else:
        raise AgentError(ErrorCategory.VALIDATION, "expiration is required")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt <= _utcnow():
        raise AgentError(ErrorCategory.VALIDATION, "expiration must be in the future")
    return _iso(dt)


def _json_or_empty(resp: Any) -> dict[str, Any]:
    """Decode a Graph JSON body, tolerating an empty (e.g. 204) response."""
    body = getattr(resp, "content", b"") or b""
    if not body:
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def webhooks_renewal_lifespan(
    manager: GraphSubscriptionManager,
    *,
    poll_interval: float = 3600.0,
    renew_before_seconds: int = 24 * 3600,
    renew_window_seconds: int = 3 * 24 * 3600,
    max_per_tick: int = 100,
) -> Callable[["FastAPI"], AbstractAsyncContextManager[None]]:
    """Background poller that renews subscriptions before they expire.

    Every ``poll_interval`` seconds it renews up to ``max_per_tick`` subscriptions
    expiring within ``renew_before_seconds``, extending each by
    ``renew_window_seconds`` from now. Per-subscription failures are isolated and
    logged by type (never the body); a tick error never kills the poller. The
    ``max_per_tick`` bound caps Graph fan-out under a large backlog (the rest are
    picked up on the next tick); the task is cancelled on shutdown.

    The ``manager`` MUST be backed by an application-credential Graph poster —
    renewal runs with no request context, so a delegated/OBO poster (which needs
    an inbound user assertion) would fail every tick. See the module docstring.
    """
    per_tick = max(1, int(max_per_tick))

    @asynccontextmanager
    async def _lifespan(app: "FastAPI") -> AsyncIterator[None]:
        async def _run() -> None:
            try:
                while True:
                    await asyncio.sleep(poll_interval)
                    try:
                        await _renew_due()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # a tick must never kill the loop
                        logger.error(
                            "webhooks renewal tick error_type=%s", type(exc).__name__
                        )
            except asyncio.CancelledError:
                return

        async def _renew_due() -> None:
            cutoff = _iso(_utcnow() + timedelta(seconds=renew_before_seconds))
            new_exp = _utcnow() + timedelta(seconds=renew_window_seconds)
            for sub in manager._store.due_for_renewal(cutoff)[:per_tick]:
                try:
                    await manager.renew(sub["id"], new_exp)
                except Exception as exc:
                    logger.error(
                        "webhooks renewal error_type=%s sub=%s",
                        type(exc).__name__,
                        sub.get("id", "?"),
                    )

        task = asyncio.create_task(_run(), name="webhook-renewal")
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except BaseException:
                pass

    return _lifespan


__all__ = [
    "SubscriptionStore",
    "GraphSubscriptionManager",
    "webhooks_renewal_lifespan",
    "validate_guid",
    "validate_change_type",
    "validate_resource",
    "validate_notification_url",
    "recommended_action",
    "LIFECYCLE_ACTIONS",
    "VALID_CHANGE_TYPES",
]
