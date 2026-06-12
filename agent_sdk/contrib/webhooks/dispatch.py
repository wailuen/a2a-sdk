"""WebhookDispatcher — transport-agnostic Graph notification routing (DESIGN §9).

EXPERIMENTAL (DESIGN §4.0).

The dispatcher is the security boundary between an *unauthenticated* inbound
webhook and your handlers. It owns four jobs, in order, for every notification:

1. **clientState validation (constant-time, fail-closed).** Graph echoes the
   ``clientState`` secret you set at subscription time. A notification whose
   ``clientState`` does not match — compared with :func:`hmac.compare_digest`, so
   a mismatch leaks no timing — is dropped. With no expected secret configured
   and ``require_client_state=True`` (the default) *every* notification is
   dropped: fail closed, never fail open. The secret value is never logged.
2. **Replay de-duplication.** Graph retries undelivered notifications for up to
   4 hours and may redeliver; each change notification carries a stable ``id``.
   A bounded in-process LRU *claims* a key before dispatch so a side-effecting
   handler is not re-run for the same event — and *releases* the claim if the
   handler fails, so a later re-delivery is retried rather than dropped as a
   duplicate of a failed attempt. Pass ``seen=`` for durable cross-restart dedup
   (that hook owns its own retry policy — see :meth:`_release`).
3. **Routing.** Change notifications go to a *named* handler chosen by a
   ``route`` callback (default: ``"default"``). Lifecycle notifications go to a
   handler registered for their ``lifecycleEvent`` (or a ``"*"`` catch-all).
4. **Isolated invocation.** A handler that raises never breaks the batch or the
   202 response — the error is logged by exception *type* only (no message, no
   args, no clientState), and the next notification still runs.

**Why the response path stays fast.** Graph drops a subscription that is "slow"
(>3 s to respond). :meth:`schedule` hands the batch to a tracked background task
and returns immediately so the HTTP layer can answer 202 within budget; handler
latency never delays the response. ``max_in_flight`` bounds concurrent batches
(backpressure: an over-cap batch is dropped and Graph re-delivers it later).

**Lifecycle notifications are not de-duplicated** — ``reauthorizationRequired``
/ ``missed`` can legitimately repeat, and acting on each is the safe default; a
handler that must not double-act (e.g. avoid two reauthorize calls inside 10
minutes, per Graph) owns that idempotency itself.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .models import (
    ChangeNotification,
    LifecycleNotification,
    parse_batch,
)

logger = logging.getLogger("agent_sdk.contrib.webhooks")

ChangeHandler = Callable[[ChangeNotification], Awaitable[None]]
LifecycleHandler = Callable[[LifecycleNotification], Awaitable[None]]
# (source_name unused) resolver: subscription_id -> expected clientState | None
ClientStateResolver = Callable[[str], str | None]
# returns True if the key was ALREADY seen (and records it) — durable dedup hook
SeenPredicate = Callable[[str], Awaitable[bool]]

LIFECYCLE_WILDCARD = "*"


@dataclass
class DispatchReport:
    """Per-batch outcome counts (for tests / metrics; never carries payloads)."""

    changes_dispatched: int = 0
    changes_dropped: int = 0  # bad clientState, duplicate, or no handler
    lifecycles_dispatched: int = 0
    lifecycles_dropped: int = 0
    handler_errors: int = 0
    skipped: int = 0  # malformed entries
    truncated: int = 0  # entries past max_items


class WebhookDispatcher:
    def __init__(
        self,
        *,
        expected_client_state: str | ClientStateResolver | None = None,
        require_client_state: bool = True,
        route: Callable[[ChangeNotification], str | None] | None = None,
        seen: SeenPredicate | None = None,
        max_in_flight: int = 256,
        max_seen: int = 10_000,
        max_items: int = 256,
    ) -> None:
        self._expected = expected_client_state
        self._require_client_state = require_client_state
        self._route = route or (lambda _n: "default")
        self._change_handlers: dict[str, ChangeHandler] = {}
        self._lifecycle_handlers: dict[str, LifecycleHandler] = {}
        self._seen = seen
        self._max_in_flight = max(1, int(max_in_flight))
        self._max_seen = max(1, int(max_seen))
        self._max_items = max(1, int(max_items))
        self._seen_keys: "OrderedDict[str, None]" = OrderedDict()
        self._seen_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()

    # ── registration ──
    def on(self, name: str, handler: ChangeHandler) -> "WebhookDispatcher":
        """Register a named change-notification handler. Returns self (chainable)."""
        if not name:
            raise ValueError("handler name must be non-empty")
        self._change_handlers[name] = handler
        return self

    def on_lifecycle(
        self, event: str, handler: LifecycleHandler
    ) -> "WebhookDispatcher":
        """Register a lifecycle handler for one ``lifecycleEvent`` (or ``"*"``)."""
        if not event:
            raise ValueError("lifecycle event must be non-empty")
        self._lifecycle_handlers[event] = handler
        return self

    # ── 202-fast scheduling ──
    def schedule(self, payload: Any) -> bool:
        """Hand a parsed-or-raw POST body to a tracked background task and return
        immediately (so the HTTP layer can answer 202 within Graph's 3 s budget).

        Returns ``False`` without scheduling when ``max_in_flight`` is reached —
        backpressure; Graph re-delivers the dropped batch on its retry schedule.
        """
        if len(self._tasks) >= self._max_in_flight:
            logger.warning(
                "webhooks: max_in_flight=%d reached; shedding batch (will be "
                "re-delivered by Graph retry)",
                self._max_in_flight,
            )
            return False
        task = asyncio.create_task(self._run(payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _run(self, payload: Any) -> None:
        try:
            await self.handle_payload(payload)
        except Exception as exc:  # a scheduled batch must never crash the loop
            logger.error("webhooks dispatch error_type=%s", type(exc).__name__)

    async def aclose(self) -> None:
        """Await in-flight batch tasks (graceful shutdown). Idempotent."""
        if not self._tasks:
            return
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ── core processing (awaitable; deterministic for tests) ──
    async def handle_payload(self, payload: Any) -> DispatchReport:
        """Validate, de-dup, route and invoke every notification in one POST body.

        Never raises: a malformed body yields an empty report, a bad-clientState
        or duplicate notification is dropped, and a handler exception is caught
        and counted. The caller has already (or will) answer Graph 202.
        """
        batch = parse_batch(payload, max_items=self._max_items)
        report = DispatchReport(skipped=batch.skipped, truncated=batch.truncated)

        # One malformed/hostile item must never abort the rest of the batch
        # (e.g. a non-ASCII clientState that once raised in the compare path).
        for note in batch.changes:
            try:
                await self._handle_change(note, report)
            except Exception as exc:
                report.changes_dropped += 1
                logger.error("webhooks change error_type=%s", type(exc).__name__)

        for life in batch.lifecycles:
            try:
                await self._handle_lifecycle(life, report)
            except Exception as exc:
                report.lifecycles_dropped += 1
                logger.error("webhooks lifecycle error_type=%s", type(exc).__name__)

        return report

    # ── per-notification handling ──
    async def _handle_change(
        self, note: ChangeNotification, report: DispatchReport
    ) -> None:
        if not self._client_state_ok(note.subscription_id, note.client_state):
            report.changes_dropped += 1
            # %r so an attacker-supplied subscriptionId cannot inject log lines.
            logger.warning(
                "webhooks: clientState mismatch sub=%r (dropped)", note.subscription_id
            )
            return
        if not await self._claim(note.dedup_key):
            report.changes_dropped += 1  # duplicate (already seen this run)
            return
        handler = self._resolve_change_handler(note)
        processed = handler is not None and await self._invoke(handler, note, report)
        if processed:
            report.changes_dispatched += 1
        else:
            # No handler, or the handler raised: we did NOT process it. Release
            # the dedup claim so a later Graph re-delivery (at-least-once) can be
            # retried rather than dropped as a duplicate of a failed attempt.
            report.changes_dropped += 1
            await self._release(note.dedup_key)

    async def _handle_lifecycle(
        self, life: LifecycleNotification, report: DispatchReport
    ) -> None:
        if not self._client_state_ok(life.subscription_id, life.client_state):
            report.lifecycles_dropped += 1
            logger.warning(
                "webhooks: lifecycle clientState mismatch sub=%r (dropped)",
                life.subscription_id,
            )
            return
        handler = self._lifecycle_handlers.get(
            life.lifecycle_event
        ) or self._lifecycle_handlers.get(LIFECYCLE_WILDCARD)
        if handler is None:
            report.lifecycles_dropped += 1
            logger.warning(
                "webhooks: no handler for lifecycleEvent=%r sub=%r (dropped)",
                life.lifecycle_event,
                life.subscription_id,
            )
            return
        if await self._invoke(handler, life, report):
            report.lifecycles_dispatched += 1
        else:
            report.lifecycles_dropped += 1

    # ── helpers ──
    def _resolve_change_handler(self, note: ChangeNotification) -> ChangeHandler | None:
        try:
            name = self._route(note)
        except Exception as exc:  # a buggy router must not crash the batch
            logger.error("webhooks route error_type=%s", type(exc).__name__)
            return None
        if not name:
            return None
        handler = self._change_handlers.get(name)
        if handler is None:
            logger.warning(
                "webhooks: no handler named %r for sub=%r (dropped)",
                name,
                note.subscription_id,
            )
        return handler

    async def _invoke(
        self,
        handler: Callable[[Any], Awaitable[None]],
        note: Any,
        report: DispatchReport,
    ) -> bool:
        try:
            await handler(note)
            return True
        except Exception as exc:
            # Never log the message/args — only the exception type.
            report.handler_errors += 1
            logger.error(
                "webhooks handler error_type=%s sub=%r",
                type(exc).__name__,
                getattr(note, "subscription_id", "?"),
            )
            return False

    def _client_state_ok(self, subscription_id: str, actual: str | None) -> bool:
        """Constant-time clientState check, fail-closed (DESIGN §9 hardening)."""
        if callable(self._expected):
            try:
                expected = self._expected(subscription_id)
            except Exception as exc:
                logger.error(
                    "webhooks clientState resolver error_type=%s",
                    type(exc).__name__,
                )
                return False
        else:
            expected = self._expected
        if not expected:
            # No secret to compare against. Default fails closed; an integrator
            # who *explicitly* opts out (dev only) accepts unauthenticated input.
            return not self._require_client_state
        # Compare as BYTES: hmac.compare_digest raises TypeError on a non-ASCII
        # str, and `actual` is attacker-controlled — a non-ASCII clientState
        # must fail the compare, never raise. Still constant-time over bytes.
        if isinstance(expected, str):
            expected_b = expected.encode("utf-8")
        elif isinstance(expected, (bytes, bytearray)):
            expected_b = bytes(expected)
        else:
            return False  # misconfigured secret → fail closed
        return hmac.compare_digest((actual or "").encode("utf-8"), expected_b)

    async def _claim(self, key: str) -> bool:
        """Claim a notification for processing. Returns True if newly claimed
        (process it), False if already seen this run (a duplicate — drop). A
        failing durable hook claims rather than drops (at-least-once beats lost)."""
        if self._seen is not None:
            try:
                return not bool(await self._seen(key))
            except Exception as exc:
                logger.error("webhooks dedup error_type=%s", type(exc).__name__)
                return True
        async with self._seen_lock:
            if key in self._seen_keys:
                self._seen_keys.move_to_end(key)
                return False
            self._seen_keys[key] = None
            if len(self._seen_keys) > self._max_seen:
                self._seen_keys.popitem(last=False)
            return True

    async def _release(self, key: str) -> None:
        """Un-claim an in-memory key claimed but not successfully processed, so a
        later Graph re-delivery is retried instead of dropped as a duplicate.
        No-op for a durable ``seen`` hook — it owns its own at-least/at-most-once
        policy (record-on-check there means a failed event's repeat is dropped;
        record-on-success in the hook if you need the retry)."""
        if self._seen is not None:
            return
        async with self._seen_lock:
            self._seen_keys.pop(key, None)


__all__ = [
    "WebhookDispatcher",
    "DispatchReport",
    "ChangeHandler",
    "LifecycleHandler",
    "ClientStateResolver",
    "SeenPredicate",
    "LIFECYCLE_WILDCARD",
]
