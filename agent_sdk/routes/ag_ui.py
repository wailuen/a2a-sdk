"""AG-UI route — POST /ag-ui/run, SSE (DESIGN.md §5.3).

The task worker publishes ``StreamItem``s carrying raw loop events; this
route owns a per-request state machine that maps them to AG-UI wire frames
(camelCase JSON, ``data:`` lines only). Transport-level rejections —
disallowed Origin (403), wrong Content-Type (415), oversized body (413) —
are returned/raised before the stream is ever constructed. Once the stream
begins, each request's stream is a self-contained run: ``RUN_STARTED`` is
always the first frame, ``STATE_SNAPSHOT`` second, exactly one terminal
``RUN_FINISHED`` | ``RUN_ERROR``; every failure after ``RUN_STARTED`` is
reported as a ``RUN_ERROR`` frame rather than an HTTP error. An interrupt
ends the run with the interrupt outcome; resume arrives as a NEW run
carrying ``resume=[{interrupt_id, status, payload}]`` and is identity-bound
exactly like the A2A path (§5.1).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from ..a2ui.translator import A2uiCapabilities, translate
from ..agent.runner import new_task, run_task_worker, split_a2ui_delivery_validated
from ..auth.identity import Identity
from ..auth.middleware import require_identity
from ..common.iso8601 import iso_utc
from ..common.origin import guard_origin
from ..common.sse import HEARTBEAT, SSE_HEADERS, sse_data
from ..credentials import forwarding
from ..models.content_types import ContentModel
from ..tasks.store import StreamTerminated, TaskRecord
from ..agent.events import (
    ArtifactEvent,
    DoneEvent,
    InterruptEvent,
    NoteEvent,
    ProgressEvent,
    TextEvent,
    ToolCallEvent,
    ToolProgressEvent,
    ToolResultEvent,
    TurnStartedEvent,
)

logger = logging.getLogger("agent_sdk.ag_ui")

router = APIRouter()

MAX_HISTORY_MESSAGES = 50
MAX_MESSAGE_CHARS = 4000
_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB — mirrors MCP/OAuth caps
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# ── history fold (processing, not rejection — §5.3) ──


def _fold_history(raw_messages: list[Any]) -> list[dict[str, Any]] | None:
    """AG-UI messages → Converse format. Truncates (50 msgs / 4000 chars),
    skips blank assistant turns, merges consecutive same-role turns, drops
    a leading assistant prefix. None when no user content survives.

    Control characters are STRIPPED — never rejected — from every folded
    string (RT-001). The AG-UI client re-submits the full conversation history
    each turn with BOTH its own user turns and the model's streamed assistant
    turns folded back in (chat.js). If any single control char in that replayed
    content could hard-reject the run, one ESC/NUL/BEL emitted in the model's
    own output would turn every subsequent turn into RUN_ERROR and permanently
    brick the session. Stripping here — the one function that builds the model
    input, covering str/list/coerced shapes uniformly — guarantees nothing
    unsafe reaches the model, mirroring the loop.py unknown-tool sanitizer."""
    folded: list[dict[str, Any]] = []
    for raw in raw_messages[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        if role not in ("user", "assistant"):
            continue
        content = raw.get("content") or ""
        if isinstance(content, list):
            content = "".join(
                str(p.get("text") or "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        elif not isinstance(content, str):
            content = str(content)
        content = _CONTROL_CHARS.sub("", content)
        if role == "assistant" and not content.strip():
            continue
        if len(content) > MAX_MESSAGE_CHARS:
            logger.warning(
                "ag-ui history message truncated from %d to %d chars",
                len(content),
                MAX_MESSAGE_CHARS,
            )
            content = content[:MAX_MESSAGE_CHARS]
        if folded and folded[-1]["role"] == role:
            folded[-1]["content"].append({"text": content})
        else:
            folded.append({"role": role, "content": [{"text": content}]})
    while folded and folded[0]["role"] != "user":
        folded.pop(0)
    return folded or None


def _validate(body: dict[str, Any]) -> str | None:
    """Returns an error message (→ RUN_ERROR) or None.

    Only the STRUCTURAL shape of ``messages`` is rejected here. Message CONTENT
    is never hard-rejected — not on control characters, not on unexpected part
    shapes (RT-001). The AG-UI client re-submits the full conversation history
    every turn (its own user turns AND the model's streamed assistant turns,
    folded back in by chat.js), so rejecting content would let a single control
    char anywhere in that replayed history turn every subsequent turn into
    RUN_ERROR and permanently brick the session. Content is sanitized instead:
    _fold_history strips control chars from every folded string — of any shape
    — before it reaches the model.

    threadId/runId are NOT checked here: the route always synthesizes them
    before RUN_STARTED (§5.3), so by the time _validate runs a missing or
    malformed id has already been replaced — rejecting the original raw
    body for those fields would emit RUN_ERROR right after a RUN_STARTED
    that already claimed a valid id (GH-97).
    """
    messages = body.get("messages")
    if messages is not None and not isinstance(messages, list):
        return "messages must be a list"
    return None


# ── event → frame mapping ──


class _RunMapper:
    """Per-request state machine: raw loop events → AG-UI frames."""

    def __init__(self, thread_id: str, run_id: str, capabilities: A2uiCapabilities) -> None:
        self.thread_id = thread_id
        self.run_id = run_id
        self.capabilities = capabilities
        self.open_step: str | None = None
        self.terminal_sent = False
        # parent for TOOL_CALL_START; reset each turn, set by assistant text
        self.last_message_id: str | None = None
        # tool_call_ids whose TOOL_CALL_START was emitted in THIS stream;
        # used to detect resume runs where the START occurred in a prior stream
        self._seen_starts: set[str] = set()

    def _close_step(self) -> list[dict[str, Any]]:
        if self.open_step is None:
            return []
        frame = {"type": "STEP_FINISHED", "stepName": self.open_step}
        self.open_step = None
        return [frame]

    def _ensure_step(self) -> list[dict[str, Any]]:
        """Guarantee an open STEP before tool frames. On a resume run the
        new mapper never saw the original TurnStartedEvent, so tool frames
        would otherwise be unparented — open a synthetic step (§5.3)."""
        if self.open_step is not None:
            return []
        self.open_step = "turn-1"
        return [{"type": "STEP_STARTED", "stepName": self.open_step}]

    def _custom(self, name: str, value: Any) -> dict[str, Any]:
        return {"type": "CUSTOM", "name": name, "value": value}

    def run_finished(self, outcome: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        frames = self._close_step()
        frame: dict[str, Any] = {
            "type": "RUN_FINISHED",
            "threadId": self.thread_id,
            "runId": self.run_id,
        }
        if outcome is not None:
            frame["outcome"] = outcome
        frames.append(frame)
        self.terminal_sent = True
        return frames

    def run_error(self, message: str) -> list[dict[str, Any]]:
        frames = self._close_step()
        frames.append({"type": "RUN_ERROR", "message": message})
        self.terminal_sent = True
        return frames

    def map(self, event: Any) -> list[dict[str, Any]]:
        if event is None:
            return []

        if isinstance(event, TurnStartedEvent):
            frames = self._close_step()
            self.open_step = f"turn-{event.turn}"
            self.last_message_id = None  # no assistant message in this turn yet
            frames.append({"type": "STEP_STARTED", "stepName": self.open_step})
            return frames

        if isinstance(event, TextEvent):
            if not event.text:
                return []
            message_id = uuid.uuid4().hex
            self.last_message_id = message_id  # parent for this turn's tool calls
            return [
                {"type": "TEXT_MESSAGE_START", "messageId": message_id, "role": "assistant"},
                {"type": "TEXT_MESSAGE_CONTENT", "messageId": message_id, "delta": event.text},
                {"type": "TEXT_MESSAGE_END", "messageId": message_id},
            ]

        if isinstance(event, ToolCallEvent):
            self._seen_starts.add(event.tool_call_id)
            start: dict[str, Any] = {
                "type": "TOOL_CALL_START",
                "toolCallId": event.tool_call_id,
                "toolCallName": event.tool_name,
                # always present so consumers can key on the field; null when no
                # preceding text turn has established an assistant message id
                "parentMessageId": self.last_message_id,
            }
            return self._ensure_step() + [
                start,
                {
                    "type": "TOOL_CALL_ARGS",
                    "toolCallId": event.tool_call_id,
                    "delta": json.dumps(event.arguments, default=str),
                },
                {"type": "TOOL_CALL_END", "toolCallId": event.tool_call_id},
            ]

        if isinstance(event, ToolResultEvent):
            if event.ok:
                result = event.result
                content = result if isinstance(result, str) else json.dumps(
                    result.model_dump(mode="json", by_alias=True, exclude_none=True)
                    if isinstance(result, BaseModel)
                    else result,
                    default=str,
                )
            else:
                content = str(event.error) if event.error is not None else "tool failed"
            # _ensure_step: a resume run delivers this result with no prior
            # TurnStartedEvent, so open a synthetic step to enclose it (§5.3).
            frames = self._ensure_step()
            # On a resume run the TOOL_CALL_START/ARGS/END lifecycle occurred in
            # the PREVIOUS interrupted stream. Strict AG-UI clients reject an
            # orphan TOOL_CALL_RESULT with no open tool-call, so we inject
            # synthetic START + END before the RESULT (§5.3).
            if event.tool_call_id not in self._seen_starts:
                synthetic_start: dict[str, Any] = {
                    "type": "TOOL_CALL_START",
                    "toolCallId": event.tool_call_id,
                    "toolCallName": event.tool_name,
                    "parentMessageId": self.last_message_id,
                }
                frames += [
                    synthetic_start,
                    # AG-UI spec requires ≥1 TOOL_CALL_ARGS between START and END.
                    # On the resume path we have no original args, so emit empty JSON.
                    {"type": "TOOL_CALL_ARGS", "toolCallId": event.tool_call_id, "delta": "{}"},
                    {"type": "TOOL_CALL_END", "toolCallId": event.tool_call_id},
                ]
            frames.append(
                {
                    "type": "TOOL_CALL_RESULT",
                    # spec: fresh UUID, never derived from tool_call_id (§5.3)
                    "messageId": uuid.uuid4().hex,
                    "toolCallId": event.tool_call_id,
                    "content": content,
                    "role": "tool",
                }
            )
            return frames

        if isinstance(event, ToolProgressEvent):
            # GH-88: interim event from an async-generator tool.
            return [self._custom(
                "TOOL_PROGRESS",
                {"message": event.message, "toolName": event.tool_name},
            )]

        if isinstance(event, ProgressEvent):
            return [self._custom("AGENT_PROGRESS", {"message": event.message})]

        if isinstance(event, NoteEvent):
            return [self._custom("AGENT_NOTE", {"note": event.note})]

        if isinstance(event, ArtifactEvent):
            payload = event.model
            if isinstance(payload, ContentModel):
                data = payload.wire()
            elif isinstance(payload, BaseModel):
                data = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
            else:
                data = payload
            frames = [
                self._custom(
                    "AGENT_ARTIFACT",
                    {"dataType": event.data_type, "toolName": event.tool_name, "data": data},
                )
            ]
            if isinstance(payload, ContentModel):
                a2ui_messages = translate(payload, capabilities=self.capabilities.for_custom_emit())
                if a2ui_messages is not None:
                    # RT-001: SC-D1 + RT-004 validation, mirroring
                    # runner.py::build_artifact's A2A path exactly via the
                    # shared split_a2ui_delivery_validated() boundary, so a
                    # malformed translate() output (e.g. a custom domain-card
                    # translate() that is entirely deleteSurface) fails this
                    # transport too instead of silently emitting an empty
                    # A2UI_UPDATE {"messages": []} and letting the run
                    # succeed. Raises ValueError, caught by the enclosing
                    # stream() try/except and reported as RUN_ERROR (§5.3) —
                    # the same "every failure after RUN_STARTED becomes a
                    # RUN_ERROR frame" contract every other exception here
                    # already follows.
                    #
                    # Critical protocol-conformance fix: deleteSurface must
                    # never share a delivered array with its own surface's
                    # create/populate messages — a spec-conformant Path-A
                    # renderer folds one delivered array atomically and
                    # paints once after the fold, so a bundled deleteSurface
                    # would unmount the surface before it ever painted (see
                    # split_a2ui_delivery() docstring). Deliver the open and
                    # close arrays as two separate A2UI_UPDATE CUSTOM events,
                    # open first — each event a self-contained fold+paint
                    # unit. Named envelope so consumers can key on
                    # value.messages (spec: CUSTOM.value carries the A2UI
                    # message array).
                    open_messages, close_messages = split_a2ui_delivery_validated(
                        payload, a2ui_messages
                    )
                    frames.append(self._custom("A2UI_UPDATE", {"messages": open_messages}))
                    if close_messages:
                        frames.append(self._custom("A2UI_UPDATE", {"messages": close_messages}))
            return frames

        if isinstance(event, InterruptEvent):
            # camelCase keys, consistent with the rest of the AG-UI wire and
            # with the A2A interrupt metadata (runner.py); resume reads accept
            # both casings for back-compat (§5.3).
            interrupt: dict[str, Any] = {
                "id": event.interrupt_id,
                "reason": event.reason,
                "message": event.message,
            }
            if event.response_schema:
                interrupt["responseSchema"] = event.response_schema
            if event.tool_call_id is not None:
                interrupt["toolCallId"] = event.tool_call_id
            if event.expires_in is not None:
                # upstream ag-ui-protocol's Interrupt.expires_at is
                # Optional[str] (ISO-8601, e.g. "2026-04-20T17:00:00Z") —
                # NOT epoch-ms; a reference-SDK consumer would fail to
                # parse a numeric value. Confirmed by direct package
                # inspection of installed ag-ui-protocol==0.1.19
                # (PyPI: https://pypi.org/project/ag-ui-protocol/0.1.19/),
                # site-packages/ag_ui/core/types.py:259-270, class
                # `Interrupt(ConfiguredBaseModel)` declares
                # `expires_at: Optional[str] = None` with no further format
                # constraint — the package itself does not mandate
                # ISO-8601 over another string encoding, so ISO-8601 UTC
                # is this SDK's own interoperable-default choice, not an
                # upstream-mandated one. Full citation + reasoning:
                # workspace/learning/LRN-111-agui-interrupt-expires-at-wire-format-citation.md
                # (RT-002 citation).
                #
                # event.expires_in is seconds-remaining-until-expiry, a
                # relative duration computed by the task store (see
                # TaskStore.interrupt_ttl_remaining) — NOT a raw reading
                # from whichever clock the store happens to use internally
                # (time.monotonic for the in-memory store; a durable
                # cross-process store may use time.time instead). Adding it
                # to wall-clock now is therefore correct regardless of the
                # store's clock choice (RT-001).
                wall_deadline = time.time() + event.expires_in
                interrupt["expiresAt"] = iso_utc(wall_deadline)
            return self.run_finished(
                outcome={"type": "interrupt", "interrupts": [interrupt]}
            )

        if isinstance(event, DoneEvent):
            if event.ok:
                return self.run_finished()
            return self.run_error(
                str(event.error) if event.error is not None else "run failed"
            )

        return []  # UsageEvent and anything future: no AG-UI frame


# ── route ──


def _capabilities(body: dict[str, Any]) -> A2uiCapabilities:
    # The fail-closed default itself lives in A2uiCapabilities.gated (C-006)
    # so this transport cannot drift from a2a.py's independently.
    forwarded = body.get("forwardedProps")
    if not isinstance(forwarded, dict) or "a2uiClientCapabilities" not in forwarded:
        return A2uiCapabilities.gated(False, None)
    return A2uiCapabilities.gated(True, forwarded["a2uiClientCapabilities"])


def _start_worker(request: Request, record: TaskRecord, capabilities: A2uiCapabilities) -> None:
    state = request.app.state
    # Bind per-call forwarded credentials BEFORE create_task so the worker
    # snapshots them via contextvars (mirrors the A2A route pattern).
    forwarding.bind(forwarding.parse_header(request.headers.get(forwarding.HEADER_NAME)))
    record.worker = asyncio.get_running_loop().create_task(
        run_task_worker(
            store=state.task_store,
            record=record,
            model=state.model_client,
            registry=state.registry,
            adapters=state.adapters,
            skills=state.skills,
            system=state.system_prompt,
            capabilities=capabilities,
            policies=state.loop_policies,
        )
    )


@router.post("/ag-ui/run")
async def ag_ui_run(
    request: Request, identity: Identity = Depends(require_identity)
) -> Response:
    guard_origin(request)
    ct = request.headers.get("content-type", "")
    if ct and "application/json" not in ct:
        return Response(status_code=415)
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return Response(status_code=413, content=b"request body too large")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict):
            body = {}
    except (json.JSONDecodeError, ValueError):
        body = {}

    # threadId/runId echo back on every frame; synthesize when absent so we
    # never emit empty correlation ids (§5.3).
    raw_thread = body.get("threadId")
    raw_run = body.get("runId")
    thread_id = raw_thread if isinstance(raw_thread, str) and raw_thread else uuid.uuid4().hex
    run_id = raw_run if isinstance(raw_run, str) and raw_run else uuid.uuid4().hex
    store = request.app.state.task_store
    mapper = _RunMapper(thread_id, run_id, _capabilities(body))

    async def stream() -> AsyncIterator[bytes]:
        # Transport-level rejections (Origin 403, Content-Type 415, body
        # size 413) already happened above, before this generator was ever
        # constructed. From here on, RUN_STARTED is ALWAYS first; every
        # failure after it becomes a RUN_ERROR frame, not an HTTP error (§5.3)
        yield sse_data({"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id})
        yield sse_data({"type": "STATE_SNAPSHOT", "snapshot": body.get("state") or {}})

        sub = None
        record: TaskRecord | None = None
        try:
            if (problem := _validate(body)) is not None:
                for frame in mapper.run_error(problem):
                    yield sse_data(frame)
                return

            resume_raw = body.get("resume")
            resume = resume_raw if isinstance(resume_raw, list) else []
            if resume:
                if not isinstance(resume[0], dict):
                    for frame in mapper.run_error("invalid resume entry"):
                        yield sse_data(frame)
                    return
                entry = resume[0]
                # accept both casings; emit camelCase (interruptId) ourselves
                interrupt_id = str(entry.get("interruptId") or entry.get("interrupt_id") or "")
                record = store.find_interrupt(interrupt_id, identity)
                if record is None:
                    for frame in mapper.run_error("unknown or expired interrupt"):
                        yield sse_data(frame)
                    return
                sub = store.subscribe(record.task.id)  # subscribe BEFORE resuming
                delivered = store.deliver_resume(
                    record.task.id,
                    {"status": entry.get("status"), "payload": entry.get("payload")},
                )
                if not delivered:
                    for frame in mapper.run_error("interrupt is no longer resumable"):
                        yield sse_data(frame)
                    return
            else:
                folded = _fold_history(body.get("messages") or [])
                if folded is None:
                    for frame in mapper.run_error("no user message in input"):
                        yield sse_data(frame)
                    return
                task = new_task(thread_id)
                record = store.create(task, identity)
                record.messages.extend(folded)
                sub = store.subscribe(task.id)
                _start_worker(request, record, mapper.capabilities)

            while not mapper.terminal_sent:
                try:
                    item = await asyncio.wait_for(sub.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield HEARTBEAT
                    continue
                if item is None:
                    break
                for frame in mapper.map(item.event):
                    yield sse_data(frame)
                if item.final:
                    break
        except StreamTerminated:
            pass
        except Exception:
            logger.exception("ag-ui stream failed")
            if not mapper.terminal_sent:
                for frame in mapper.run_error("internal error"):
                    yield sse_data(frame)
        finally:
            if sub is not None and record is not None:
                store.unsubscribe(record.task.id, sub)

        if not mapper.terminal_sent:
            for frame in mapper.run_error("stream ended unexpectedly"):
                yield sse_data(frame)

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)
