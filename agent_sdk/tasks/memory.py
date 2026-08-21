"""InMemoryTaskStore — the default, process-local store (DESIGN.md §5.2)."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Callable, Sequence

from ..auth.identity import Identity
from ..models.a2a import Task
from ..models.errors import AgentError, ErrorCategory
from .store import StreamTerminated, Subscription, TaskRecord, TaskStore

__all__ = ["InMemoryTaskStore", "StreamTerminated"]


class InMemoryTaskStore(TaskStore):
    def __init__(
        self,
        *,
        capacity: int = 1000,
        task_ttl: float = 3600.0,
        interrupt_ttl: float = 1800.0,
        max_interrupted: int = 100,
        queue_maxsize: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._records: OrderedDict[str, TaskRecord] = OrderedDict()
        self._capacity = capacity
        self._task_ttl = task_ttl
        self._interrupt_ttl = interrupt_ttl
        self._max_interrupted = max_interrupted
        self._queue_maxsize = queue_maxsize
        self._clock = clock

    # ── lifecycle ──

    def create(self, task: Task, identity: Identity) -> TaskRecord:
        now = self._clock()
        record = TaskRecord(
            task=task, identity=identity.binding, created_at=now, updated_at=now
        )
        self._records[task.id] = record
        self._records.move_to_end(task.id)
        self._evict_over_capacity()
        return record

    def get(self, task_id: str, identity: Identity | None = None) -> TaskRecord | None:
        record = self._records.get(task_id)
        if record is None:
            return None
        if self._expired(record):
            # RT-001 (round 6, AG-UI cross-check): the same live-subscriber
            # guard `_evict_over_capacity` uses must apply here too. This path
            # is reachable from `find_interrupt()` — e.g. an AG-UI resume
            # lookup on a DIFFERENT record than the one being resumed — so an
            # unrelated caller's TTL/interrupt-deadline check could otherwise
            # `evict()` a record some other subscriber is still actively
            # streaming, severing it with no `final:true` frame. Reap first so
            # a leaked (owner-task-finished) subscription can never pin an
            # actually-expired record here forever.
            self.reap_dead_subscriptions(record)
            if not record.subscriptions:
                self.evict(task_id)
                return None
        if identity is not None and not (identity.kind == "api_key" and identity.admin):
            if record.identity != identity.binding:
                return None  # existence is not leaked (§5.1)
        self._records.move_to_end(task_id)
        return record

    def touch(self, task_id: str) -> None:
        record = self._records.get(task_id)
        if record is not None:
            record.updated_at = self._clock()
            self._records.move_to_end(task_id)

    # ── streams ──

    def subscribe(self, task_id: str) -> Subscription:
        record = self._records[task_id]
        # RT-001 (round 4) / RT-003 / RT-002 (round 7): reap-then-stamp-then-
        # append is the WHOLE required body, and it now lives as one concrete
        # method on the TaskStore base class (`new_subscription`) rather than
        # being reproduced here. The reap reclaims subscriptions whose owning
        # ASGI request task finished without unsubscribing — the case a bare
        # generator `finally` and a response BackgroundTask both miss when the
        # request task is hard-cancelled before the SSE body starts — and the
        # `owner_task` stamp is what gives that reap anything to match on (see
        # `new_subscription`'s docstring: reap without stamp is vacuous).
        # Bounded here rather than by a cap because publish() walks this list
        # for every frame.
        return self.new_subscription(record, maxsize=self._queue_maxsize)

    def unsubscribe(self, task_id: str, sub: Subscription) -> None:
        record = self._records.get(task_id)
        if record is not None and sub in record.subscriptions:
            record.subscriptions.remove(sub)

    def find_interrupt(
        self, interrupt_id: str, identity: Identity | None = None
    ) -> TaskRecord | None:
        for task_id, record in list(self._records.items()):
            if record.interrupted and record.interrupt_id == interrupt_id:
                return self.get(task_id, identity)
        return None

    def publish(self, task_id: str, event: Any) -> None:
        record = self._records.get(task_id)
        if record is None:
            return
        # RT-001 (round 5, fresh-lens): refresh the LRU position, not just
        # `updated_at`. `_evict_over_capacity` walks `self._records` in
        # insertion order, and before this call `publish()` touched only the
        # TTL clock — so a task that had been streaming frames for an hour was
        # still sitting at the LRU end and was the FIRST thing overflow
        # eviction chose. `touch()` is the single place that keeps the two in
        # step; delegating here is what gives it a call site (it previously had
        # none repo-wide, which is why the LRU never reflected stream activity).
        self.touch(task_id)
        for sub in record.subscriptions:
            sub.publish(event)

    def close_streams(self, task_id: str) -> None:
        record = self._records.get(task_id)
        if record is None:
            return
        for sub in record.subscriptions:
            sub.close()
        record.subscriptions.clear()

    # ── interrupts / resume ──

    def mark_interrupted(self, task_id: str, interrupt_id: str) -> asyncio.Future[Any]:
        if self._interrupted_count() >= self._max_interrupted:
            raise AgentError(
                ErrorCategory.RATE_LIMITED,
                "too many tasks awaiting input; retry later",
            )
        record = self._records[task_id]
        record.interrupted = True
        record.interrupt_id = interrupt_id
        record.interrupt_deadline = self._clock() + self._interrupt_ttl
        record.resume_future = asyncio.get_running_loop().create_future()
        return record.resume_future

    def deliver_resume(self, task_id: str, value: Any) -> bool:
        record = self._records.get(task_id)
        if (
            record is None
            or not record.interrupted
            or record.resume_future is None
            or record.resume_future.done()
        ):
            return False
        record.interrupted = False
        record.interrupt_deadline = None
        record.updated_at = self._clock()
        record.resume_future.set_result(value)
        record.resume_future = None
        return True

    def interrupt_ttl_remaining(self, task_id: str) -> float | None:
        record = self._records.get(task_id)
        if record is None or not record.interrupted or record.interrupt_deadline is None:
            return None
        return record.interrupt_deadline - self._clock()

    # ── context continuation ──

    def context_messages(
        self, context_id: str, identity: Identity | None = None
    ) -> Sequence[dict[str, Any]]:
        """Return messages from the most recent terminal task in this context."""
        from ..models.a2a import TERMINAL_STATES
        candidates = [
            r for r in self._records.values()
            if r.task.context_id == context_id
            and r.task.status.state in TERMINAL_STATES
            and (
                identity is None
                or (identity.kind == "api_key" and identity.admin)
                or r.identity == identity.binding
            )
        ]
        if not candidates:
            return []
        latest = max(candidates, key=lambda r: r.created_at)
        return list(latest.messages)

    # ── listing ──

    def list_tasks_for_identity(
        self, identity: Identity, page_size: int = 50, page_token: str | None = None
    ) -> tuple[list[Task], str | None, int]:
        page_size = min(max(page_size, 1), 100)
        all_matching = sorted(
            (r for r in self._records.values() if r.identity == identity.binding),
            key=lambda r: r.task.id,
        )
        total = len(all_matching)
        after_cursor = (
            [r for r in all_matching if r.task.id > page_token]
            if page_token is not None
            else all_matching
        )
        page = after_cursor[:page_size]
        next_token = page[-1].task.id if len(after_cursor) > page_size else None
        return [r.task for r in page], next_token, total

    # ── eviction ──

    def evict(self, task_id: str) -> None:
        record = self._records.pop(task_id, None)
        if record is None:
            return
        if record.resume_future is not None and not record.resume_future.done():
            record.resume_future.cancel()
            record.resume_future = None
        if record.worker is not None and not record.worker.done():
            record.worker.cancel()
        # GH-87 / W025-GH87-SHUTDOWN-TRACK-001: cancel the deferred background
        # awaiter if it is still running so it can transition the task to FAILED
        # and close streams deterministically before adapter teardown.
        if record.bg_task is not None and not record.bg_task.done():
            record.bg_task.cancel()
        for sub in record.subscriptions:
            sub.close()
        record.subscriptions.clear()

    def sweep(self) -> None:
        # Same live-subscriber guard as `get()`/`_evict_over_capacity`: the
        # periodic sweeper must not silently sever a still-actively-streamed
        # record just because its TTL/interrupt-deadline lapsed while a live
        # subscriber was waiting on it.
        for task_id in [tid for tid, r in self._records.items() if self._expired(r)]:
            record = self._records.get(task_id)
            if record is None:
                continue
            self.reap_dead_subscriptions(record)
            if record.subscriptions:
                continue
            self.evict(task_id)

    def close_all(self) -> None:
        """Cancel all live workers and sentinel-close all subscriber queues.
        Called once from lifespan finally to drain interrupted tasks before
        adapters are torn down (DESIGN.md §5.2 shutdown contract)."""
        for task_id in list(self._records.keys()):
            self.evict(task_id)

    # ── internals ──

    def _interrupted_count(self) -> int:
        return sum(1 for r in self._records.values() if r.interrupted)

    def _expired(self, record: TaskRecord) -> bool:
        now = self._clock()
        if record.interrupted:
            # the confirmation window owns expiry while interrupted (§5.2)
            return record.interrupt_deadline is not None and now > record.interrupt_deadline
        return now - record.updated_at > self._task_ttl

    def _evict_over_capacity(self) -> None:
        # Oldest first, skipping records that must not be torn down merely
        # because someone else filled the store:
        #
        #  - `interrupted` — they pin paused workers and are bounded
        #    separately by `max_interrupted`.
        #
        #  - RT-001 (round 5, fresh-lens): records with LIVE SUBSCRIBERS.
        #    `evict()` cancels the record's worker and `sub.close()`s every
        #    subscriber, which pushes the bare `None` sentinel — routes/a2a.py's
        #    `gen()` reads that as "stop" and returns WITHOUT emitting a
        #    `final:true` TaskStatusUpdateEvent, so the client's SSE stream just
        #    dies mid-flight and the task is gone from the store (a later
        #    `tasks:subscribe` 404s and the work is lost). Because eviction is
        #    driven by TOTAL store occupancy, the caller who overflows the store
        #    is almost never the owner of the record that gets evicted: any
        #    authenticated identity calling `POST /v1/message:send` — which has
        #    no admission cap at all, and needs none — could sever another
        #    tenant's in-flight stream. The route-layer admission caps cannot
        #    fix this; they bound how many streams exist, not which record
        #    overflow picks. Reproduced end-to-end: with one live subscriber
        #    open, six `create()` calls from a different identity killed it.
        #
        #    This is the same reject-don't-evict rule routes/mcp.py's
        #    `_MAX_GET_STREAMS` comment already states for stream admission,
        #    finally applied at the layer that actually does the evicting.
        #
        # Both skips let occupancy exceed `capacity`, by design and boundedly:
        # `interrupted` by `max_interrupted`, and subscribed records by the
        # route-layer stream budgets (`_MAX_A2A_STREAMS` + `_MAX_GET_STREAMS`),
        # which is precisely what those caps are for. A bounded overrun is the
        # correct trade against silently severing a live stream.
        if len(self._records) <= self._capacity:
            return
        for task_id in list(self._records.keys()):
            if len(self._records) <= self._capacity:
                break
            record = self._records[task_id]
            if record.interrupted:
                continue
            # Reap first, so a LEAKED subscription (owning request task already
            # finished) can never pin a record here forever — that would trade
            # a severed stream for an unbounded store. Only genuinely live
            # subscribers protect a record.
            self.reap_dead_subscriptions(record)
            if record.subscriptions:
                continue
            self.evict(task_id)
