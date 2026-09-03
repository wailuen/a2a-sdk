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
    # RT-B-001: ``toolResult`` blocks already built for the turn currently in
    # flight, owned here rather than inside ``run_loop`` so that a mid-turn
    # exit cannot destroy them. ``run_loop`` folds a turn's assistant
    # ``toolUse`` message into ``messages`` BEFORE running that turn's
    # per-tool-call loop, and appends the matching ``user``/``toolResult``
    # message only once EVERY call in the turn has finished. Any mid-turn
    # exit — a ``DeferredEvent`` handoff (GH-87), a cancellation (GH-150), or
    # a raise that unwinds the generator frame (RT-A-002) — therefore used to
    # discard the results of the calls in that turn that DID complete, and
    # ``repair_dangling_tool_use`` then synthesised a blanket error result for
    # every one of them: the model was told on the next contextId
    # continuation that a tool which actually succeeded (and whose real result
    # had already reached the client as a ToolResultEvent) returned nothing.
    # Runtime-only turn state, exactly like ``worker``/``resume_future``:
    # never serialised, cleared by ``run_loop`` at each turn boundary and by
    # ``repair_dangling_tool_use`` once consumed.
    pending_tool_results: list[dict[str, Any]] = field(default_factory=list)


class TaskStore(abc.ABC):
    """Abstract task lifecycle store (C-005).

    In-place mutation contract (RT-005/RT-B-003, GH-150 follow-up): callers
    that already hold a ``TaskRecord`` — ``run_loop``, ``set_task_status``,
    the out-of-loop repair helper ``agent/runner.py::repair_dangling_tool_use``,
    and ``routes/a2a.py``'s ``tasks_cancel`` (via ``set_task_status`` for
    ``task.status``, RT-004; directly for its other fields — ``interrupted``,
    ``worker``, ``bg_task``, ``resume_future``) — mutate its fields
    (``task.status``, ``messages``, ``pending_tool_results``, ...) directly
    on that object rather than calling a setter per field.
    ``InMemoryTaskStore.get()`` returns the live record by reference, so
    this is transparently correct for it. A durable subclass whose ``get()``
    deserializes a fresh copy per call must either make ``get()`` return
    (and internally track) the SAME object across calls for the lifetime of
    a task, or override the narrow write hooks this ABC exposes for the
    mutations that have one (``persist_messages`` for ``messages``;
    ``persist_status`` for ``task.status``) — there is no such hook yet
    for the other
    in-place-mutated fields (e.g. ``task.artifacts``); a subclass needing
    durability for those must track object identity itself. A subclass
    needing durability for ``task.status`` MUST override ``persist_status``
    in addition to ``persist_messages``: overriding one without the other
    still loses data — a CANCELED status that never reaches durable storage
    means ``context_messages()``'s ``TERMINAL_STATES`` filter never finds
    the task, so the transcript ``persist_messages`` flushed is never read
    back as a continuation candidate either.
    """

    @abc.abstractmethod
    def create(self, task: Task, identity: Identity) -> TaskRecord: ...

    @abc.abstractmethod
    def get(self, task_id: str, identity: Identity | None = None) -> TaskRecord | None:
        """Identity-bound lookup: mismatched identity → None (existence is
        not leaked; routes answer 404 + -32001). ``identity=None`` or an
        admin api_key identity bypasses the binding."""

    @abc.abstractmethod
    def subscribe(self, task_id: str) -> Subscription: ...

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

    def persist_messages(self, record: TaskRecord) -> None:
        """Flush ``record.messages`` after an out-of-loop caller has
        repaired it in place (RT-005, GH-150 follow-up).

        ``run_loop`` and every out-of-loop repair of a dangling ``toolUse``
        tail (``agent/runner.py``'s ``repair_dangling_tool_use`` — called
        from ``routes/a2a.py``'s ``tasks_cancel`` and from ``runner.py``'s
        deferred background awaiter and terminal exception handlers) mutate
        ``record.messages`` directly on the object the caller is holding;
        there is no separate write call. ``InMemoryTaskStore`` needs no
        override: its ``get()`` hands back the live record by reference, so
        the in-place mutation IS the write. A durable ``TaskStore`` whose
        ``get()`` deserializes a FRESH copy from storage on every call (the
        external ``AzureTableTaskStore`` shape this ABC exists for) MUST
        override this to write ``record.messages`` back to the backing
        store keyed by ``record.task.id`` — otherwise
        every such repair is silently dropped and the durable store keeps
        replaying the pre-repair (malformed) transcript on the next
        ``context_messages()`` read.

        RT-B-001 (round 2): ``agent/runner.py``'s ``set_task_status`` — the
        choke point for every ``record.task.status`` mutation — ALSO calls
        this hook directly, once, whenever it transitions a task into a
        ``TERMINAL_STATES`` member (RT-B-104: and, since that follow-up,
        every ``INTERRUPT_STATES`` member too — see below). This covers the
        plain, non-repaired completion path (``run_task_worker``'s normal
        ``DoneEvent`` branch), which has no dangling ``toolUse`` tail and
        therefore never reaches ``repair_dangling_tool_use`` at all — before
        this, that path flushed ``persist_status`` (RT-B-008) but never
        ``persist_messages``, so a durable store observed a task going
        terminal without ever having received its transcript.

        RT-007 (debug round 4): the SDK's own out-of-loop repair callers
        (cancel, the deferred-background paths, the terminal exception
        handlers) route through ``agent/runner.py``'s
        ``repair_dangling_tool_use_safe``, which takes no ``store`` and
        issues no flush of its own — ``set_task_status`` is their sole
        flush point, so none of the SDK's own paths call this hook twice for
        the same transition. The double-call case this hook must still
        tolerate is a DIRECT caller: the unguarded
        ``repair_dangling_tool_use`` still accepts its own ``store``
        parameter for a caller that bypasses the guarded wrapper (see its
        docstring, ``agent/runner.py`` — a durable-store author's own
        restart-time repair is exactly the case ``docs/deployment.md``
        points there for), and a caller that combines that with a
        subsequent ``set_task_status(..., store=store)`` on the same record
        triggers this hook twice with the identical, already-repaired
        content — implementations must be idempotent for the same
        reason ``persist_status`` must be (see its own docstring): writing
        the same content twice is not a correctness hazard, so a hook that
        fails or corrupts state on a repeat call with unchanged data is
        itself the bug.

        RT-B-104: also flushed on an ``INTERRUPT_STATES`` transition
        (AUTH_REQUIRED/INPUT_REQUIRED), under the same fail-closed ordering
        as ``TERMINAL_STATES`` (this hook first, ``persist_status`` only if
        it succeeded). ``persist_status``'s own docstring justifies its
        interrupt-state flush as durability for resume-after-restart — but
        status alone is not a coherent record of an interrupted task: the
        matching ``record.messages`` transcript has to accompany it, or a
        durable store is left holding a resumable-looking status over a
        transcript that couldn't back it.

        RT-B-205: **the ``INTERRUPT_STATES`` flush is a MID-TURN snapshot,
        not a turn-boundary one — read that as "accompanies it", never as
        "is directly replayable".** An interrupt is always raised from
        INSIDE the per-tool-call loop (``agent/loop.py``), after that turn's
        assistant ``toolUse`` message has already been folded into
        ``record.messages`` and BEFORE the matching ``toolResult`` is folded
        (that fold happens only once every tool call in the turn finishes
        normally). So ``record.messages`` at the instant of this flush is
        GUARANTEED to end on a dangling assistant ``toolUse`` with no
        matching ``toolResult`` — the exact shape ``repair_dangling_tool_use``
        (C-018) exists to close, which nothing calls on this path (see the
        ``InterruptEvent`` branch, ``agent/runner.py``). It is therefore NOT
        Converse-replayable as-is: a durable subclass whose OWN
        resume-after-restart mechanism reconstructs a task from this
        snapshot must run the same repair (or equivalent logic) before
        handing the transcript to a model, exactly as ``run_loop``'s own
        mid-turn exit paths do. This does not affect the SDK's own in-memory
        resume: ``context_messages()`` filters candidates on
        ``TERMINAL_STATES`` only, so an interrupted task is never selected as
        a continuation candidate, and in-process resume reads the live
        ``resume_future`` directly, never this flushed copy. See also
        DESIGN.md §5.2 and docs/deployment.md's "Custom TaskStore
        durability" section, which restate this for implementers who don't
        read source docstrings.

        This hook flushes ``messages`` only, exactly as documented above —
        it does NOT cover ``record.pending_tool_results``. That field stays
        runtime-only (never serialized, exactly like ``worker``/
        ``resume_future`` — see ``TaskRecord``'s own field comment) even
        across an ``INTERRUPT_STATES`` flush: a turn interrupted after some
        of its sibling tool calls already completed has those results
        sitting in ``pending_tool_results``, still unfolded into
        ``messages`` (folding happens only in ``repair_dangling_tool_use``,
        which nothing calls on this path — see the ``InterruptEvent``
        branch, ``agent/runner.py``). In-process resume is unaffected: the
        live record, and the sibling results inside it, survive untouched.
        A durable subclass whose OWN resume-after-restart mechanism needs
        to reconstruct that mid-turn state has to track
        ``pending_tool_results`` itself — this hook will not do it, and no
        other hook exists for that field.

        Takes the ``TaskRecord`` itself, not a bare ``task_id``: the caller
        already holds the exact object it mutated, and a copy-on-``get()``
        store has no other reference to that copy to resolve an id against.

        Default implementation is a no-op, so a pre-existing external
        ``TaskStore`` subclass keeps instantiating without an override —
        mirroring ``interrupt_ttl_remaining``'s precedent: it silently keeps
        losing repaired transcripts rather than erroring, until it adds
        one."""

    persist_every_status: bool = False
    """RT-007 opt-in: ``agent/runner.py``'s ``set_task_status`` checks this
    before flushing ``persist_status`` on a non-terminal, non-interrupt
    transition (i.e. WORKING). False (the default) skips those calls
    entirely — a subclass sees ``persist_status`` only for TERMINAL_STATES
    and INTERRUPT_STATES. Set True on a subclass to receive every
    transition instead, matching the pre-RT-007 behavior; see
    ``persist_status``'s own docstring below for the full rationale."""

    def persist_status(self, record: TaskRecord) -> None:
        """Flush ``record.task.status`` after an in-place status mutation
        (RT-B-003, GH-150/RT-005 follow-up).

        ``agent/runner.py``'s ``set_task_status`` (RT-B-008, RT-004) is the
        single choke point for EVERY in-place ``record.task.status`` mutation
        the SDK makes — WORKING (opening the task, and again on every
        streamed ``TextEvent``/``ProgressEvent``/``NoteEvent``/
        ``ToolProgressEvent`` chunk), COMPLETED, FAILED, AUTH_REQUIRED,
        INPUT_REQUIRED, and CANCELED (``routes/a2a.py``'s ``tasks_cancel``,
        which calls it rather than mutating ``record.task.status`` itself) —
        but (RT-007, below) it calls this hook only for a subset of those
        transitions by default, not after every one.

        On a ``TERMINAL_STATES`` transition, ``set_task_status`` calls this
        ONLY after its own ``persist_messages(record)`` flush has succeeded
        (RT-B-007: the reverse order — publishing the terminal status before
        the transcript flush it depends on has landed — is fail-unsafe: a
        ``persist_messages`` failure would then leave a durably terminal task
        whose transcript is still the unrepaired dangling ``toolUse`` tail,
        which ``context_messages()`` would select and replay against a
        backend that rejects it). ``tasks_cancel`` gets this ordering for
        free through ``set_task_status`` rather than re-deriving it: the
        in-memory CANCELED transition it has already returned to the client
        is never rolled back to compensate for a failure here or in
        ``persist_messages`` — a failure only ever skips the durable write
        (RT-001).

        RT-007: a plain, synchronous ``def`` hook doing a durable write
        blocks the event loop, and WORKING is re-applied once per streamed
        chunk within a turn — several times more often than the transitions
        that actually need durability. So ``set_task_status`` flushes this
        hook by default only when ``record.task.status.state`` is in
        ``TERMINAL_STATES`` (COMPLETED/CANCELED/FAILED/REJECTED) or
        ``INTERRUPT_STATES`` (AUTH_REQUIRED/INPUT_REQUIRED — an interrupted
        task that never reaches durable storage cannot survive a restart to
        be resumed) — never for the repeated WORKING transitions. A
        subclass whose ``persist_status`` override wants the old
        every-transition granularity (e.g. to drive a live status
        dashboard) sets the ``persist_every_status = True`` class attribute
        below instead of re-deriving ``record.task.status.state`` itself.

        ``InMemoryTaskStore`` needs no override: its
        ``get()`` hands back the live record by reference, so the in-place
        mutation IS the write. A durable ``TaskStore`` whose ``get()``
        deserializes a FRESH copy from storage on every call MUST override
        this to write ``record.task.status`` back to the backing store keyed
        by ``record.task.id`` — otherwise the CANCELED transition never
        reaches storage: ``context_messages()`` filters candidates on
        ``r.task.status.state in TERMINAL_STATES``, so a cancelled task
        never becomes a continuation candidate and the repaired transcript
        ``persist_messages`` just flushed is never read back, no matter how
        faithfully ``persist_messages`` was overridden on its own.

        Takes the ``TaskRecord`` itself, for the same reason
        ``persist_messages`` does: the caller already holds the exact
        object it mutated, and a copy-on-``get()`` store has no other
        reference to that copy to resolve an id against.

        Default implementation is a no-op, so a pre-existing external
        ``TaskStore`` subclass keeps instantiating without an override —
        mirroring ``persist_messages``'s and ``interrupt_ttl_remaining``'s
        precedent: it silently keeps losing the CANCELED transition rather
        than erroring, until it adds one."""

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
        terminal task in ``context_id`` owned by ``identity``. Used by
        ``_create_task_record`` to carry prior conversation history into a
        new task started on the same context (A2A §3 contextId continuation).
        Returns an empty list when no prior terminal task exists.

        RT-004: identity-scoped exactly like ``context_reusable_messages()``
        below — **no admin api_key bypass.** ``routes/a2a.py``'s
        ``_create_task_record`` calls this method on every fresh
        ``message/send``/``:stream`` (no ``taskId``, i.e. a NEW task) and
        folds the result straight into that new task's ``record.messages``
        (see ``_create_task_record``), which is then sent to the model —
        this is ``contextId`` continuation, the SAME path a same-identity
        caller uses to continue their own thread, never a read-only
        inspection view. There is no ownership check on a bare
        ``context_id`` itself (only on an existing ``taskId`` — DESIGN.md
        §5.1's binding), so an earlier revision special-cased an admin
        api_key identity to bypass the identity filter here too; that
        bypass fed a foreign identity's transcript straight into the
        admin's own new task and from there into the model's context —
        materially more exposure than the read-only "operator task
        inspection" it was framed as, and never something a wave's own
        redteam pass may ratify as SDK policy on its own. Removed: a
        mismatched identity (admin or not) now simply sees no prior
        transcript, exactly as ``context_reusable_messages()`` already
        behaved. Genuine operator inspection of another identity's task
        remains available, safely, as a read that never seeds a new task's
        model context: ``GET /v1/tasks/{id}`` (``TaskStore.get()``'s own,
        narrower admin override, DESIGN.md §5.1). A concrete store
        overriding this method for durability must apply the same
        identity scoping, not reintroduce a bypass. See
        ``tests/test_admin_continuation_scoped_to_own_identity.py``, which
        pins this end-to-end through the live ASGI app.

        RT-007: a concrete store MUST bound how many messages it returns —
        without a cap, a long-lived thread makes every fresh (non-resume)
        request on it re-carry the FULL transcript of every prior turn into
        the new task's ``record.messages``, and the model prompt built from
        it grows unbounded for the life of the thread (the same class of
        risk ``context_reusable_messages()`` bounds on task count via
        ``MAX_REUSABLE_TASKS``, and ``routes/ag_ui.py``'s
        ``MAX_HISTORY_MESSAGES`` bounds on a different carrier). The
        in-memory store's cap is the ``InMemoryTaskStore.MAX_CONTEXT_MESSAGES``
        class attribute, defaulting to the
        ``agent_sdk.tasks.memory.MAX_CONTEXT_MESSAGES`` module constant and
        overridable per subclass. The cap MUST land on a genuine
        user-authored turn boundary — a ``role == "user"`` message with no
        ``toolResult`` block in its content — never mid-tool-round on a
        ``toolResult`` continuation (or a toolUse-carrying assistant turn)
        whose matching half was truncated away, which Bedrock's Converse API
        rejects outright. RT-002: a concrete store's cap MUST NOT collapse
        to an empty result merely because the trailing cap-sized window has
        no such boundary in it (e.g. a single task that hit its own
        ``max_turns`` without ever finishing has no boundary later than its
        seed message) — that silently disables contextId continuation for
        the whole thread rather than truncating it. Fall back to the
        nearest earlier boundary instead, and log the fallback; see
        ``InMemoryTaskStore``'s ``_turn_boundary_slice`` for the reference
        implementation."""
        return []

    def context_reusable_messages(
        self, context_id: str, identity: Identity | None = None
    ) -> Sequence[dict[str, Any]]:
        """Return the ``__resolved__`` marker content of terminal tasks in
        ``context_id`` owned by ``identity``, oldest first (RT-001).

        Used only to seed ``run_loop``'s ``resolved_index`` (GH-148 /
        RT-A-004) on a transport whose own ``TaskRecord.messages`` does not
        itself accumulate prior-task history the way A2A's does — AG-UI
        (``routes/ag_ui.py``) is the only current caller. Unlike
        ``context_messages()``, which replays only the SINGLE most recent
        terminal task (correct there, since A2A folds each new task's
        ``messages`` from the previous one, so history already accumulates
        transitively), this method scans every terminal task in the context:
        an AG-UI ``TaskRecord`` never inherits a prior run's ``messages``, so
        a ``__resolved__`` marker folded in run N would otherwise stop being
        visible the moment any later, unrelated run N+1 becomes the newest
        terminal task — decaying after exactly one intervening run instead
        of surviving for the life of the conversation.

        RT-009: never honours an admin api_key identity's cross-identity
        override — this is a covert side channel with no user-visible frame,
        so admin privilege must not leak another identity's resolved values
        into a caller's tool arguments. ``context_messages()`` above is
        identity-scoped the same way (RT-004: it no longer special-cases
        admin api_key identities either). Returns an empty list when no
        prior terminal task exists.

        RT-010: ``scan_resolved`` (the sole consumer of this method's
        return value) reads nothing out of a message besides a
        ``__resolved__`` marker's own ``json`` block, so a concrete store
        MUST return only that content (e.g. via
        ``agent.reuse.extract_resolved_markers``), never whole transcripts
        — and MUST bound how many terminal tasks it scans per call (newest
        first; the in-memory store's cap is the
        ``InMemoryTaskStore.MAX_REUSABLE_TASKS`` class attribute, defaulting
        to the ``agent_sdk.tasks.memory.MAX_REUSABLE_TASKS`` module constant
        and overridable per subclass — RT-006), the same class of
        unbounded-growth risk
        ``routes/ag_ui.py``'s ``MAX_HISTORY_MESSAGES`` bounds on a
        different carrier. A long-lived thread's full history must never be
        re-walked and re-allocated on every fresh request against it."""
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
