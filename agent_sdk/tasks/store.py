"""TaskStore interface + records (DESIGN.md §5.2).

Process-local by design (§2 single-process invariant). The store owns task
lifecycle state shared by A2A routes, the loop worker, and SSE subscribers:

- LRU (1000) / TTL (1h) bounded records carrying their creating identity
- per-subscriber bounded queues (maxsize 256) with sentinel close;
  overflow terminates that subscriber's stream — never silent drops
- the resume channel for interrupted tasks: interrupted tasks are excluded
  from LRU pressure-eviction, get their own TTL (default 30 min), and are
  capped by AGENT_SDK_MAX_INTERRUPTED (at the cap a new interrupt is a typed
  task failure). Any eviction cancels the paused worker, closes the resume
  channel and sentinel-closes subscriber queues — nothing leaks.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..auth.identity import Identity
from ..models.a2a import Task

_CLOSE = object()  # sentinel: stream closed normally (final frame already published)


class StreamTerminated(Exception):
    """Subscriber queue overflowed or task was evicted: the stream ends
    without a final frame; the documented consumer contract is re-subscribe
    (then 404 if the task expired)."""


class Subscription:
    def __init__(self, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._killed = False
        # RT-001 (round 4): the ASGI request task that owns this subscription,
        # captured at subscribe() time. Routes subscribe EAGERLY — before the
        # StreamingResponse exists, so no frame is missed — and then release in
        # the SSE generator's `finally`. That `finally` is not a lifecycle hook:
        # it never runs when the request task is cancelled at Starlette's
        # send(http.response.start) checkpoint, before the body iterator is
        # pulled, and that same unwind skips the response's BackgroundTask too.
        # Recording the owner lets subscribe() reclaim such an orphan on a
        # LIVENESS FACT (the owning task finished) rather than a timing guess —
        # a still-open stream's task is never done, so a live subscriber can
        # never be reaped. None when subscribe() ran outside a task (direct
        # store use in tests): such a subscription is simply never auto-reaped.
        self.owner_task: "asyncio.Task[Any] | None" = None

    def publish(self, event: Any) -> None:
        if self._killed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # slow consumer: terminate, never drop frames silently (§5.2)
            self._killed = True

    def close(self) -> None:
        if self._killed:
            return
        try:
            self._queue.put_nowait(_CLOSE)
        except asyncio.QueueFull:
            self._killed = True

    async def get(self) -> Any:
        """Next event; None on normal close; StreamTerminated on kill."""
        if self._killed and self._queue.empty():
            raise StreamTerminated()
        event = await self._queue.get()
        if event is _CLOSE:
            return None
        return event


@dataclass(slots=True)
class TaskRecord:
    task: Task
    identity: tuple[str, str]  # (kind, subject) binding — §5.1
    created_at: float
    updated_at: float
    worker: asyncio.Task[Any] | None = None
    bg_task: asyncio.Task[Any] | None = None  # GH-87: deferred background awaiter
    subscriptions: list[Subscription] = field(default_factory=list)
    # interrupt state
    interrupted: bool = False
    interrupt_deadline: float | None = None
    interrupt_id: str | None = None
    resume_future: asyncio.Future[Any] | None = None
    # cumulative model spend, survives resume cycles (§8)
    spent_tokens: int = 0
    # Converse-format history retained for resume folding
    messages: list[dict[str, Any]] = field(default_factory=list)


class TaskStore(abc.ABC):
    def reap_dead_subscriptions(self, record: TaskRecord) -> None:
        """RT-003: shared layer-3 backstop every ``subscribe()`` implementation
        must call. Drops any ``Subscription`` whose owning ASGI request task
        has finished (``owner_task.done()``) — a liveness fact, never elapsed
        time, so a still-open stream's subscription is never reaped. A
        subscription whose ``owner_task`` is ``None`` (recorded outside a
        running task — direct store use in tests) is never auto-reaped
        either. Concrete rather than abstract: the filter depends only on
        ``TaskRecord``/``Subscription`` fields this base class already
        defines, so every implementation gets the identical, tested behavior
        for free rather than re-deriving the filter (see ``subscribe``'s
        docstring for why skipping this call is a leak, not a style choice)."""
        if record.subscriptions:
            record.subscriptions[:] = [
                s
                for s in record.subscriptions
                if s.owner_task is None or not s.owner_task.done()
            ]

    def new_subscription(self, record: TaskRecord, maxsize: int = 256) -> Subscription:
        """RT-002 (round 7): the COMPLETE ``subscribe()`` body every
        implementation should delegate to — reap, construct, stamp
        ``owner_task``, append — as ONE concrete method.

        ``reap_dead_subscriptions`` alone was only half the contract, and the
        unstated half was the half that makes it work.
        ``reap_dead_subscriptions`` keeps every entry whose ``owner_task`` is
        ``None``, and ``Subscription.__init__`` defaults it to ``None`` — so an
        implementation that faithfully called the reap but never stamped
        ``sub.owner_task`` had a permanently VACUOUS backstop:
        ``record.subscriptions`` grew without bound exactly as before, and
        ``publish()`` walked every leaked entry per frame. Mandating only the
        consume half left the backstop a no-op for every implementation that
        did not already do both, on a documented public extension point
        (``Agent(task_store=...)``, DESIGN.md §4.1).

        The stamp is a liveness fact, not a timing guess: the owning ASGI
        request task stays not-done for the entire response cycle
        (``StreamingResponse`` body and ``BackgroundTask`` included), so a
        still-open stream can never be reaped, however long it holds its
        connection. ``asyncio.current_task()`` raises ``RuntimeError`` with no
        running loop (direct store use in a sync test), which folds to ``None``
        — such a subscription is simply never auto-reaped.

        Concrete, and reached through the store rather than assembled at the
        call site, for the same reason ``routes/a2a.py``'s ``_ClaimedSlot``
        exposes ``subscribe`` instead of a ``bind`` the route must remember:
        a two-step contract is one a future implementation can satisfy halfway.
        """
        self.reap_dead_subscriptions(record)
        sub = Subscription(maxsize=maxsize)
        try:
            sub.owner_task = asyncio.current_task()
        except RuntimeError:  # no running loop (direct store use outside async)
            sub.owner_task = None
        record.subscriptions.append(sub)
        return sub

    @abc.abstractmethod
    def create(self, task: Task, identity: Identity) -> TaskRecord: ...

    @abc.abstractmethod
    def get(self, task_id: str, identity: Identity | None = None) -> TaskRecord | None:
        """Identity-bound lookup: mismatched identity → None (existence is
        not leaked; routes answer 404 + -32001). ``identity=None`` or an
        admin api_key identity bypasses the binding."""

    @abc.abstractmethod
    def subscribe(self, task_id: str) -> Subscription:
        """Register a new consumer and return its ``Subscription``.

        Resolve ``task_id`` to its ``TaskRecord`` and return
        ``self.new_subscription(record, maxsize=...)``. That concrete helper is
        the whole required body; an implementation that reproduces it by hand
        MUST reproduce BOTH halves of the contract, in this order:

        1. **Reap** dead subscriptions from the target record — call
           ``self.reap_dead_subscriptions(record)`` (or reproduce its identical
           ``owner_task.done()`` filter). A route may subscribe eagerly, before
           its ``StreamingResponse`` exists, and then be hard-cancelled before
           any of its own release paths run (bare generator ``finally``, the
           response's ``BackgroundTask``) — see ``Subscription.owner_task``.
           Without this reap, ``record.subscriptions`` grows without bound and
           every subsequent ``publish()`` walks the leaked entries.
        2. **Record the owner** on the subscription being returned — set
           ``sub.owner_task = asyncio.current_task()`` (``None`` when there is
           no running loop) BEFORE appending it. RT-002 (round 7): this half is
           what makes step 1 non-vacuous. ``reap_dead_subscriptions`` keeps
           every ``owner_task is None`` entry by design, and
           ``Subscription.__init__`` defaults it to ``None`` — so an
           implementation that reaps but never stamps leaks exactly as much as
           one that never reaped at all, and additionally pins its record
           against ``InMemoryTaskStore._evict_over_capacity``'s
           live-subscriber skip for the process lifetime.

        ``tests/test_rt003_task_store_reap_conformance.py`` asserts both halves
        against every factory in its ``_STORE_FACTORIES`` list; a new
        implementation should add itself there."""

    @abc.abstractmethod
    def unsubscribe(self, task_id: str, sub: Subscription) -> None:
        """Detach a consumer (stream ended or client disconnected) so the
        worker stops filling its queue."""

    @abc.abstractmethod
    def find_interrupt(
        self, interrupt_id: str, identity: Identity | None = None
    ) -> TaskRecord | None:
        """Identity-bound lookup by pending interrupt id (AG-UI resume path,
        §5.3)."""

    @abc.abstractmethod
    def publish(self, task_id: str, event: Any) -> None: ...

    @abc.abstractmethod
    def close_streams(self, task_id: str) -> None:
        """Normal close after the final frame was published."""

    @abc.abstractmethod
    def mark_interrupted(self, task_id: str, interrupt_id: str) -> asyncio.Future[Any]:
        """Register the interrupt and return the resume future the worker
        awaits. Raises AgentError at the MAX_INTERRUPTED cap."""

    @abc.abstractmethod
    def deliver_resume(self, task_id: str, value: Any) -> bool:
        """Hand a resume value to the paused worker. False if the task is
        not interrupted (caller maps to the spec error)."""

    def interrupt_ttl_remaining(self, task_id: str) -> float | None:
        """Seconds remaining before the pending interrupt expires, or None
        if the task is not currently interrupted.

        A relative duration, not a raw reading from ``self._clock()`` —
        callers (route/serializer code) must stay agnostic to whichever
        clock a concrete store uses internally (``time.monotonic`` for the
        in-memory store; a durable cross-process store may use
        ``time.time`` instead). Implementations compute this by subtracting
        their own clock reading from their own stored deadline.

        Default implementation returns None (unknown) so pre-existing
        ``TaskStore`` subclasses that predate this hook keep instantiating;
        callers already treat None as "no expiry to report" (AG-UI route
        omits ``expiresAt`` in that case). Concrete stores should override
        this to report a real deadline where they track one."""
        return None

    @abc.abstractmethod
    def list_tasks_for_identity(
        self, identity: Identity, page_size: int = 50, page_token: str | None = None
    ) -> tuple[list[Task], str | None, int]:
        """Return up to ``page_size`` tasks owned by ``identity``, sorted by
        task id, plus an opaque ``nextPageToken`` when more remain, and the
        total count of all matching tasks regardless of cursor."""

    def context_messages(
        self, context_id: str, identity: Identity | None = None
    ) -> Sequence[dict[str, Any]]:
        """Return the Converse-format message history from the most recent
        terminal task in ``context_id`` owned by ``identity``.  Used by
        ``_create_task_record`` to carry prior conversation history into a
        new task started on the same context (A2A §3 contextId continuation).
        Returns an empty list when no prior terminal task exists."""
        return []

    @abc.abstractmethod
    def evict(self, task_id: str) -> None:
        """Cancel worker, close resume channel, sentinel-close subscribers,
        drop the record."""

    @abc.abstractmethod
    def sweep(self) -> None:
        """TTL pass — called periodically from the lifespan."""

    def close_all(self) -> None:
        """Cancel all live workers, close resume channels, and sentinel-close
        all subscriber queues.  Called once during graceful shutdown before
        adapters are closed.  Default implementation iterates ``evict()`` over
        every record ID — concrete stores may override for efficiency."""
        for task_id in list(getattr(self, "_records", {}).keys()):
            self.evict(task_id)
