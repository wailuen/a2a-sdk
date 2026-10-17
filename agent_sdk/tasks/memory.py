"""InMemoryTaskStore — the default, process-local store (DESIGN.md §5.2)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any, Callable, Sequence

from ..agent.loop import is_user_turn_boundary
from ..agent.reuse import extract_resolved_markers
from ..auth.identity import Identity
from ..models.a2a import Task
from ..models.errors import AgentError, ErrorCategory
from .store import StreamTerminated, Subscription, TaskRecord, TaskStore

logger = logging.getLogger(__name__)

__all__ = [
    "InMemoryTaskStore",
    "StreamTerminated",
    "MAX_REUSABLE_TASKS",
    "MAX_CONTEXT_MESSAGES",
]

# RT-010: caps the number of terminal tasks context_reusable_messages()
# scans per call, newest first — without this, a long-lived thread makes
# every fresh (non-resume) request on it re-walk and re-allocate the
# transcript of every prior run in the thread, unbounded. Mirrors
# routes/ag_ui.py's MAX_HISTORY_MESSAGES precedent for the same class of
# unbounded-history problem on a different carrier.
MAX_REUSABLE_TASKS = 50

# RT-007: caps how many messages context_messages() carries from the most
# recent terminal task into a fresh contextId continuation. Both sibling
# carriers already bound themselves — MAX_REUSABLE_TASKS above (task count)
# and routes/ag_ui.py's MAX_HISTORY_MESSAGES (message count) — but this,
# the PRIMARY A2A carrier, stayed uncapped: it grows linearly with total
# turns for the life of a thread, and the model prompt built from it grows
# with it, eventually failing upstream on context length rather than
# exiting cleanly through LoopPolicies.token_budget (which counts tokens
# already spent, not prompt size). Trailing-N only, never a raw head/tail
# split of the transcript — see _turn_boundary_slice below.
MAX_CONTEXT_MESSAGES = 50


def _turn_boundary_slice(
    messages: list[dict[str, Any]], cap: int
) -> list[dict[str, Any]]:
    """``messages`` unchanged when it already fits in ``cap`` — capping must
    never rewrite a transcript it didn't need to shrink, including one with
    no genuine turn boundary in it at all (e.g. an out-of-loop repair-only
    tail with no organic user turn, GH-150). Otherwise, the trailing ``cap``
    messages, advanced forward to the next genuine turn boundary
    (``agent.loop.is_user_turn_boundary`` — RT-004, debug round 5: the ONE
    C-017-registered implementation of that predicate, imported and shared
    with the read-side head repair in
    ``agent/loop.py::bridge_context_messages`` rather than kept as a second
    byte-equivalent private copy in this module. Note the two callers apply it
    to different questions: this one caps and so must leave an already-fitting
    transcript alone, while the read-side one REPAIRS and so must trim an
    illegal head unconditionally.)

    A raw ``messages[-cap:]`` slice can land mid-tool-round: on a
    ``toolResult`` continuation message whose matching ``toolUse`` fell
    outside the window, or on an assistant turn whose ``toolUse`` block has
    no answering ``toolResult`` in the window at all. Bedrock's Converse API
    rejects both shapes outright (the same invariant
    ``agent.loop.close_dangling_tool_use``/``bridge_context_messages`` guard
    at the transcript's tail — this guards the new HEAD a cap introduces).
    Every genuine turn in a transcript built through the normal request path
    starts with exactly such a plain-text user message
    (``_create_task_record``'s seed turn, every ``run_loop`` turn boundary)
    — never a toolResult-only one — so scanning forward for one, once
    truncation has actually happened, is safe.

    RT-002: a single task's own transcript is bounded by that task's own
    ``max_turns`` (``2 * max_turns + 2`` messages for a run that never
    finishes — GH-... regression at ``max_turns=25``), which can exceed
    ``cap`` with no turn boundary anywhere in the trailing window: the ONLY
    plain user turn is the seed message at index 0, outside it. Returning
    ``[]`` there would silently disable contextId continuation for that
    thread entirely, not just truncate it. So when the trailing window has
    no boundary, the search widens BACKWARD past ``cap`` for the nearest
    earlier one, logging a WARNING — this cannot reopen the unbounded-growth
    risk ``cap`` guards against (RT-007), because that risk is a long-lived
    THREAD accumulating cost across many completed tasks, while this widens
    within one already-finite task's own message list. Returns an empty
    list, also logged, only when no turn boundary exists anywhere in
    ``messages`` — the caller already treats that as "no usable prior
    context" for a fresh continuation."""
    if len(messages) <= cap:
        return list(messages)
    tail_start = len(messages) - cap
    for i in range(tail_start, len(messages)):
        if is_user_turn_boundary(messages[i]):
            return messages[i:]
    for i in range(tail_start - 1, -1, -1):
        if is_user_turn_boundary(messages[i]):
            logger.warning(
                "context continuation: no turn boundary within the trailing "
                "%d-message cap (transcript has %d messages) — falling back "
                "to a %d-message slice from the nearest earlier turn "
                "boundary instead of dropping prior context. Raise "
                "MAX_CONTEXT_MESSAGES (or lower max_turns) if this recurs.",
                cap, len(messages), len(messages) - i,
            )
            return messages[i:]
    logger.warning(
        "context continuation: dropping the entire prior transcript — no "
        "turn boundary found anywhere in %d messages (cap=%d); contextId "
        "continuation loses all prior context for this thread.",
        len(messages), cap,
    )
    return []


class InMemoryTaskStore(TaskStore):
    MAX_REUSABLE_TASKS: int = MAX_REUSABLE_TASKS
    """RT-006 (debug round 4): the cap ``context_reusable_messages`` applies,
    exposed as a CLASS attribute so ``TaskStore.context_reusable_messages``'s
    docstring can cite it as the in-memory store's cap and be right — it
    named ``InMemoryTaskStore.MAX_REUSABLE_TASKS`` while the value existed
    only as the module-level constant above, closed over directly by the
    method, so an implementer following that pointer got an ``AttributeError``
    or silently believed they had overridden a cap they had not. Read through
    ``self`` below, so a subclass can now genuinely change it. The module
    constant remains the default and stays exported for direct import."""

    MAX_CONTEXT_MESSAGES: int = MAX_CONTEXT_MESSAGES
    """RT-007: same pattern as ``MAX_REUSABLE_TASKS`` above — the cap
    ``context_messages`` applies, exposed as a class attribute (read through
    ``self`` in the method below) so a subclass can genuinely override it,
    not just shadow a module constant the method ignores."""

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
        # the TTL clock — `_evict_over_capacity` walks `self._records` in
        # insertion order, so a task that had been streaming frames for an
        # hour must not still sit at the LRU end as the first thing overflow
        # eviction picks.
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
        """Return messages from the most recent COMPLETED task in this
        context (GH-187: FAILED/CANCELED/REJECTED tasks are skipped entirely,
        including their user message, so a retry never inherits a failed
        turn's stale tool results), identity-scoped exactly like ``context_reusable_messages()``
        below — no admin api_key bypass (RT-004): this seeds a NEW task's
        model-facing ``record.messages`` (``routes/a2a.py::_create_task_record``),
        not a read-only inspection view, so cross-identity transcript data
        must never enter a caller's own task through it. Genuine operator
        inspection of another identity's task already exists, safely, as a
        read: ``GET /v1/tasks/{id}`` (this store's ``get()`` admin override,
        §5.1) — which never seeds a new task's model context.

        RT-007: bounded to the newest ``MAX_CONTEXT_MESSAGES`` messages —
        without this, a long-lived thread makes every fresh (non-resume)
        request re-carry the transcript of every prior turn, unbounded, into
        the new task's ``record.messages`` and the model prompt built from
        it. Truncation lands on a genuine turn boundary
        (``_turn_boundary_slice``), never mid-tool-round — and never on
        nothing at all (RT-002): a single terminal task whose own transcript
        has no turn boundary inside the trailing cap window (e.g. it hit
        ``max_turns`` without ever finishing) still gets a usable, logged
        fallback slice rather than losing all prior context silently."""
        from ..models.a2a import TaskState
        candidates = [
            r for r in self._records.values()
            if r.task.context_id == context_id
            and r.task.status.state == TaskState.COMPLETED
            and (identity is None or r.identity == identity.binding)
        ]
        if not candidates:
            return []
        latest = max(candidates, key=lambda r: r.created_at)
        # RT-007: read through ``self`` so a subclass override genuinely
        # changes the cap (mirrors MAX_REUSABLE_TASKS, RT-006).
        return _turn_boundary_slice(list(latest.messages), self.MAX_CONTEXT_MESSAGES)

    def context_reusable_messages(
        self, context_id: str, identity: Identity | None = None
    ) -> Sequence[dict[str, Any]]:
        """The ``__resolved__`` marker content of the newest
        ``MAX_REUSABLE_TASKS`` COMPLETED tasks (GH-187: markers from
        FAILED/CANCELED/REJECTED tasks are not reused) in ``context_id``, oldest
        first (RT-001) — never the admin cross-identity override (RT-009);
        see the base-class docstring (tasks/store.py).

        RT-010: bounded on two axes so a long-lived thread cannot make
        every fresh request re-walk and re-allocate its entire history —
        only the newest ``MAX_REUSABLE_TASKS`` terminal tasks are scanned
        at all, and each contributes only its marker content
        (``extract_resolved_markers``, RT-010), never its full messages:
        ``scan_resolved`` (the sole consumer of this method's return value)
        reads nothing else out of it."""
        from ..models.a2a import TaskState
        candidates = [
            r for r in self._records.values()
            if r.task.context_id == context_id
            and r.task.status.state == TaskState.COMPLETED
            and (identity is None or r.identity == identity.binding)
        ]
        candidates.sort(key=lambda r: r.created_at, reverse=True)
        # RT-006: read through ``self`` so the documented class attribute is
        # the real knob — a subclass setting it actually changes the cap.
        candidates = candidates[: self.MAX_REUSABLE_TASKS]
        candidates.reverse()
        combined: list[dict[str, Any]] = []
        for r in candidates:
            combined.extend(extract_resolved_markers(r.messages))
        return combined

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
        #    overflow picks.
        #
        # Both skips let occupancy exceed `capacity`, by design and boundedly:
        # `interrupted` by `max_interrupted`, and subscribed records by the
        # route-layer stream budgets, which is precisely what those caps are
        # for. A bounded overrun is the correct trade against silently
        # severing a live stream.
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
