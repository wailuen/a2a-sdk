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
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# RT-W025-004: module-level set that holds strong references to deferred
# background tasks, following the same pattern as contrib/webhooks/dispatch.py.
# Python 3.12+ event-loop keeps only *weak* references to tasks; without a
# strong reference the GC can silently discard a running background task and
# leave the A2A task stuck in WORKING state forever.
_background_tasks: set[asyncio.Task[Any]] = set()

from pydantic import BaseModel

from ..a2ui.translator import A2uiCapabilities, split_a2ui_delivery, translate
from ..models.a2a import (
    Artifact,
    DataPart,
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from ..models.content_types import A2UI_MIME_TYPE, ContentModel
from ..models.errors import AgentError, ErrorCategory, WireError
from ..tasks.store import TaskRecord, TaskStore
from .deferred import DeferredEvent
from .events import (
    ArtifactEvent,
    DoneEvent,
    InterruptEvent,
    NoteEvent,
    ProgressEvent,
    TextEvent,
    ToolProgressEvent,
    ToolResultEvent,
    UsageEvent,
)
from .loop import LoopPolicies, run_loop
from .model_client import ModelClient
from .registry import ToolRegistry, resolve_deferred_result
from .skills import SkillsRegistry
from ..sources import SourceAdapter


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
    return Message(
        role="agent",
        parts=[TextPart(text=text)],
        messageId=uuid.uuid4().hex,
        taskId=record.task.id,
        contextId=record.task.context_id,
        metadata=metadata,
    )


def _status_frame(record: TaskRecord, *, final: bool = False) -> dict[str, Any]:
    return TaskStatusUpdateEvent(
        taskId=record.task.id,
        contextId=record.task.context_id,
        status=record.task.status,
        final=final,
    ).wire()


def _set_status(
    record: TaskRecord,
    state: TaskState,
    message: Message | None = None,
    *,
    error: WireError | None = None,
) -> None:
    # stateTransitionHistory (A2A v0.3.0 §2) is not implemented: the Task
    # model has no such field and the card advertises stateTransitionHistory=false.
    record.task.status = TaskStatus(state=state, message=message, timestamp=_now(), error=error)


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
            raise ValueError(
                f"Domain card {label}: wire() raised an exception: {exc}"
            ) from exc
        if not isinstance(wire_val, dict) or not wire_val:
            raise ValueError(
                f"Domain card {label}: wire() must return a non-empty dict; "
                f"got {type(wire_val).__name__!r}: {wire_val!r}"
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
    try:
        json.dumps(artifact.wire(), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"artifact for {event.data_type!r} is not JSON-serializable"
        ) from exc
    return artifact


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
    """

    def publish(frame: dict[str, Any] | None, ev: Any, *, final: bool = False) -> None:
        store.publish(record.task.id, StreamItem(frame=frame, event=ev, final=final))

    def _fail(error_msg: str, *, code: int = -32603) -> None:
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
        """
        wire_err = WireError(code=code, message=error_msg)
        _set_status(
            record, TaskState.FAILED, _agent_message(record, error_msg), error=wire_err
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
                DoneEvent(ok=False, error=error_msg),
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
        _fail("deferred job timed out")
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
        except Exception:
            pass
        raise
    except Exception:
        _fail("deferred job failed")
        return

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
        artifact_ev = ArtifactEvent(
            data_type=getattr(event.emits, "data_type", event.tool_name)
            if event.emits is not None
            else event.tool_name,
            tool_name=event.tool_name,
            model=raw_result,
        )
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
        if isinstance(exc, ValueError):
            _fail("invalid agent response", code=-32006)
        else:
            _fail("internal error")
        return

    try:
        publish(artifact_frame, artifact_ev)
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

        _set_status(record, TaskState.COMPLETED)
    except Exception:
        # RT-001: any PRE-terminal publish failure fails the task with the
        # FIRST terminal frame (no terminal frame has reached the wire yet, so
        # this is never a duplicate) and closes streams — mirroring
        # run_task_worker's `except Exception → _fail`. SI-2: fixed message
        # only, no exception text echoed.
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
) -> None:
    """Consume the loop until DoneEvent or interrupt-expiry/cancellation.
    ``record.messages`` must already contain the folded user turn."""
    task = record.task
    text_segments: list[str] = []
    # GH-87: set to True when a DeferredEvent is received; prevents the
    # `else: store.close_streams(task.id)` from closing the stream before
    # the background awaiter finishes.
    deferred_launched: bool = False
    # Set when a DoneEvent is consumed; the terminal publish itself runs in
    # the `else:` clause below, not here — see the DoneEvent branch.
    done_event: DoneEvent | None = None

    async def wait_resume(interrupt_id: str) -> Any:
        # the InterruptEvent handler below registered the future already
        future = record.resume_future
        if future is None:  # defensive: interrupt registration failed
            raise AgentError(ErrorCategory.INTERNAL, "resume channel missing")
        return await future

    def publish(frame: dict[str, Any] | None, event: Any, *, final: bool = False) -> None:
        store.publish(task.id, StreamItem(frame=frame, event=event, final=final))

    try:
        _set_status(record, TaskState.WORKING)
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
        ):
            if isinstance(event, UsageEvent):
                record.spent_tokens += event.input_tokens + event.output_tokens
                publish(None, event)
            elif isinstance(event, TextEvent):
                text_segments.append(event.text)
                _set_status(record, TaskState.WORKING, _agent_message(record, event.text))
                publish(_status_frame(record), event)
            elif isinstance(event, (ProgressEvent, NoteEvent)):
                text = event.message if isinstance(event, ProgressEvent) else event.note
                _set_status(record, TaskState.WORKING, _agent_message(record, text))
                publish(_status_frame(record), event)
            elif isinstance(event, ToolProgressEvent):
                # GH-88: interim tool progress — A2A TaskStatusUpdateEvent{state:"working",
                # final:false} + raw event for AG-UI CUSTOM "TOOL_PROGRESS" frame.
                _set_status(record, TaskState.WORKING, _agent_message(record, event.message))
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
                _set_status(
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
                )
                # the stream MAY close final:true while interrupted (§5.1)
                publish(_status_frame(record, final=True), event, final=True)
            elif isinstance(event, DoneEvent):
                if event.ok:
                    final_text = "\n\n".join(s for s in text_segments if s).strip()
                    message = _agent_message(record, final_text) if final_text else None
                    if message is not None:
                        task.history = (task.history or []) + [message]
                    _set_status(record, TaskState.COMPLETED, message)
                else:
                    error_msg = event.error or "task failed"
                    _set_status(
                        record,
                        TaskState.FAILED,
                        _agent_message(record, error_msg),
                        error=WireError(code=-32603, message=error_msg),
                    )
                # The state transition above is already committed; the
                # terminal publish runs in the `else:` clause below, outside
                # this try, so a publish failure there is not caught by the
                # except handlers and cannot re-enter the FAILED path with a
                # SECOND terminal frame on top of one that may have already
                # reached subscribers (mirrors the narrowed guard around
                # _run_deferred_background's success path above).
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
        wire_err = WireError(
            code=err.a2a_code if err.a2a_code is not None else -32603,
            message=err.message,
        )
        _set_status(record, TaskState.FAILED, _agent_message(record, err.message), error=wire_err)
        # RT-002 (round 2): guard close_streams with a finally — a second
        # publish() failure inside this except-handler must not itself skip
        # stream teardown (mirrors _fail()'s identical guard above).
        try:
            publish(_status_frame(record, final=True), DoneEvent(ok=False, error=err.message), final=True)
        finally:
            store.close_streams(task.id)
    except Exception as exc:
        if isinstance(exc, ValueError):
            wire_err = WireError(code=-32006, message="invalid agent response")
            msg = "invalid agent response"
        else:
            wire_err = WireError(code=-32603, message="internal error")
            msg = "internal error"
        _set_status(record, TaskState.FAILED, _agent_message(record, msg), error=wire_err)
        try:
            publish(_status_frame(record, final=True), DoneEvent(ok=False, error=msg), final=True)
        finally:
            store.close_streams(task.id)
    else:
        try:
            if done_event is not None:
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
