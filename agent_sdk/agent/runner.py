"""Task worker — bridges loop events to A2A task state (DESIGN.md §5.1/§5.2).

One worker per task, regardless of which protocol started it. It is the only
writer of the task record: it folds loop events into the canonical A2A
``Task`` (status, history, artifacts) and publishes ``StreamItem``s to the
record's subscribers. Each item carries the pre-built A2A wire frame (used by
A2A SSE consumers as-is) AND the raw loop event (mapped by the AG-UI route's
per-request state machine) — interrupts therefore resume identically across
protocols.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from pydantic import BaseModel

from ..auth.context import ResumeEnvelope, bind_identity
from ..a2ui.translator import A2uiCapabilities, split_a2ui_delivery, translate
from ..common.json_strict import dumps_strict, scrub_unencodable
from ..common.tz import load_zone, valid_timezone
from ..models.a2a import (
    Artifact,
    DataPart,
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TERMINAL_STATES,
    INTERRUPT_STATES,
    TextPart,
)
from ..models.content_types import A2UI_MIME_TYPE, ContentModel
from ..models.errors import AgentError, ErrorCategory, WireError
from ..tasks.store import TaskRecord, TaskStore
from .deferred import DeferredEvent
from .registry import match_emits_type
from .events import (
    ArtifactEvent,
    AuditEvent,
    DoneEvent,
    InterruptEvent,
    NoteEvent,
    ProgressEvent,
    TextEvent,
    ToolProgressEvent,
    ToolResultEvent,
    UsageEvent,
)
from .loop import (
    LoopPolicies,
    bridge_trailing_user,
    close_dangling_tool_use,
    fold_result_content,
    jsonable_reuse_value,
    run_loop,
)
from .model_client import ModelClient
from .registry import ToolRegistry, resolve_deferred_result
from .reuse import RESOLVED_MARKER_KEY, Reusable
from .skills import SkillsRegistry
from ..sources import SourceAdapter

logger = logging.getLogger(__name__)

# RT-W025-004: module-level set that holds strong references to deferred
# background tasks, following the same pattern as contrib/webhooks/dispatch.py.
# Python 3.12+ event-loop keeps only *weak* references to tasks; without a
# strong reference the GC can silently discard a running background task and
# leave the A2A task stuck in WORKING state forever.
_background_tasks: set[asyncio.Task[Any]] = set()


@dataclass(slots=True)
class StreamItem:
    frame: dict[str, Any] | None  # A2A wire frame, ready to send
    event: Any  # raw loop event (AG-UI mapping) — None for synthetic frames
    final: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agent_message(
    record: TaskRecord, text: str, metadata: dict[str, Any] | None = None
) -> Message:
    # w050 RT-001 (round 6): every agent Message the runner builds lands in
    # task status and/or history, and every later read serializes it with
    # dumps_strict. Model text, progress/note/tool-progress messages and
    # interrupt metadata can all carry a lone surrogate (an upstream API that
    # cut an emoji in half), so replace those code points with U+FFFD here,
    # before the message exists. set_task_status re-applies the rule for any
    # message built elsewhere.
    text = scrub_unencodable(text)
    metadata = scrub_unencodable(metadata)
    return Message(
        role="agent",
        parts=[TextPart(text=text)],
        messageId=uuid.uuid4().hex,
        taskId=record.task.id,
        contextId=record.task.context_id,
        metadata=metadata,
    )


def _status_frame(record: TaskRecord, *, final: bool = False) -> dict[str, Any]:
    """Build the A2A status frame from ``record.task.status`` verbatim.

    Carries no ``metadata`` param: the AuditEvent branch below needs a
    message-free status (RT-A-003) and builds its own TaskStatusUpdateEvent
    inline instead of calling this helper, so a metadata hook here would sit
    unused and invite a caller to bypass that rule by accident.
    """
    return TaskStatusUpdateEvent(
        taskId=record.task.id,
        contextId=record.task.context_id,
        status=record.task.status,
        final=final,
    ).wire()


def _scrub_model(model: Any) -> Any:
    """Rebuild a pydantic ``model`` with every surrogate code point replaced
    by U+FFFD; return it unchanged (same object) when it has none."""
    if model is None:
        return None
    dumped = model.model_dump(by_alias=True, mode="python")
    scrubbed = scrub_unencodable(dumped)
    if scrubbed is dumped:
        return model
    return type(model).model_validate(scrubbed)


def set_task_status(
    record: TaskRecord,
    state: TaskState,
    message: Message | None = None,
    *,
    error: WireError | None = None,
    store: "TaskStore | None" = None,
    repaired: bool = True,
) -> None:
    """RT-B-008/RT-004 (routes/a2a.py RT-004 follow-up): the single choke
    point for every in-place ``record.task.status`` mutation the SDK
    makes — WORKING, COMPLETED, FAILED, AUTH_REQUIRED, INPUT_REQUIRED, and
    CANCELED — across ``run_task_worker``, ``_run_deferred_background``, AND
    ``routes/a2a.py``'s ``tasks_cancel``. Flushes the new status via
    ``TaskStore.persist_status`` (C-005) when ``store`` is given, the same
    centralising pattern ``repair_dangling_tool_use`` (C-018) already uses
    for the ``persist_messages`` flush, rather than requiring each call site
    to remember its own follow-up call and its own gating. Before RT-004,
    ``tasks_cancel`` mutated ``record.task.status`` directly and hand-rolled
    an equivalent, divergent try/except pair around its own
    ``persist_messages``/``persist_status`` flush — including a rollback of
    the CANCELED transition on a flush failure that defeated every
    ``state in TERMINAL_STATES`` guard elsewhere in this module (RT-001);
    routing it through this one function closes both gaps at once.

    RT-B-001 (round 2): also the single choke point that flushes
    ``record.messages`` (``TaskStore.persist_messages``) on every TERMINAL
    transition, not only the ones a caller happens to route through
    ``repair_dangling_tool_use`` first. Before this, ``persist_messages``'s
    only call site in the SDK was that out-of-loop repair helper, which
    never runs on a normal completion (there is no dangling ``toolUse`` tail
    to repair) — so RT-B-008's own fix above made a durable store correctly
    observe the COMPLETED/FAILED status on the happy path while the
    transcript behind it never reached durable storage at all, and
    ``context_messages()`` then replayed a stale (often empty) history on
    the next ``contextId`` continuation. On a terminal transition,
    ``persist_messages`` is flushed FIRST, and ``persist_status`` runs only
    if that flush actually succeeded — a failure leaves the durable record
    correctly non-terminal (never a continuation candidate) rather than
    durably terminal over a transcript that never arrived; the in-memory
    ``record.task.status`` mutation above is never rolled back to compensate
    (RT-001) — the caller's own wire response already committed to it.

    RT-007 (debug round 4): this is the SINGLE ``persist_messages`` flush
    point for the repair callers too (cancel, the deferred-background
    success/failure paths, both ``run_task_worker`` terminal exception
    handlers). ``repair_dangling_tool_use_safe`` used to run its own flush
    first, so every terminal transition through a repair issued TWO durable
    writes of the same unchanged record; the hook is a plain synchronous
    ``def`` whose durable write blocks the event loop, which is the whole
    reason WORKING flushes were gated away below. That wrapper no longer
    takes a ``store`` at all — see its docstring.

    RT-B-104: ``persist_messages`` is flushed under this same fail-closed
    ordering for ``INTERRUPT_STATES`` too, not only ``TERMINAL_STATES``.
    ``tasks/store.py``'s ``persist_status`` docstring justifies its own
    interrupt-state flush as "an interrupted task that never reaches durable
    storage cannot survive a restart to be resumed" — but status alone is
    not a coherent record without the matching ``record.messages``
    transcript alongside it; a durable store that observed
    AUTH_REQUIRED/INPUT_REQUIRED without that transcript had nothing
    coherent to resume from restart. (``record.pending_tool_results`` is
    NOT part of that transcript flush — it stays runtime-only, never
    serialized, exactly like ``worker``/``resume_future``; see
    ``TaskStore.persist_messages``'s own docstring, ``tasks/store.py``.)
    Both flushes now share one condition (below) so the two can never drift
    apart again.

    Guarded (RT-B-003): a failing durable write degrades to an unpersisted
    status rather than raising out of a hot status-transition path.

    RT-007: ``persist_status`` is a plain, synchronous ``def`` — a durable
    subclass doing a network write inside it blocks the event loop. Flushing
    it on EVERY transition (as RT-B-008 above first did) therefore hammers
    that write on the SSE hot path: WORKING is re-applied once per streamed
    ``TextEvent``/``ProgressEvent``/``NoteEvent``/``ToolProgressEvent``
    within a single model turn, several times more often than the terminal
    transition it actually needs to observe. This function now flushes
    ``persist_status`` by default only for the transitions durability
    actually depends on — ``TERMINAL_STATES`` (unchanged) and
    ``INTERRUPT_STATES`` (AUTH_REQUIRED/INPUT_REQUIRED: an interrupted task
    that never reaches durable storage cannot survive a restart to be
    resumed) — never for the repeated WORKING transitions. A store that
    wants the old every-transition granularity opts back in by setting
    ``TaskStore.persist_every_status = True`` on its subclass; see that
    attribute's docstring in ``tasks/store.py``.

    RT-001 (agent/runner.py review): ``repaired`` (default ``True``, so every
    call site that never routed through a repair — WORKING, the InterruptEvent
    branch, a normal DoneEvent completion — keeps flushing exactly as before)
    is threaded by the five callers that call ``repair_dangling_tool_use_safe``
    first, passing its return value straight through. It means exactly one
    thing: whether ``record.messages`` is SAFE TO PERSIST. Nothing about a
    dangling ``toolUse`` tail makes a store's ``persist_messages`` write raise
    — a caller that swallowed a repair failure and called this function
    unconditionally anyway would have this flush happily persist the STILL
    unrepaired transcript and then durably commit the terminal/interrupt
    status over it, defeating the whole point of gating ``persist_status`` on
    ``persist_messages`` above. ``repaired=False`` skips BOTH flushes entirely
    — the in-memory ``record.task.status`` mutation above still always
    commits (the caller's own wire response has already committed to it,
    same rationale as every other guard in this function); only the durable
    copy is deliberately left stale rather than corrupted.

    RT-001 (debug round 4): ``repaired`` must NEVER be used to report a
    failed durable WRITE — only a failed in-memory repair. A durable write
    failure is already handled correctly right here (the ``flushed`` gate
    below), and routing it through this parameter instead made a transient
    ``persist_messages`` blip skip the very retry-and-gate path that was
    designed for it, permanently stranding the durable record non-terminal.
    That is why ``repair_dangling_tool_use_safe`` no longer flushes at all.
    """
    # stateTransitionHistory (A2A v0.3.0 §2) is not implemented: the Task
    # model has no such field and the card advertises stateTransitionHistory=false.
    # w050 RT-001 (round 6): this is the one place status is committed, so
    # the "every stored string must encode as UTF-8" rule is applied here,
    # not only at ingress and the artifact gate. Otherwise a single bad
    # status message made GET /v1/tasks/{id} and GET /v1/tasks answer 502
    # for the whole identity.
    message = _scrub_model(message)
    error = _scrub_model(error)
    record.task.status = TaskStatus(state=state, message=message, timestamp=_now(), error=error)
    if store is None:
        return
    if not repaired:
        logger.error(
            "skipping durable status flush for task %s: transcript repair "
            "did not land",
            record.task.id,
        )
        return
    flushed = True
    # RT-B-104: same durability-need condition for both flushes — a store
    # observing a terminal or interrupt status without the transcript behind
    # it has nothing coherent to replay on the next continuation/resume.
    needs_durability = state in TERMINAL_STATES or state in INTERRUPT_STATES
    if needs_durability:
        try:
            store.persist_messages(record)
        except Exception as exc:
            flushed = False
            logger.error(
                "persist_messages failed for task %s error_type=%s",
                record.task.id,
                type(exc).__name__,
            )
    should_persist_status = needs_durability or store.persist_every_status
    if flushed and should_persist_status:
        try:
            store.persist_status(record)
        except Exception as exc:
            logger.error(
                "persist_status failed for task %s error_type=%s",
                record.task.id,
                type(exc).__name__,
            )


def _validate_a2ui_wire(payload: "ContentModel", a2ui_messages: list[Any]) -> None:
    """SC-D1: Structural assertion on translate() output + domain-card wire() value.

    Standard Profile types use _Wire.wire() (Pydantic-validated), so this
    primarily catches domain cards whose wire() returns a non-conformant value.
    Raises ValueError before delivery rather than silently sending malformed data.

    RT-004's open/close-split emptiness guard lives in ``build_artifact``
    (right after its own single ``split_a2ui_delivery`` call) rather than
    here, so the split is computed exactly once per artifact instead of
    once here and again in ``build_artifact`` (RT-002).
    """
    from ..models.content_types import CATALOG_ID as _CATALOG_ID  # local to avoid circulars
    from ..models.content_types import MarketBriefing

    cls = type(payload)
    label = f"{cls.__name__!r} ({payload.data_type!r})"

    # Structural assertion on the a2ui_messages list itself.
    if not (isinstance(a2ui_messages, list) and len(a2ui_messages) > 0):
        raise ValueError(
            f"Content type {label}: translate() must return a non-empty list of dicts; "
            f"got {type(a2ui_messages).__name__!r}"
        )
    if not all(isinstance(m, dict) and "version" in m for m in a2ui_messages):
        raise ValueError(
            f"Content type {label}: each A2UI message must be a dict with a 'version' key; "
            f"malformed translate() output detected"
        )

    # For domain cards (non-standard-catalog types): also validate wire() output
    # directly. Standard Profile types are Pydantic-validated via _Wire.wire() /
    # model_dump(exclude_none=True), so structural conformance is guaranteed without
    # re-checking here.
    if cls.catalog_id != _CATALOG_ID:
        try:
            wire_val = payload.wire()
        except Exception as exc:
            # SI-2: report only the exception's type, never str(exc) — the
            # domain card's wire() may have embedded upstream/tool payload
            # content in its own message. `from None` (not `from exc`) is
            # required too: chaining preserves exc as __cause__, and a
            # transport that logs this via logger.exception() (AG-UI's
            # stream handler) walks the full chain and reprints exc's
            # message regardless of what this ValueError's own text says.
            raise ValueError(
                f"Domain card {label}: wire() raised {type(exc).__name__}"
            ) from None
        if isinstance(payload, MarketBriefing):
            if not isinstance(wire_val, str) or not wire_val:
                raise ValueError(
                    f"Domain card {label}: wire() must return a non-empty str; "
                    f"got {type(wire_val).__name__!r}"
                )
        elif not isinstance(wire_val, dict) or not wire_val:
            # SI-2: only the type name — never a repr of the payload itself.
            raise ValueError(
                f"Domain card {label}: wire() must return a non-empty dict; "
                f"got {type(wire_val).__name__!r}"
            )


def split_a2ui_delivery_validated(
    payload: "ContentModel", a2ui_messages: list[Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """SC-D1 + RT-004, as one call: validate structure, split into (open,
    close), and raise if the open half is empty.

    The single boundary both delivery transports (A2A ``build_artifact``,
    AG-UI's ``ArtifactEvent`` branch in ``routes/ag_ui.py``) MUST call
    between ``translate()`` and delivering the split arrays, so a malformed
    ``translate()`` output — e.g. a custom domain-card ``translate()`` that
    is entirely ``deleteSurface`` — is rejected identically on every
    transport instead of only on whichever one remembers to check (RT-001).
    """
    _validate_a2ui_wire(payload, a2ui_messages)
    open_messages, close_messages = split_a2ui_delivery(a2ui_messages)
    if not open_messages:
        raise ValueError(
            f"Content type {type(payload).__name__!r} "
            f"({payload.data_type!r}): translate() output split into "
            "an empty open sequence (deleteSurface with no "
            "accompanying create/populate messages); malformed "
            "translate() output"
        )
    return open_messages, close_messages


def build_text_only_artifact(event: ArtifactEvent) -> Artifact:
    """GH-225: TextPart-only artifact for a declared-``emits`` tool whose result
    matches no declared member — no A2UI card, no DataPart."""
    payload = event.model
    text = payload.to_plain_text() if isinstance(payload, ContentModel) else str(payload)
    artifact = Artifact(
        artifactId=uuid.uuid4().hex,
        name=event.tool_name,
        parts=[TextPart(text=text)],
        metadata={"data_type": event.tool_name, "tool_name": event.tool_name},
    )
    try:
        dumps_strict(artifact.wire())
    except (TypeError, ValueError) as exc:
        raise ValueError("text-only artifact is not JSON-serializable") from exc
    return artifact


def build_artifact(
    event: ArtifactEvent, capabilities: A2uiCapabilities
) -> Artifact:
    """Dual-part structured artifact: TextPart fallback + DataPart payload (§5.1).
    ContentModel payloads always emit both parts. When the A2UI capability is
    active the DataPart carries the A2UI message array; when inactive it carries
    the raw model dump so plain A2A clients can extract structured data without
    parsing the TextPart (A2A §D3). Non-ContentModel BaseModel and plain-value
    payloads follow the same dual-part contract."""
    payload = event.model
    metadata: dict[str, Any] = {"data_type": event.data_type, "tool_name": event.tool_name}
    if isinstance(payload, ContentModel):
        parts: list[Any] = [TextPart(text=payload.to_plain_text())]
        a2ui_messages = translate(payload, capabilities=capabilities)
        if a2ui_messages is not None:
            # SC-D1 + RT-004: validate structure, split into open/close, and
            # reject an empty open sequence — the one shared boundary both
            # transports call (RT-001; see split_a2ui_delivery_validated).
            # Computed exactly ONCE and reused for both the emptiness guard
            # and the DataPart split itself (RT-002).
            open_messages, close_messages = split_a2ui_delivery_validated(payload, a2ui_messages)
            metadata["mimeType"] = A2UI_MIME_TYPE
            # Critical protocol-conformance fix: deleteSurface must never
            # share a delivered array with its own surface's create/populate
            # messages — a spec-conformant Path-A renderer folds one
            # delivered array atomically and paints once after the fold, so
            # a bundled deleteSurface would unmount the surface before it
            # ever painted (see split_a2ui_delivery() docstring). Deliver the
            # open and close arrays as two DataParts, open first, each
            # self-describing via its own mimeType. DataPart.data is wrapped
            # as {"messages": [...]} rather than a bare array to satisfy A2A
            # v0.3.0's DataPart.data typing (types.ts DataPart.data:
            # {[key: string]: any}, required — an object, confirmed against
            # the pinned tag, not just this SDK's own prior claim; GH-128).
            # This is an SDK-specific tradeoff, NOT a canonical A2UI
            # convention: A2UI v0.9.1's own A2A binding (google/A2UI
            # specification/v0_9_1/docs/a2ui_extension_specification.md,
            # "Data encoding") says data "MUST be an array of messages" — a
            # bare array — and defines no data.messages wrapper. A strictly
            # spec-conformant third-party A2UI Path-A renderer with no
            # knowledge of this SDK will not find messages at `data` and
            # will render nothing; this SDK's own console/testing clients
            # unwrap data.messages and are unaffected. The deviation is
            # wire-discoverable via the agent card's `dataEncoding` A2UI
            # extension param (agent_sdk/a2ui/catalog.py::a2ui_extension(),
            # mirroring deleteSurfaceSemantics/GH-113). See LRN-134 for the
            # full citation trail.
            parts.append(
                DataPart(
                    data={"messages": open_messages},
                    metadata={"mimeType": A2UI_MIME_TYPE},
                )
            )
            if close_messages:
                parts.append(
                    DataPart(
                        data={"messages": close_messages},
                        metadata={"mimeType": A2UI_MIME_TYPE},
                    )
                )
        else:
            # P6-02 / A2A §D3: always emit a DataPart for structured payloads,
            # even when A2UI is not active, so plain A2A clients can consume
            # the model dump without screen-scraping the TextPart fallback.
            dump = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
            parts.append(
                DataPart(
                    data=dump,
                    metadata={"data_type": event.data_type, "tool_name": event.tool_name},
                )
            )
    elif isinstance(payload, BaseModel):
        dump = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
        parts = [
            TextPart(text=str(dump)),
            DataPart(data=dump, metadata=dict(metadata)),
        ]
    else:
        # SC-A2: plain scalar — emit TextPart fallback + DataPart so plain A2A
        # clients can extract structured data without screen-scraping (A2A §D3).
        parts = [
            TextPart(text=str(payload)),
            DataPart(
                kind="data",
                data={"value": payload},
                metadata={"mimeType": "application/json"},
            ),
        ]
    artifact = Artifact(
        artifactId=uuid.uuid4().hex,
        name=event.data_type,
        parts=parts,
        metadata=metadata,
    )
    # RT-001 (ROOT CAUSE): _Wire.wire() dumps in Python mode (model_dump WITHOUT
    # mode="json"), so a DataPart whose `data` holds a non-JSON-serializable
    # value survives .wire() UNCHANGED and only raises later at the UNGUARDED
    # sse_data() json.dumps (routes/a2a.py) — killing the SSE stream AFTER the
    # task has already transitioned to COMPLETED (false success). The plain-
    # scalar branch above is the common offender: it embeds the raw resolved
    # tool value directly (DataPart(data={"value": payload})) with NONE of the
    # model_dump(mode="json") coercion the BaseModel branches apply; the A2UI /
    # domain-card branches can leak one too. Validate serializability HERE, at
    # the single point every branch converges, and raise ValueError so BOTH
    # build_artifact call sites — the synchronous run_task_worker ArtifactEvent
    # branch and the deferred background builder — fail the task
    # deterministically with -32006 ("invalid agent response") BEFORE any false
    # COMPLETED or dead stream. This makes the "deterministic FAILED" guarantee
    # true for a non-serializable resolved value, not just a build_artifact
    # raise. SI-2: this ValueError's text never reaches the wire (both call
    # sites emit fixed strings), so no payload detail is echoed.
    # w050 RT-001: use dumps_strict, the SAME helper every writer uses, so a
    # string that is not UTF-8-encodable (a lone surrogate) fails HERE too.
    # A plain json.dumps let it through, the task committed COMPLETED, and
    # every later read of it (GET /v1/tasks/{id}, GET /v1/tasks) failed.
    try:
        dumps_strict(artifact.wire())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"artifact for {event.data_type!r} is not JSON-serializable"
        ) from exc
    return artifact


def repair_dangling_tool_use(
    record: "TaskRecord",
    *,
    default_content: list[dict[str, Any]],
    default_status: str = "error",
    overrides: dict[str, tuple[list[dict[str, Any]], str]] | None = None,
    bridge_text: str | None = None,
    store: "TaskStore | None" = None,
) -> None:
    """GH-150/RT-002: close out a dangling assistant ``toolUse`` tail in
    ``record.messages``.

    ``run_loop`` folds a turn's assistant ``toolUse`` message into
    ``record.messages`` before running that turn's per-tool-call loop
    (``agent/loop.py``); the matching ``toolResult`` message is appended only
    once every tool call in the turn finishes normally. Any exit that leaves
    the record mid-turn — a task cancelled while a tool call is still in
    flight (GH-150: ``routes/a2a.py``'s ``tasks_cancel``) or a
    ``long_running`` tool's ``DeferredEvent`` handoff resolving in the
    background (RT-002: ``_run_deferred_background`` below) — leaves
    ``record.messages`` ending on that assistant ``toolUse`` message with no
    matching ``toolResult``. ``context_messages()`` (§3 contextId
    continuation) replays that transcript verbatim on the next turn, which
    Converse-API-shaped backends (Bedrock) reject outright.

    Detects that unresolved toolUse tail — last message is ``assistant``
    with one or more ``toolUse`` blocks — and appends ONE synthetic
    ``toolResult`` per dangling ``toolUseId``: ``overrides[tool_use_id]``
    when present (the caller's own resolved ``(content, status)`` for that
    specific call — e.g. the deferred tool's actual result), else
    ``(default_content, default_status)``. A no-op when the last message
    isn't a dangling assistant toolUse turn, so callers may call this
    unconditionally.

    RT-001 (GH-147 AC3): every caller of this helper repairs ``messages``
    OUTSIDE of ``run_loop`` — at a point ``run_loop`` will never run again
    for this task (a task cancelled mid-tool-call, ``routes/a2a.py``'s
    ``tasks_cancel``; a ``long_running`` tool's ``DeferredEvent`` handoff
    resolving in the background, ``_run_deferred_background`` below) — so
    none of ``run_loop``'s own ``bridge_trailing_user`` call sites ever run
    to fix up the synthetic ``toolResult`` this function just appended.
    Bridging HERE, once, after the append, covers every current and future
    caller identically instead of requiring each call site to remember its
    own follow-up call (the exact drift RT-001 found: two of three call
    sites had it, one — the cancel path — did not).

    RT-003 (GH-147 AC3): the bridge must run on every exit, not only the
    append-a-synthetic-toolResult path above. ``tasks_cancel`` calls this
    unconditionally as its ONLY bridge for the cancelled task's transcript
    (the worker's own ``except asyncio.CancelledError: raise`` deliberately
    leaves ``record.messages`` untouched). Two shapes reach this function
    with ``messages`` already ending on 'user' and nothing to repair — the
    last message isn't an assistant toolUse turn at all — and previously hit
    an early ``return`` before ``bridge_trailing_user`` ever ran: cancelling
    while the model is still "thinking" on turn 1 (the last message is the
    original inbound 'user' turn) and cancelling between turns after a
    completed tool round (the last message is that round's 'user' toolResult
    fold). Both left a CANCELED — terminal, hence replayable — task's
    ``record.messages`` ending on 'user'. Structured as a single exit so the
    guarantee holds unconditionally: repair the dangling toolUse tail when
    there is one, then always bridge.

    RT-B-001: a turn can contain SEVERAL tool calls, and the ones that
    already completed before the mid-turn exit have real results — their
    ``toolResult`` blocks are in ``record.pending_tool_results`` (populated
    by ``run_loop`` as each call finishes; see ``loop.py``'s
    ``pending_results``). Those are applied here in preference to
    ``default_content``, so only a call that genuinely never produced a
    result falls back to the synthetic default. Without this, a two-call
    turn whose second call deferred (or was cancelled, or raised) told the
    model on the next contextId continuation that the FIRST call — which
    succeeded, and whose real result had already reached the client as a
    ``ToolResultEvent`` — returned nothing. An explicit ``overrides`` entry
    still wins over a pending block for the same id (the caller knows the
    outcome of the specific call it is resolving); the pending list is
    consumed (cleared) once folded so a later repair cannot replay it.

    RT-008: ``bridge_text`` is forwarded verbatim to ``bridge_trailing_user``
    (``None`` keeps its own "(no response)" default). A caller whose repair
    followed a tool call that actually succeeded — the deferred (GH-87)
    background success path below — passes its own fixed, SDK-authored
    string so the synthetic assistant turn doesn't misreport a genuine
    result as "(no response)"; every failure/cancel caller leaves this at
    its default, since those exits really did produce no response.

    RT-005: ``store``, when given, is handed the repaired ``record`` via
    ``TaskStore.persist_messages`` once, after the repair/bridge above have
    both run. RT-007 (debug round 4): this is now a DIRECT-CALLER-ONLY
    affordance — the SDK's own five out-of-loop callers (cancel, the
    deferred-background paths, both ``run_task_worker`` terminal exception
    handlers) all route through ``repair_dangling_tool_use_safe`` below,
    which takes no ``store`` and issues no flush of its own; ``set_task_status``
    is the SDK's single production flush point for ``persist_messages`` (see
    that function's own RT-007 paragraph and ``repair_dangling_tool_use_safe``'s
    RT-001/RT-007 paragraph). This parameter remains for a caller that
    reaches this function directly, bypassing the guarded wrapper —
    ``docs/deployment.md``'s "Custom TaskStore durability" section points a
    durable-store author here as the pattern to mirror for their own
    restart-time repair, and direct-call test coverage exercises it in
    isolation (``tests/test_rt005_gh150_taskstore_persist_messages_hook.py``).
    ``InMemoryTaskStore``'s default no-op needs nothing further (its
    ``get()`` already returns the live object this function mutated); a
    durable ``TaskStore`` whose ``get()`` deserializes a copy per call MUST
    override the hook or this repair never reaches storage (see
    ``TaskStore.persist_messages``'s docstring). Omitting ``store`` (every
    current SDK call site) simply skips the flush.

    RT-B-007 (RT-B-206 follow-up): each synthetic ``toolResult`` block
    DEEP-copies its ``content`` list rather than embedding
    ``default_content``/a pending or override entry by reference — several
    dangling ids in the same turn falling back to the same
    ``default_content`` would otherwise all point at the exact same list
    object, still reachable by the caller, so a later mutation of it (or of
    any one block by a store's serializer) would silently rewrite every one
    of those transcript entries at once. RT-B-206: the original fix used a
    SHALLOW ``list(content)`` copy — a new outer list whose elements were
    still the same shared dicts, so mutating a BLOCK in place (rather than
    the list itself) still rewrote every dangling id's entry. A deep copy
    closes that too; these lists are one or two small dicts per dangling id,
    on a path that runs once per abnormal task exit, so the cost is
    negligible.

    RT-B-008 (superseded by RT-005 — see ``agent/loop.py::close_dangling_
    tool_use``'s matching paragraph and ``tests/test_rt005_non_dict_tail_
    unreadable_gate.py``): a non-dict tail entry (a durable store
    deserialising loosely, or a future caller appending something other than
    a plain dict) originally degraded to "nothing to repair" rather than
    raising. That let ``repair_dangling_tool_use_safe`` report ``True``
    (safe to persist) for a transcript whose tail could not even be
    confirmed clean — the exact fail-open ``set_task_status``'s ``repaired``
    gate exists to prevent, same class of gap RT-001/RT-004 below closed one
    level deeper. ``close_dangling_tool_use`` now raises
    ``DanglingToolUseUnreadable`` for this shape too.

    RT-001 (agent/runner.py review) / RT-004 (correction): the guard above
    only reached one level deep — a tail block whose own ``"toolUse"`` value
    is present but is not itself a dict (or is a dict missing
    ``"toolUseId"``), or a non-list ``"content"`` value, used to raise
    ``TypeError``/``KeyError`` out of the id-extraction comprehension. An
    intermediate fix guarded those the same way as the outer RT-B-008 case —
    skip the block, treat the tail as "nothing to repair" — but that
    silently turned a genuinely dangling, unrepairable ``toolUse`` tail into
    the SAME return value as a confirmed-clean one, letting
    ``repair_dangling_tool_use_safe`` report ``True`` (safe to persist) over
    a transcript still ending on that unrepaired tail. This function lets
    ``close_dangling_tool_use`` raise ``DanglingToolUseUnreadable`` for both
    that one-level-deep case AND the outer non-dict-tail case (RT-005)
    instead of swallowing either — the raise propagates out of this function
    uncaught, so ``repair_dangling_tool_use_safe``'s existing broad ``except
    Exception`` reports the correct "not safe to persist" outcome for it,
    exactly as it already does for any other in-memory repair failure.
    """
    messages = record.messages
    pending: dict[str, tuple[list[dict[str, Any]], str]] = {}
    for block in record.pending_tool_results:
        if not isinstance(block, dict):
            continue
        tr = block.get("toolResult")
        if isinstance(tr, dict) and "toolUseId" in tr:
            pending[tr["toolUseId"]] = (
                tr.get("content", default_content),
                tr.get("status", default_status),
            )
    # RT-003 (debug round 4): the fold itself now lives in
    # ``loop.py::close_dangling_tool_use`` — ONE implementation shared with the
    # read side (``bridge_context_messages``), which has to re-assert this same
    # invariant on a transcript a TaskStore subclass hands back and previously
    # re-asserted only the trailing-``user`` half of it. An explicit override
    # still wins over a pending block for the same id (the caller knows the
    # outcome of the specific call it is resolving), which is what merging
    # overrides ON TOP of pending expresses.
    close_dangling_tool_use(
        messages,
        default_content=default_content,
        default_status=default_status,
        resolved={**pending, **(overrides or {})},
    )
    record.pending_tool_results.clear()
    bridge_trailing_user(messages, bridge_text)
    if store is not None:
        store.persist_messages(record)


def repair_dangling_tool_use_safe(
    record: "TaskRecord",
    *,
    default_content: list[dict[str, Any]],
    default_status: str = "error",
    overrides: dict[str, tuple[list[dict[str, Any]], str]] | None = None,
    bridge_text: str | None = None,
) -> bool:
    """RT-B-002/RT-003 (routes/a2a.py RT-003 follow-up): the one guarded
    public entry point every out-of-loop caller of ``repair_dangling_tool_use``
    (C-018) uses — ``tasks_cancel`` (``routes/a2a.py``), ``_fail`` below, the
    deferred background success path, and ``run_task_worker``'s ``except
    AgentError``/``except Exception`` handlers — rather than each hand-rolling
    its own try/except around the same call (the exact drift RT-003 found:
    ``tasks_cancel`` carried a second copy with different log text and its own
    ad hoc success flag). Four of the five callers sit BEFORE the try/finally
    that guarantees their own terminal transition, publish, and
    ``close_streams``/stream teardown — an unguarded raise here would skip
    all of that, stranding the task WORKING (or, for ``tasks_cancel``,
    mid-response) with its streams never sentinel-closed.

    RT-003 (routes/a2a.py review, GH-150 follow-up) / RT-004 (restored after
    an intermediate regression — see ``repair_dangling_tool_use``'s own
    RT-001/RT-004 paragraph): the append/bridge mutation of
    ``record.messages`` CAN itself fail — a malformed dangling ``toolUse``
    block (e.g. its ``"toolUse"`` value is not a dict, or is missing
    ``"toolUseId"``, from a durable store deserialising loosely or a future
    caller appending something unexpected) raises
    ``agent.loop.DanglingToolUseUnreadable`` inside ``repair_dangling_tool_use``
    before it appends anything, leaving ``record.messages`` exactly as it
    was: still ending on the dangling ``toolUse`` tail. That is exactly what
    this guard has to report to its caller, because ``set_task_status``'s
    own ``persist_messages`` flush (its RT-B-001 durability gate) would
    otherwise durably persist that still-broken transcript and commit the
    terminal status over it.

    ``default_status`` (RT-B-107) forwards verbatim to
    ``repair_dangling_tool_use``'s own parameter of the same name (default
    ``"error"``, matching that function's default) — added so a caller
    needing a non-``"error"`` default status is not forced back onto the
    unguarded ``repair_dangling_tool_use`` to get one, reintroducing the
    per-call-site try/except drift this wrapper exists to remove.

    Returns exactly one thing: whether ``record.messages`` is now in a state
    that is SAFE TO PERSIST. ``True`` — the in-memory repair landed (or there
    was nothing to repair). ``False`` — the append/bridge step raised, so
    ``record.messages`` is untouched and still ends on the dangling
    ``toolUse`` tail. Every one of the five call sites passes this straight
    through as ``set_task_status``'s ``repaired`` kwarg, whose gate means
    precisely that (see that function's docstring).

    RT-001/RT-007 (debug round 4): this wrapper takes NO ``store`` and does
    NO durable flush of its own. It used to take ``store`` and run
    ``store.persist_messages`` as a second guarded stage, folding that
    stage's failure into the SAME boolean as an in-memory repair failure —
    two materially different outcomes reported through one signal. Because
    each call site threads that boolean into ``set_task_status(...,
    repaired=...)``, and ``repaired=False`` there skips BOTH durable flushes,
    a single transient ``persist_messages`` failure (a network blip on a
    durable subclass) permanently prevented the terminal status from ever
    reaching storage — leaving the durable record non-terminal forever, the
    exact stuck-task condition ``_run_deferred_background``'s comments claim
    the design rules out. ``set_task_status`` already owns the correct
    durable path for every one of these callers: it flushes
    ``persist_messages`` first and gates ``persist_status`` on that flush
    having actually landed. Removing the flush from here makes the boolean
    unambiguous, leaves exactly ONE ``persist_messages`` write per terminal
    transition instead of two (RT-007: these are plain synchronous ``def``
    hooks whose durable writes block the event loop — the reason WORKING
    flushes were gated away in the first place), and puts the repair paths on
    the identical durable path as the non-repair ones (a normal ``DoneEvent``
    completion). ``repair_dangling_tool_use``'s own ``store`` parameter and
    single-flush-point contract are unchanged for direct callers.

    ``tasks_cancel`` (RT-B-106, ``routes/a2a.py``) additionally logs its own
    warning pointing back at this function's log line, since its own HTTP
    response has already committed to reporting the task canceled either way.
    """
    try:
        repair_dangling_tool_use(
            record,
            default_content=default_content,
            default_status=default_status,
            overrides=overrides,
            bridge_text=bridge_text,
        )
    except Exception as exc:
        logger.error(
            "repair_dangling_tool_use in-memory repair failed for task %s "
            "error_type=%s — record.messages was left unrepaired, still "
            "ending on the dangling toolUse tail",
            record.task.id,
            type(exc).__name__,
        )
        return False
    return True


# RT-008: fixed, SDK-authored — never derived from the tool's own result
# (SI-2). Bridges the synthetic toolResult turn appended by a deferred
# (GH-87) tool call's SUCCESS path, replacing bridge_trailing_user's default
# "(no response)" — which would misreport a call that actually completed and
# produced a terminal artifact as one that produced nothing.
_DEFERRED_SUCCESS_BRIDGE_TEXT = "(tool completed in background)"


async def _run_deferred_background(
    *,
    store: "TaskStore",
    record: "TaskRecord",
    event: DeferredEvent,
    capabilities: "A2uiCapabilities",
) -> None:
    """GH-87: Background awaiter for a deferred tool result.

    Awaits ``event.deferred.handle`` under ``event.timeout_seconds`` and
    transitions the A2A task to COMPLETED (with a terminal artifact) or
    FAILED (on timeout / exception).  The runner calls this via
    ``asyncio.create_task`` immediately after receiving a ``DeferredEvent``;
    the main loop has already exited and the record is in WORKING state.

    RT-001: a handle resolving to ANOTHER ``DeferredResult`` (nested
    deferral) is resolved via the shared ``resolve_deferred_result`` —
    the SAME helper ``ToolEntry.invoke_any`` uses for MCP ``tools/call`` and
    the admin try-tool endpoint — under the identical
    ``_MAX_DEFERRED_RESOLUTIONS`` bound and a single ``event.timeout_seconds``
    deadline shared across every resolution (mirroring RT-003: a nested
    handle never gets a fresh timeout on top). This keeps a ``long_running``
    tool's nested-``DeferredResult`` contract identical across every
    dispatch surface; nesting beyond the bound raises ``AgentError``, caught
    below by the same generic ``except Exception`` branch as any other tool
    failure.

    SI-2: exception text from the handle is not echoed — only a fixed
    "deferred job timed out" / "deferred job failed" string is published.

    RT-002: ``run_loop`` folds the assistant ``toolUse`` message for this
    call BEFORE yielding ``DeferredEvent`` and returning — the matching
    ``toolResult`` is never appended there (the loop has already exited).
    This background awaiter is the only place that later learns the
    outcome, so ``_fail`` (below) and the success path both call
    ``repair_dangling_tool_use`` once that outcome is known, reusing
    GH-150's shared repair helper rather than a separate inline fold.
    RT-001 (GH-147 AC3): that helper also bridges the trailing ``user``
    toolResult turn it appends, so neither branch needs its own follow-up
    call — see ``repair_dangling_tool_use``'s docstring.
    """

    def publish(frame: dict[str, Any] | None, ev: Any, *, final: bool = False) -> None:
        store.publish(record.task.id, StreamItem(frame=frame, event=ev, final=final))

    def _fail(error_msg: str, *, code: int = -32603, category: str = "internal") -> None:
        """Single terminal FAILED exit for every PRE-TERMINAL failure branch
        of the deferred background task — timeout, cancellation, tool
        failure, a raise while building / serialising the terminal artifact,
        AND a publish failure on any pre-terminal step of the success path
        (the artifact-frame publish, the synthetic ToolResultEvent, or the
        COMPLETED transition), all of which run before any terminal final:true
        frame reaches the wire (RT-001).  Deliberately NOT called for a failure
        that happens AT OR AFTER the terminal DoneEvent publish — that would
        emit a duplicate terminal frame (see the narrowed guard around the
        success-path terminal publish below).

        Mirrors ``run_task_worker``'s terminal except-handlers: set FAILED,
        publish the terminal ``DoneEvent(ok=False)`` + final status frame, and
        close streams — so no SSE subscriber ever hangs and no persistent store
        ever observes a stuck-WORKING task, regardless of *which* pre-delivery
        step raised.

        RT-002: also publishes a synthetic ``ToolResultEvent(ok=False)`` so the
        AG-UI ``TOOL_CALL_START`` emitted before the ``DeferredEvent`` gets a
        matching ``TOOL_CALL_RESULT`` — closing the tool-call lifecycle
        symmetrically with the success path rather than only on the happy path
        (frame=None → A2A SSE skips it; only the AG-UI RunMapper consumes it).

        SI-2: ``error_msg`` is always a fixed, non-sensitive string (never raw
        handle/exception text); it is echoed into both the WireError and the
        synthetic ToolResultEvent, both of which reach the wire.

        RT-B-001: no-ops when ``record.task`` is already terminal — a
        concurrent ``tasks_cancel`` (``routes/a2a.py``) can commit its own
        CANCELED transition, repair, and terminal publish while this awaiter
        is mid-flight; ``asyncio.Task.cancel()`` only raises
        ``CancelledError`` at the next await point, so this branch can still
        run afterward. Without this guard it would flip an already-terminal
        task to FAILED and publish a second terminal frame onto streams
        ``tasks_cancel`` already closed.
        """
        if record.task.status.state in TERMINAL_STATES:
            return
        wire_err = WireError(code=code, message=error_msg)
        # RT-002: the dangling toolUse for THIS call is closed with the same
        # fixed error_msg reaching the wire — never raw handle/exception text.
        # RT-001 (GH-147 AC3): repair_dangling_tool_use bridges the trailing
        # 'user' toolResult turn it just appended itself, so no separate
        # follow-up call is needed here.
        # RT-B-002: guarded — see repair_dangling_tool_use_safe.
        # RT-001 (agent/runner.py review): threaded into set_task_status's
        # own `repaired` gate below — see that function's docstring.
        repaired = repair_dangling_tool_use_safe(
            record, default_content=[{"text": error_msg}]
        )
        set_task_status(
            record, TaskState.FAILED, _agent_message(record, error_msg), error=wire_err,
            store=store, repaired=repaired,
        )
        # RT-002 (round 2): close_streams must run even if one of the two
        # publish() calls below raises (e.g. a persistent TaskStore's durable
        # write) — otherwise a *second* failure inside this already-failing
        # path would itself skip stream teardown and strand SSE subscribers
        # un-sentinel-closed until the TTL sweep.
        try:
            publish(
                None,
                ToolResultEvent(
                    tool_call_id=event.tool_call_id,
                    tool_name=event.tool_name,
                    ok=False,
                    error=error_msg,
                ),
            )
            publish(
                _status_frame(record, final=True),
                DoneEvent(ok=False, error=error_msg, code=category),
                final=True,
            )
        finally:
            store.close_streams(record.task.id)

    deadline = time.monotonic() + event.timeout_seconds

    def _handle_timeout() -> float:
        return max(0.0, deadline - time.monotonic())

    try:
        raw_result = await resolve_deferred_result(
            event.deferred, tool_name=event.tool_name, handle_timeout=_handle_timeout
        )
    except asyncio.TimeoutError:
        _fail("deferred job timed out", category="timeout")
        return
    except asyncio.CancelledError:
        # W025-GH87-CANCEL-001: transition to FAILED and close streams so that
        # a persistent store never sees a stuck-WORKING task after cancellation,
        # and SSE subscribers are unblocked before the CancelledError propagates.
        # RT-002: _fail() calls store.publish() / store.close_streams(); if a
        # custom persistent TaskStore raises during that teardown (e.g. streams
        # already closed by a concurrent close_all()), the exception must NOT
        # replace the CancelledError — doing so would break cooperative
        # cancellation of this fire-and-forget background task. Swallow any
        # teardown error so the bare `raise` below always re-raises the
        # CancelledError.
        try:
            _fail("deferred job cancelled")
        except Exception as exc:
            # RT-B-201: an operator needs to know a teardown failure happened
            # inside this already-failing cancellation path — never wire-
            # facing (SI-2), but never silently dropped either.
            logger.warning(
                "deferred cancel teardown failed error_type=%s", type(exc).__name__
            )
        raise
    except Exception as exc:
        # RT-002 (agent/runner.py review): the exception class name is an
        # operator-facing diagnostic — logged only, never interpolated into
        # the wire message _fail() publishes (WireError.message, the
        # user-facing status Message, and ToolResultEvent.error all reach the
        # untrusted A2A/AG-UI caller). Mirrors bedrock.py's RT-006 precedent
        # (BedrockModelClient.converse dropped the identical enrichment from
        # its own wire message for the same reason) and this module's own
        # fixed-string branches (`_fail("internal error")`,
        # `msg = "internal error"` in run_task_worker's terminal handlers).
        # SI-2: never str(exc), which can carry credentials or user payloads.
        logger.warning("deferred job failed error_type=%s", type(exc).__name__)
        _fail("deferred job failed")
        return

    # RT-B-001: the handle resolved successfully, but a concurrent
    # tasks_cancel (routes/a2a.py) may have already committed its own
    # terminal CANCELED transition, repair, and close_streams while this
    # awaiter was in flight — asyncio.Task.cancel() only raises
    # CancelledError at the next await point, so a handle that resolves in
    # the same tick a cancellation was requested reaches here regardless.
    # Bail out before the RT-002 fold below ever touches record.messages,
    # record.task.artifacts, or record.task.status: a background awaiter
    # must never revert an already-terminal task or publish a second
    # terminal frame onto streams tasks_cancel already closed.
    if record.task.status.state in TERMINAL_STATES:
        return

    # GH-148 (cross-surface parity with registry.py's ToolEntry.invoke_any and
    # loop.py's synchronous run_loop branch): a resolved deferred handle may
    # itself be a Reusable — unwrap it to .value here, BEFORE it reaches
    # fold_result_content or build_artifact below, so this background
    # awaiter never leaks the raw Reusable dataclass into record.messages or
    # the terminal artifact. This awaiter has no live run_loop resolved_index
    # to grow in place (run_loop already exited at the DeferredEvent
    # handoff), so — unlike the synchronous branch — the __resolved__ marker
    # is folded into messages ONLY; a later contextId continuation's
    # scan_resolved() rebuilds the index from it exactly like any other
    # marker (agent/reuse.py).
    resolved_marker: dict[str, Any] | None = None
    if isinstance(raw_result, Reusable):
        jsonable_value = jsonable_reuse_value(raw_result.value)
        resolved_marker = {
            "kind": raw_result.kind, "label": raw_result.label, "value": jsonable_value,
        }
        raw_result = raw_result.value
    elif event.reuse_kind is not None:
        # RT-002: the tool returned Reusable(value=DeferredResult(...)) — the
        # ORIGINAL wrapper (loop.py unwraps it before the DeferredResult
        # check and threads kind/label onto this event, since run_loop
        # exits at the handoff before it ever reaches its own Reusable
        # unwrap). The handle's resolved value itself is the reusable one.
        resolved_marker = {
            "kind": event.reuse_kind,
            "label": event.reuse_label,
            "value": jsonable_reuse_value(raw_result),
        }

    # RT-001: the tool has resolved successfully, but building the terminal
    # artifact can still raise — build_artifact() runs translate() /
    # _validate_a2ui_wire() / a domain card's wire(), and
    # TaskArtifactUpdateEvent.wire() serialises the frame. In the SYNCHRONOUS
    # worker the identical build_artifact call (run_task_worker, ArtifactEvent
    # branch) is guarded by that worker's try/except, which fails the task and
    # closes streams on any raise. This deferred path runs in a fire-and-forget
    # background asyncio.Task that nobody awaits, so an unguarded raise here
    # would strand the A2A task in WORKING forever and leave every SSE
    # subscriber queue un-sentinel-closed until the TTL sweep. Guard ONLY the
    # build/serialize/append step so a failure here — before anything has
    # reached the wire — degrades deterministically to FAILED + closed streams,
    # exactly like the synchronous run_task_worker ArtifactEvent branch.
    #
    # RT-001 (round 6): the terminal sequence splits into TWO regions,
    # mirroring run_task_worker's `try` body vs. its `else:` terminal publish.
    #
    #   1. PRE-TERMINAL (guarded by _fail): the artifact-frame publish, the
    #      artifacts append, the synthetic ToolResultEvent publish, and the
    #      COMPLETED transition. These all run BEFORE any terminal final:true
    #      frame reaches the wire, so a failure here (a custom/persistent
    #      TaskStore whose publish() does a durable write that raises) must
    #      fail the task deterministically WITH a terminal frame — _fail()
    #      emits the FIRST terminal frame, never a duplicate — exactly like
    #      the synchronous worker's `except Exception → _fail` ArtifactEvent
    #      branch. Letting it escape this fire-and-forget asyncio.Task instead
    #      (the pre-fix behaviour) stranded the A2A task in WORKING forever
    #      with the stream sentinel-closed but no terminal frame ever
    #      delivered — the exact WORKING-strand this fix closes.
    #
    #   2. TERMINAL (propagate, don't re-fail): the terminal DoneEvent publish
    #      and close_streams. Once the ok=True terminal frame has reached
    #      subscribers, a later failure must NOT re-enter _fail() — doing so
    #      would emit a SECOND, ok=False terminal frame (and ToolResultEvent)
    #      and flip an already-COMPLETED task back to FAILED while it retains
    #      the actually-delivered artifact (RT-002b). Such a failure (e.g. a
    #      persistent TaskStore whose terminal publish() or close_streams()
    #      does a durable write that fails) simply propagates out of this
    #      background task — BUT store.close_streams() still runs in the
    #      `finally` so SSE subscribers are never left un-sentinel-closed.
    try:
        # RT-002: fold the matching toolResult into record.messages NOW — the
        # tool call itself succeeded, and the transcript must say so
        # regardless of whether the terminal-artifact build/delivery below
        # later fails. RT-B-001: run_loop CAN produce a turn in which this
        # deferred call shares the assistant turn with other tool calls —
        # it iterates every tool call in the response and only hands off
        # when it reaches the deferred one, so any earlier call in the same
        # turn has already run. Those siblings' real results are folded from
        # record.pending_tool_results by repair_dangling_tool_use; the
        # default below is the last-resort fallback for a toolUseId with
        # neither an override nor a pending result (SI-2: fixed,
        # non-sensitive text). fold_result_content(raw_result) can itself
        # raise (e.g. a resolved value whose __str__ raises) — kept INSIDE
        # this guarded try, alongside build_artifact's identical rendering
        # risk, so such a failure degrades to _fail("internal error") like
        # any other pre-terminal raise here, rather than escaping this
        # fire-and-forget background task (RT-001).
        content_blocks: list[dict[str, Any]] = [fold_result_content(raw_result)]
        if resolved_marker is not None:
            # GH-148: same __resolved__ marker shape loop.py folds for a
            # synchronous Reusable-returning tool call, so scan_resolved()
            # rebuilds the index identically regardless of which dispatch
            # surface resolved it.
            content_blocks.append({"json": {RESOLVED_MARKER_KEY: resolved_marker}})
        # RT-003: routed through the guarded wrapper (not the raw helper) so
        # a durable store's persist_messages failure here degrades to a
        # missing flush like it does at every other call site, rather than
        # failing this otherwise-successful deferred call via the broad
        # `except Exception` below.
        # RT-001 (agent/runner.py review): threaded into set_task_status's
        # own `repaired` gate at the COMPLETED transition below.
        deferred_repaired = repair_dangling_tool_use_safe(
            record,
            default_content=[{"text": "tool call result unavailable"}],
            overrides={event.tool_call_id: (content_blocks, "success")},
            bridge_text=_DEFERRED_SUCCESS_BRIDGE_TEXT,
        )
        # GH-225: a declared tool's result that matches no emits member gets a
        # text-only artifact (no A2UI card); a matching one is labelled with
        # that member's data_type; an emits-less tool is unchanged.
        matched = match_emits_type(event.emits_types, raw_result)
        artifact_ev = ArtifactEvent(
            data_type=getattr(matched, "data_type", event.tool_name)
            if matched is not None
            else event.tool_name,
            tool_name=event.tool_name,
            model=raw_result,
        )
        if event.emits_types and matched is None:
            artifact = build_text_only_artifact(artifact_ev)
        else:
            artifact = build_artifact(artifact_ev, capabilities)
        # RT-002: serialize the wire frame HERE (inside the guarded block) but
        # do NOT mutate task.artifacts yet — the append is deferred to AFTER
        # publish() has actually delivered the frame (second try block below).
        # If .wire() raises, the except branch below fails the task; if the
        # artifact-frame publish() later raises, the append simply never runs.
        # Either way a task that never delivered this artifact on any stream
        # must not retain it (mirrors run_task_worker's ArtifactEvent branch).
        artifact_frame = TaskArtifactUpdateEvent(
            taskId=record.task.id,
            contextId=record.task.context_id,
            artifact=artifact,
            lastChunk=True,
        ).wire()
    except Exception as exc:
        # Mirror run_task_worker's terminal Exception handler: a ValueError
        # (e.g. _validate_a2ui_wire rejecting a malformed domain card) maps to
        # the A2A "invalid agent response" code (-32006); anything else is a
        # generic internal error (-32603).  SI-2: no exception text is echoed.
        # RT-B-201: log the class name — pydantic's ValidationError IS a
        # ValueError (LRN-044), so this branch previously mapped a
        # validation failure to the fixed wire string with zero operator
        # attribution.
        logger.warning(
            "deferred artifact build failed error_type=%s", type(exc).__name__
        )
        if isinstance(exc, ValueError):
            _fail("invalid agent response", code=-32006, category="validation")
        else:
            _fail("internal error")
        return

    try:
        # GH-225: a no-match text-only artifact publishes no loop event, so
        # AG-UI renders no AGENT_ARTIFACT / A2UI card (same as the inline path).
        publish(
            artifact_frame,
            None if event.emits_types and matched is None else artifact_ev,
        )
        # RT-002: append to task.artifacts ONLY AFTER the artifact frame has
        # actually been delivered on the stream. If the publish() above raises
        # (e.g. a persistent TaskStore's durable write), the artifact is never
        # recorded on the record, so the _fail() below leaves behind no
        # undelivered-artifact — same guarantee as run_task_worker's
        # ArtifactEvent branch.
        record.task.artifacts = (record.task.artifacts or []) + [artifact]

        # RT-W025-003: emit a synthetic ToolResultEvent so the AG-UI RunMapper
        # can produce a TOOL_CALL_RESULT frame to close the tool-call
        # lifecycle that was opened by the ToolCallEvent / TOOL_CALL_START
        # emitted before the loop yielded the DeferredEvent.  Without this,
        # strict AG-UI clients receive a TOOL_CALL_START with no matching
        # TOOL_CALL_RESULT, violating the protocol.
        tool_result_ev = ToolResultEvent(
            tool_call_id=event.tool_call_id,
            tool_name=event.tool_name,
            ok=True,
            result=raw_result,
        )
        publish(None, tool_result_ev)

        set_task_status(record, TaskState.COMPLETED, store=store, repaired=deferred_repaired)
    except Exception as exc:
        # RT-001: any PRE-terminal publish failure fails the task with the
        # FIRST terminal frame (no terminal frame has reached the wire yet, so
        # this is never a duplicate) and closes streams — mirroring
        # run_task_worker's `except Exception → _fail`. RT-002 (agent/runner.py
        # review): the exception class name is logged only, never wired — see
        # the identical fix (and its full rationale) on the handle-resolution
        # branch above.
        logger.warning("deferred internal error error_type=%s", type(exc).__name__)
        _fail("internal error")
        return

    try:
        done_ev = DoneEvent(ok=True)
        publish(_status_frame(record, final=True), done_ev, final=True)
    finally:
        # RT-002: guarantee stream closure even if the terminal publish() above
        # raised (e.g. a persistent TaskStore's durable write) — a custom
        # TaskStore must never strand SSE subscribers un-sentinel-closed just
        # because the terminal frame failed. A failure here propagates without
        # re-failing (RT-002b): the ok=True terminal frame may already have
        # reached subscribers, so re-entering _fail() would duplicate it.
        store.close_streams(record.task.id)


def _clock_now() -> datetime:
    return datetime.now(timezone.utc)


def current_date_line(tz: str, *, now: datetime | None = None) -> str:
    """``Today is YYYY-MM-DD (<tz>).`` — date only, in zone ``tz`` (GH-154)."""
    moment = now if now is not None else _clock_now()
    return f"Today is {moment.astimezone(load_zone(tz)).date().isoformat()} ({tz})."


# RT-A-002: fixed, SDK-authored — never derived from an AgentError's own
# .message or str(exc) (SI-2). The synthetic toolResult content for a
# dangling assistant toolUse repaired by run_task_worker's own terminal
# `except AgentError` handler; kept separate from the WireError/agent-facing
# message (which does echo err.message) so this internally-replayed content
# never depends on what a given AgentError raise site happens to say.
_TASK_FAILED_TOOL_RESULT_TEXT = "tool call failed: task failed before a result was returned"


async def run_task_worker(
    *,
    store: TaskStore,
    record: TaskRecord,
    model: ModelClient,
    registry: ToolRegistry,
    adapters: dict[type[SourceAdapter], SourceAdapter],
    skills: SkillsRegistry | None,
    system: str,
    capabilities: A2uiCapabilities,
    policies: LoopPolicies,
    extra_resolved_messages: Sequence[dict[str, Any]] | None = None,
    inject_date: bool = False,
    timezone_name: str = "UTC",
    user_timezone: str | None = None,
) -> None:
    """Consume the loop until DoneEvent or interrupt-expiry/cancellation.
    ``record.messages`` must already contain the folded user turn.

    ``extra_resolved_messages`` (RT-A-004) — forwarded verbatim to
    ``run_loop`` to seed cross-request GH-148 reuse on a transport (AG-UI)
    whose ``record.messages`` does not itself carry a prior run's
    ``__resolved__`` markers. See ``run_loop``'s own docstring."""
    task = record.task
    if inject_date:
        if record.date_line is None:
            record.date_line = current_date_line(
                valid_timezone(user_timezone) or timezone_name
            )
        system = f"{system}\n\n{record.date_line}"
    text_segments: list[str] = []
    # GH-87: set to True when a DeferredEvent is received; prevents the
    # `else: store.close_streams(task.id)` from closing the stream before
    # the background awaiter finishes.
    deferred_launched: bool = False
    # Set when a DoneEvent is consumed; the terminal publish itself runs in
    # the `else:` clause below, not here — see the DoneEvent branch.
    done_event: DoneEvent | None = None
    # RT-B-102: the exact terminal TaskState this worker itself committed in
    # the DoneEvent branch below, so the `else:` clause's terminal publish
    # can detect a concurrent tasks_cancel overwriting it in the narrow
    # window between that commit and reaching `else:` (the for-loop's own
    # await boundary) and skip re-publishing a stale/second terminal frame.
    worker_committed_state: TaskState | None = None

    async def wait_resume(interrupt_id: str) -> Any:
        # the InterruptEvent handler below registered the future already
        future = record.resume_future
        if future is None:  # defensive: interrupt registration failed
            raise AgentError(ErrorCategory.INTERNAL, "resume channel missing")
        value = await future
        if isinstance(value, ResumeEnvelope):
            bind_identity(value.identity)
            return value.value
        return value

    def publish(frame: dict[str, Any] | None, event: Any, *, final: bool = False) -> None:
        store.publish(task.id, StreamItem(frame=frame, event=event, final=final))

    try:
        set_task_status(record, TaskState.WORKING, store=store)
        publish(_status_frame(record), None)

        async for event in run_loop(
            model=model,
            registry=registry,
            adapters=adapters,
            system=system,
            messages=record.messages,
            skills=skills,
            policies=policies,
            wait_resume=wait_resume,
            spent_tokens=record.spent_tokens,
            extra_resolved_messages=extra_resolved_messages,
            # RT-B-001: the turn's completed toolResult blocks live on the
            # record, not in run_loop's frame, so every mid-turn exit path
            # (the DeferredEvent handoff below, the terminal handlers, and
            # tasks_cancel in routes/a2a.py) can fold the real results of
            # calls that already succeeded instead of a blanket error.
            pending_results=record.pending_tool_results,
            # RT-004: seal the SHARED STATE, not just this consumer loop. The
            # RT-B-102 guard below stops this worker from mutating status,
            # artifacts or streams once another owner (tasks_cancel, the
            # deferred awaiter) has committed a terminal transition — but it
            # runs one level ABOVE run_loop, and run_loop's own
            # `messages.append` executes inside the generator before the next
            # event is ever yielded. So the same condition has to be readable
            # from down there. Same predicate as that guard, deliberately: one
            # source of truth rather than a second flag that can drift.
            sealed=lambda: record.task.status.state in TERMINAL_STATES,
        ):
            if record.task.status.state in TERMINAL_STATES:
                # RT-B-102: a concurrent tasks_cancel (routes/a2a.py) — or any
                # other future actor — may already have committed a terminal
                # transition, repaired record.messages, and closed streams
                # while this worker kept running: reachable whenever this
                # worker's own asyncio.CancelledError never arrives (tool
                # code catching BaseException, or asyncio.wait_for's
                # cancel-vs-timeout race in 3.11+ turning it into a
                # TimeoutError, loop.py). Checked once per event, at the top
                # of the loop, rather than duplicated per branch, so it
                # covers every event type this loop can yield — not only
                # DoneEvent — the instant the task is observed terminal: no
                # further status mutation, message fold, artifact append, or
                # publish may happen once another owner has already finished
                # tearing the task down. `return` (not `break`) also skips
                # the `else:` clause below, so no second terminal frame is
                # published onto streams the canceller already closed.
                # Mirrors the identical guard in _run_deferred_background's
                # _fail() and its post-await success check.
                return
            if isinstance(event, UsageEvent):
                record.spent_tokens += event.input_tokens + event.output_tokens
                publish(None, event)
            elif isinstance(event, TextEvent):
                text_segments.append(event.text)
                set_task_status(
                    record, TaskState.WORKING, _agent_message(record, event.text), store=store
                )
                publish(_status_frame(record), event)
            elif isinstance(event, (ProgressEvent, NoteEvent)):
                text = event.message if isinstance(event, ProgressEvent) else event.note
                set_task_status(
                    record, TaskState.WORKING, _agent_message(record, text), store=store
                )
                publish(_status_frame(record), event)
            elif isinstance(event, AuditEvent):
                # RT-009: internal audit record — NEVER folded into
                # status.message (that channel is user-facing agent chat
                # text). Logged for stored-state inspectability and carried
                # in envelope metadata, not the message; task status/history
                # is left untouched. AG-UI's mapper emits no frame for this
                # event (falls through its default no-frame case).
                #
                # RT-A-003: build the frame from a message-free status rather
                # than reusing _status_frame's record.task.status verbatim —
                # that status still carries whatever agent Message a prior
                # TextEvent/ProgressEvent/NoteEvent set, so re-serializing it
                # here would re-emit that chat sentence a second time on this
                # audit frame.
                logger.info("task %s audit: %s %s", record.task.id, event.code, event.detail)
                audit_frame = TaskStatusUpdateEvent(
                    taskId=record.task.id,
                    contextId=record.task.context_id,
                    status=TaskStatus(state=record.task.status.state, timestamp=_now()),
                    final=False,
                    metadata={"audit": {"code": event.code, **event.detail}},
                ).wire()
                publish(audit_frame, event)
            elif isinstance(event, ToolProgressEvent):
                # GH-88: interim tool progress — A2A TaskStatusUpdateEvent{state:"working",
                # final:false} + raw event for AG-UI CUSTOM "TOOL_PROGRESS" frame.
                set_task_status(
                    record, TaskState.WORKING, _agent_message(record, event.message), store=store
                )
                publish(_status_frame(record), event)
            elif isinstance(event, DeferredEvent):
                # GH-87: long-running tool returned DeferredResult — keep the
                # task WORKING and launch a background asyncio.Task that awaits
                # the handle.  The background task owns all subsequent status
                # transitions (COMPLETED / FAILED) and stream closure.
                # RT-W025-004: hold a strong reference in the module-level set so
                # the GC cannot discard the task before it finishes (Python 3.12+
                # event-loop keeps only *weak* references to tasks).  Same pattern
                # as contrib/webhooks/dispatch.py: add → callback discards on done.
                deferred_launched = True
                _bg_task = asyncio.get_running_loop().create_task(
                    _run_deferred_background(
                        store=store,
                        record=record,
                        event=event,
                        capabilities=capabilities,
                    )
                )
                # W025-GH87-SHUTDOWN-TRACK-001: expose the background task on
                # the record so evict() can cancel it during shutdown.
                record.bg_task = _bg_task
                _background_tasks.add(_bg_task)
                _bg_task.add_done_callback(_background_tasks.discard)
                # Exit the for-loop; the background task takes over from here.
                break
            elif isinstance(event, ArtifactEvent):
                artifact = build_artifact(event, capabilities)
                # RT-002: serialize the wire frame BEFORE mutating
                # task.artifacts, AND append only AFTER publish() has actually
                # delivered the frame. This closes BOTH pre-delivery failure
                # sub-cases: if .wire() raises OR if publish() raises, the
                # `except` handler below flips the task to FAILED while
                # task.artifacts still holds NO entry that never reached a
                # stream — the exact invariant the wave's earlier reorder only
                # half-enforced (it covered .wire() but left the append before
                # publish). Mirrors _run_deferred_background's success path.
                frame = TaskArtifactUpdateEvent(
                    taskId=task.id,
                    contextId=task.context_id,
                    artifact=artifact,
                    lastChunk=True,
                ).wire()
                publish(frame, event)
                task.artifacts = (task.artifacts or []) + [artifact]
            elif isinstance(event, InterruptEvent):
                # cap check + resume-channel registration; at the cap this
                # raises and becomes a typed task failure (§5.2)
                store.mark_interrupted(task.id, event.interrupt_id)
                event.expires_in = store.interrupt_ttl_remaining(task.id)
                state = (
                    TaskState.AUTH_REQUIRED
                    if "auth" in event.reason
                    else TaskState.INPUT_REQUIRED
                )
                set_task_status(
                    record,
                    state,
                    _agent_message(
                        record,
                        event.message,
                        metadata={
                            "interruptId": event.interrupt_id,
                            "responseSchema": event.response_schema,
                            "toolCallId": event.tool_call_id,
                        },
                    ),
                    store=store,
                )
                # the stream MAY close final:true while interrupted (§5.1)
                publish(_status_frame(record, final=True), event, final=True)
            elif isinstance(event, DoneEvent):
                # RT-B-102: the top-of-loop guard above already bailed out if
                # record.task.status was already terminal when this DoneEvent
                # was received, so the transition below is always this
                # worker's own legitimate commit.
                if event.ok:
                    final_text = "\n\n".join(s for s in text_segments if s).strip()
                    message = _agent_message(record, final_text) if final_text else None
                    if message is not None:
                        task.history = (task.history or []) + [message]
                    set_task_status(record, TaskState.COMPLETED, message, store=store)
                else:
                    error_msg = event.error or "task failed"
                    status_text = (
                        f"{event.summary}\n\n{error_msg}" if event.summary else error_msg
                    )
                    set_task_status(
                        record,
                        TaskState.FAILED,
                        _agent_message(record, status_text),
                        error=WireError(code=-32603, message=error_msg),
                        store=store,
                    )
                # The state transition above is already committed; the
                # terminal publish runs in the `else:` clause below, outside
                # this try, so a publish failure there is not caught by the
                # except handlers and cannot re-enter the FAILED path with a
                # SECOND terminal frame on top of one that may have already
                # reached subscribers (mirrors the narrowed guard around
                # _run_deferred_background's success path above).
                worker_committed_state = record.task.status.state
                done_event = event
            else:
                # TurnStarted / ToolCall / ToolResult: no A2A frame; AG-UI
                # consumers map these to STEP_* and tool-call families
                publish(None, event)

    except asyncio.CancelledError:
        # cancel/eviction path: the canceller owns status + final frame +
        # stream closure
        raise
    except AgentError as err:
        # RT-001 (agent/runner.py review): mirrors _run_deferred_background's
        # _fail() entry guard (line ~826) — an AgentError can escape run_loop
        # AFTER a concurrent tasks_cancel has already committed a terminal
        # transition (repaired record.messages, closed streams), since the
        # top-of-loop TERMINAL_STATES guard above only sees events run_loop
        # actually yields, not a raise between a tool await and the next
        # yield. Without this, that already-terminal task would be flipped
        # to FAILED and a second terminal frame published onto streams the
        # canceller already closed.
        if record.task.status.state in TERMINAL_STATES:
            return
        wire_err = WireError(
            code=err.a2a_code if err.a2a_code is not None else -32603,
            message=err.message,
        )
        # RT-A-002 (RT-005 follow-up): this except-handler is reachable
        # mid-turn — e.g. store.mark_interrupted (§5.2 max_interrupted cap)
        # raising from the InterruptEvent branch above, an AgentError
        # propagating from wait_resume, or any future raise between the
        # folded assistant toolUse message and the turn's own toolResult
        # fold at loop.py:815 — leaving record.messages ending on the
        # assistant toolUse message with no matching toolResult. FAILED is
        # terminal, and context_messages() replays that transcript verbatim
        # on the next contextId continuation — the exact GH-150 shape, on a
        # path GH-150 did not cover. Repair it here, BEFORE the FAILED
        # transition (same ordering as _fail()'s identical call and
        # tasks_cancel's, routes/a2a.py). SI-2: a fixed constant, never
        # err.message — err.message is echoed into the user-facing
        # WireError/agent message below, but is not guaranteed free of
        # caller-supplied detail at every AgentError raise site, so the
        # internally-replayed toolResult content stays decoupled from it.
        # RT-B-002: guarded — see repair_dangling_tool_use_safe.
        # RT-001 (agent/runner.py review): threaded into set_task_status's
        # own `repaired` gate below — see that function's docstring.
        repaired = repair_dangling_tool_use_safe(
            record, default_content=[{"text": _TASK_FAILED_TOOL_RESULT_TEXT}]
        )
        set_task_status(
            record, TaskState.FAILED, _agent_message(record, err.message), error=wire_err,
            store=store, repaired=repaired,
        )
        # RT-002 (round 2): guard close_streams with a finally — a second
        # publish() failure inside this except-handler must not itself skip
        # stream teardown (mirrors _fail()'s identical guard above).
        try:
            publish(_status_frame(record, final=True), DoneEvent(ok=False, error=err.message, code=err.category.value), final=True)
        finally:
            store.close_streams(task.id)
    except Exception as exc:
        # RT-001 (agent/runner.py review): same already-terminal bail-out as
        # the AgentError handler above, and for the identical reason — a
        # generic exception (e.g. jsonable_reuse_value / fold_result_content
        # raising outside the per-tool-call try/except in loop.py) can just
        # as easily escape run_loop after a concurrent tasks_cancel has
        # already committed CANCELED. Checked BEFORE logging/mapping so a
        # post-terminal exception leaves no side effect at all here.
        if record.task.status.state in TERMINAL_STATES:
            return
        # RT-B-201: log the class name before mapping — pydantic's
        # ValidationError IS a ValueError (LRN-044), so this branch
        # previously mapped a validation failure to the fixed wire string
        # below with zero operator attribution. SI-2: never str(exc).
        logger.warning("task worker error error_type=%s", type(exc).__name__)
        if isinstance(exc, ValueError):
            wire_err = WireError(code=-32006, message="invalid agent response")
            msg = "invalid agent response"
        else:
            wire_err = WireError(code=-32603, message="internal error")
            msg = "internal error"
        # RT-A-002 (RT-005 follow-up): same dangling-toolUse repair as the
        # AgentError branch above, and BEFORE the FAILED transition for the
        # same reason — build_artifact (via _validate_a2ui_wire / a domain
        # card's translate()/wire()/to_plain_text()) raises from inside the
        # per-tool-call loop (loop.py:777) BEFORE the matching toolResult is
        # folded (loop.py:815), so this generic-Exception handler is
        # reachable mid-turn exactly like the AgentError one. msg is always
        # one of the two fixed literals above — never str(exc) (SI-2).
        # RT-B-002: guarded — see repair_dangling_tool_use_safe.
        # RT-001 (agent/runner.py review): threaded into set_task_status's
        # own `repaired` gate below — see that function's docstring.
        repaired = repair_dangling_tool_use_safe(record, default_content=[{"text": msg}])
        set_task_status(
            record, TaskState.FAILED, _agent_message(record, msg), error=wire_err, store=store,
            repaired=repaired,
        )
        try:
            publish(_status_frame(record, final=True), DoneEvent(ok=False, error=msg, code="validation" if isinstance(exc, ValueError) else "internal"), final=True)
        finally:
            store.close_streams(task.id)
    else:
        try:
            # RT-B-102: re-check against the exact state this worker itself
            # committed in the DoneEvent branch above. `state in
            # TERMINAL_STATES` alone would also be true on every normal
            # completion (that's what the branch above just set) — the
            # comparison instead catches only the narrow race where a
            # concurrent tasks_cancel overwrote our commit with its own
            # CANCELED transition (and closed streams) in the window between
            # that commit and this `else:` clause (the for-loop's own await
            # boundary as it exhausts run_loop). Never publish a stale or
            # second terminal frame onto streams the canceller already
            # closed.
            if done_event is not None and record.task.status.state == worker_committed_state:
                publish(_status_frame(record, final=True), done_event, final=True)
        finally:
            # RT-002: close_streams must run even if the terminal publish()
            # above raises (e.g. a persistent TaskStore's durable write) —
            # this worker is itself launched as a fire-and-forget
            # asyncio.Task (routes/a2a.py, routes/ag_ui.py), so an unguarded
            # raise here would strand subscribers un-sentinel-closed.
            if not deferred_launched:
                # Normal completion: close streams now.
                # GH-87: if deferred_launched is True, the background task
                # owns stream closure — do NOT close here.
                store.close_streams(task.id)


def new_task(context_id: str | None = None) -> Task:
    return Task(
        id=uuid.uuid4().hex,
        contextId=context_id or uuid.uuid4().hex,
        status=TaskStatus(state=TaskState.SUBMITTED, timestamp=_now()),
        history=[],
        artifacts=[],
    )
