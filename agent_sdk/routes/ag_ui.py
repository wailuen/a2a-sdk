"""AG-UI route — POST /ag-ui/run, SSE (DESIGN.md §5.3).

The task worker publishes ``StreamItem``s carrying raw loop events; this
route owns a per-request state machine that maps them to AG-UI wire frames
(camelCase JSON, ``data:`` lines only). Transport-level rejections —
disallowed Origin (403), wrong Content-Type (415), oversized body (413),
stream admission at capacity (429 + ``Retry-After``, RT-002: this route
holds an indefinite ``text/event-stream`` and is admitted against the same
shared budget as the A2A streams, ``routes/a2a.py``'s ``_admit``) — are
returned/raised before the stream is ever constructed. Once the stream
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
from typing import Any, AsyncIterator, Sequence

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ..a2ui.translator import A2uiCapabilities, translate
from ..agent.runner import new_task, run_task_worker, split_a2ui_delivery_validated
from ..auth.context import ResumeEnvelope, bind_identity, unbind_identity
from ..auth.identity import Identity
from ..auth.middleware import require_identity
from ..common.iso8601 import iso_utc
from ..common.origin import guard_origin
from ..common.redact import frame_locations
from ..common.json_strict import loads_strict
from ..common import sse as _sse
from ..common.sse import HEARTBEAT, SSE_HEADERS, sse_data
from ..credentials import forwarding
from ..models.content_types import ContentModel, MarketBriefing
from ..models.a2a import TERMINAL_STATES
from ..tasks.store import StreamTerminated, TaskRecord
# RT-002: POST /ag-ui/run is the THIRD authenticated, indefinitely-held
# text/event-stream on the same single-process connection pool, and it
# shares the task store, the worker pool and the token budget with the A2A
# streams. It is admitted against the SAME `_a2a_streams()` budget for the
# identical reason routes/mcp.py's comment gives for sharing one budget
# across GET /mcp and GET /mcp/sse: capping one transport is trivially
# bypassed by calling the other.
from .a2a import _admit as _admit_stream
from .a2a import cancel_task_record
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
MAX_MESSAGE_CHARS = 32000
_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB — mirrors MCP/OAuth caps
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


# ── history fold (processing, not rejection — §5.3) ──


def _cut_middle(content: str, limit: int) -> str:
    """Keep head and tail; the marker counts within ``limit`` (GH-168)."""
    omitted = len(content)
    while True:
        marker = f"\n[... {omitted} chars omitted ...]\n"
        keep = limit - len(marker)
        new_omitted = len(content) - keep
        if new_omitted == omitted:
            break
        omitted = new_omitted
    head = keep - keep // 2
    tail = keep // 2
    return content[:head] + marker + content[len(content) - tail :]


def _fold_history(
    raw_messages: list[Any], max_chars: int
) -> list[dict[str, Any]] | None:
    """AG-UI messages → Converse format. Truncates (50 msgs; messages over
    ``max_chars`` keep head and tail with an omission marker),
    skips blank assistant turns, merges consecutive same-role turns, drops
    a leading assistant prefix. None when no user content survives.

    Control characters are STRIPPED — never rejected — from every folded
    string (RT-001). The AG-UI client re-submits the full conversation history
    each turn with BOTH its own user turns and the model's streamed assistant
    turns folded back in (chat.js). If any single control char in that replayed
    content could hard-reject the run, one ESC/NUL/BEL emitted in the model's
    own output would turn every subsequent turn into RUN_ERROR and permanently
    brick the session. Stripping here — the one function that builds the model
    input, covering every content shape uniformly — guarantees nothing
    unsafe reaches the model, mirroring the loop.py unknown-tool sanitizer.

    Content that is neither a string nor a list folds to "" — a structured
    value is never stringified into model input (GH-159)."""
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
            # Never str() a structured value into model input (GH-159): a
            # dict-shaped part would otherwise reach the model verbatim,
            # binary payload included. User messages in this shape are
            # rejected by _validate (_user_content_problem) in the current turn;
            # this is the backstop for earlier history and every other role.
            content = ""
        content = _CONTROL_CHARS.sub("", content)
        if role == "assistant" and not content.strip():
            continue
        if len(content) > max_chars:
            logger.warning(
                "ag-ui history message truncated from %d to %d chars",
                len(content),
                max_chars,
            )
            content = _cut_middle(content, max_chars)
        if folded and folded[-1]["role"] == role:
            folded[-1]["content"].append({"text": content})
        else:
            folded.append({"role": role, "content": [{"text": content}]})
    while folded and folded[0]["role"] != "user":
        folded.pop(0)
    return folded or None


_KNOWN_PART_TYPES = frozenset({"binary", "image", "audio", "file", "document"})


def _user_content_problem(content: Any) -> str | None:
    """GH-159 shape + part-type check for ONE user message's ``content``.

    Every shape the payload can arrive in is classified here, not only the
    expected list: absent/string content is accepted, a list must hold only
    ``text`` parts, and ANY other shape (a bare part object, a number, ...) is
    rejected outright. Skipping an unexpected shape would let it fall through
    to _fold_history unchecked — the allowlist must be total."""
    if content is None or isinstance(content, str):
        return None
    if not isinstance(content, list):
        return "user message content must be a string or a list of parts"
    for part in content:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind != "text":
            label = kind if isinstance(kind, str) and kind in _KNOWN_PART_TYPES else "unknown"
            return f"unsupported user content part type: {label}; only text parts are accepted"
    return None


def _is_resume(body: dict[str, Any]) -> bool:
    resume_raw = body.get("resume")
    return isinstance(resume_raw, list) and bool(resume_raw)


def _validate(body: dict[str, Any]) -> str | None:
    """Returns an error message (→ RUN_ERROR) or None.

    The non-text part rejection (GH-159, maintainer ruling: no silent drop)
    applies to the CURRENT turn only — the user message(s) after the last
    assistant message (every content shape, see ``_user_content_problem``) —
    and is skipped on resume runs. Earlier history is not re-checked: those
    parts were already rejected on their own turn, and re-rejecting them would
    lock a client that keeps a rejected message in its history out of the
    thread (ruling refinement, issue 159 comment 6135432947); _fold_history
    drops their non-text parts. The part type echoed in the error is mapped to
    a fixed allowlist (SI-2), never the client's raw string.

    Apart from the GH-159 non-text part check, only the STRUCTURAL shape of
    ``messages`` is rejected here. Message CONTENT is never hard-rejected — not on control characters, not on unexpected part
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
    if _is_resume(body):
        return None
    msgs = messages or []
    last_assistant = max(
        (i for i, m in enumerate(msgs) if isinstance(m, dict) and m.get("role") == "assistant"),
        default=-1,
    )
    for m in msgs[last_assistant + 1:]:
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        if (problem := _user_content_problem(m.get("content"))) is not None:
            return problem
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
        frame["outcome"] = outcome if outcome is not None else {"type": "success"}
        frames.append(frame)
        self.terminal_sent = True
        return frames

    def run_error(self, message: str, code: str | None = None) -> list[dict[str, Any]]:
        frames = self._close_step()
        frame: dict[str, Any] = {"type": "RUN_ERROR", "message": message}
        if code is not None:
            frame["code"] = code
        frames.append(frame)
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
            }
            if self.last_message_id is not None:
                start["parentMessageId"] = self.last_message_id
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
                }
                if self.last_message_id is not None:
                    synthetic_start["parentMessageId"] = self.last_message_id
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
            if isinstance(payload, MarketBriefing):
                # GH-179: wire() is a bare string now; the frame keeps the
                # pre-existing field-dict shape (same as the A2A DataPart).
                data: Any = payload.model_dump(mode="json", by_alias=True, exclude_none=True)
            elif isinstance(payload, ContentModel):
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
                str(event.error) if event.error is not None else "run failed",
                event.code or "internal",
            )

        # UsageEvent, AuditEvent (RT-009: internal audit records must never
        # reach the console as a chat/CUSTOM frame) and anything future: no
        # AG-UI frame.
        return []


# ── route ──


def _capabilities(body: dict[str, Any]) -> A2uiCapabilities:
    # The fail-closed default itself lives in A2uiCapabilities.gated (C-006)
    # so this transport cannot drift from a2a.py's independently.
    forwarded = body.get("forwardedProps")
    if not isinstance(forwarded, dict) or "a2uiClientCapabilities" not in forwarded:
        return A2uiCapabilities.gated(False, None)
    return A2uiCapabilities.gated(True, forwarded["a2uiClientCapabilities"])


def _user_timezone(body: dict[str, Any]) -> str | None:
    forwarded = body.get("forwardedProps")
    if not isinstance(forwarded, dict):
        return None
    return forwarded.get("timezone")


def _parse_body(raw: bytes) -> dict[str, Any] | None:
    """The body as an object, or ``None`` when it is not JSON or not an object."""
    try:
        body = loads_strict(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _resume_interrupt_id(body: dict[str, Any]) -> str:
    """The interrupt id this run would resume, or ``""`` when it is a fresh
    run. Shared by the pre-admission task-id lookup and ``_run()`` itself so
    the two can never disagree about which entry is being resumed."""
    resume_raw = body.get("resume")
    if not isinstance(resume_raw, list) or not resume_raw:
        return ""
    entry = resume_raw[0]
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("interruptId") or entry.get("interrupt_id") or "")


def _resume_target_task_id(
    request: Request, body: dict[str, Any], identity: Identity
) -> str | None:
    """Task id this run will subscribe to when it is a resume, else ``None``.

    RT-001 (round 6): the shared budget's per-task subscriber cap is documented
    (DESIGN.md §5.5, docs/protocols.md) as covering ``/ag-ui/run``, and this
    route's resume branch is the one AG-UI path that subscribes to an ALREADY
    EXISTING task — the growth of ``record.subscriptions`` that the cap exists
    to bound, since ``store.publish`` walks that list for every frame. Resolving
    the id here, before ``_admit``, is what lets the cap be enforced as a real
    ``429`` alongside the route's other transport-level rejections.

    It cannot be checked later, inside ``_run()``: everything there is past
    ``RUN_STARTED``, where §5.3 forbids an HTTP error, so an over-cap resume
    could only be reported as a ``RUN_ERROR`` frame on a run that had already
    been announced. And it does not weaken RT-001 (round 4)'s ordering rule —
    an identity-bound interrupt lookup creates no task and sheds no other
    caller's stream, so a request rejected after it is still a pure no-op on
    the capacity-bounded store.

    ``None`` covers both "fresh run" (the task is minted inside ``_run()``, so a
    per-task count would be vacuously 0 anyway, exactly as on A2A's no-taskId
    ``message:stream`` path) and "no such interrupt" (``_run()`` answers that
    with ``RUN_ERROR``, which is the accurate outcome — not a capacity 429).
    """
    interrupt_id = _resume_interrupt_id(body)
    if not interrupt_id:
        return None
    record = request.app.state.task_store.find_interrupt(interrupt_id, identity)
    return record.task.id if record is not None else None


def _start_worker(
    request: Request,
    record: TaskRecord,
    capabilities: A2uiCapabilities,
    identity: Identity,
    *,
    extra_resolved_messages: Sequence[dict[str, Any]] | None = None,
    user_timezone: str | None = None,
) -> None:
    state = request.app.state
    # Bind per-call forwarded credentials BEFORE create_task so the worker
    # snapshots them via contextvars (mirrors the A2A route pattern).
    forwarding.bind(forwarding.parse_header(request.headers.get(forwarding.HEADER_NAME)))
    identity_token = bind_identity(identity)
    try:
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
                extra_resolved_messages=extra_resolved_messages,
                inject_date=state.inject_current_date,
                timezone_name=state.timezone,
                user_timezone=user_timezone,
            )
        )
    finally:
        unbind_identity(identity_token)


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

    # Parsed BEFORE admission (RT-001, round 6) purely so the resume branch's
    # target task id is known to `_admit`. Parsing allocates nothing durable,
    # so this does not move any state mutation ahead of the load-shed check.
    parsed_body = _parse_body(raw)
    body = parsed_body if parsed_body is not None else {}

    # RT-002: admit against the shared A2A stream budget BEFORE any durable
    # state mutation (store.create() happens inside stream() below) and
    # before the StreamingResponse — the same ordering rule RT-001 forced on
    # message:stream. This sits with the other transport-level rejections
    # (403/415/413) and therefore precedes RUN_STARTED, so the §5.3 rule
    # "every failure AFTER RUN_STARTED is a RUN_ERROR frame, not an HTTP
    # error" is preserved: a shed request never starts a run at all.
    #
    # RT-001 (round 6): the task id is the resume target when this is a resume
    # run — that branch subscribes to an EXISTING task, so it is the AG-UI path
    # the shared budget's per-task subscriber cap has to cover (see
    # `_resume_target_task_id`). It stays None for a fresh run, whose task is
    # minted inside `_run()`; the global and per-identity caps, which bound
    # process load and cross-tenant fairness, apply on both branches.
    slot = await _admit_stream(
        request, identity, _resume_target_task_id(request, body, identity)
    )

    # threadId/runId echo back on every frame; synthesize when absent so we
    # never emit empty correlation ids (§5.3).
    raw_thread = body.get("threadId")
    raw_run = body.get("runId")
    thread_id = raw_thread if isinstance(raw_thread, str) and raw_thread else uuid.uuid4().hex
    run_id = raw_run if isinstance(raw_run, str) and raw_run else uuid.uuid4().hex
    store = request.app.state.task_store
    mapper = _RunMapper(thread_id, run_id, _capabilities(body))

    def _emit(frames: list[dict[str, Any]], *, what: str = "invalid agent response") -> bytes:
        # GH-173 (RT-002): sse_data refuses non-finite floats (allow_nan=False).
        # Ingress rejects them (loads_strict), but a frame can still carry one
        # from a path that bypassed validation. Serialize frame by frame; on the
        # first frame that cannot be written, drop it and close the run with
        # exactly one fixed-text RUN_ERROR (§5.3, SI-2) — never let the
        # ValueError cut the stream with no terminal frame. Any already-
        # serialized frames in the batch are kept, so a STEP_FINISHED that
        # preceded a bad RUN_FINISHED still reaches the client.
        out: list[bytes] = []
        for frame in frames:
            try:
                out.append(sse_data(frame))
            except ValueError:
                logger.error(
                    "ag-ui frame not serializable frame_type=%s run_id=%s",
                    frame.get("type"),
                    run_id,
                )
                # the bad frame may itself have been the terminal one
                mapper.terminal_sent = False
                out.extend(sse_data(f) for f in mapper.run_error(what, "internal"))
                break
        return b"".join(out)

    owned: list[TaskRecord] = []

    def _cancel_if_unfinished() -> None:
        # GH-217: a run whose stream ends before its terminal frame (client
        # disconnect or cancellation) is cancelled; a run parked on an
        # interrupt already sent its terminal RUN_FINISHED and is left alone.
        if mapper.terminal_sent or not owned:
            return
        run_record = owned.pop()
        if run_record.task.status.state in TERMINAL_STATES:
            return
        cancel_task_record(run_record, store)

    async def _finish() -> None:
        _cancel_if_unfinished()
        await slot.release()

    async def _run() -> AsyncIterator[bytes]:
        # Transport-level rejections (Origin 403, Content-Type 415, body
        # size 413, admission 429) already happened above, before this
        # generator was ever constructed. From here on, RUN_STARTED is ALWAYS
        # first; every failure after it becomes a RUN_ERROR frame, not an
        # HTTP error (§5.3)
        # threadId/runId come from loads_strict (which refuses any string a
        # writer cannot encode) or uuid4, so this cannot fail today; it still
        # goes through the guarded _emit so no sse_data call here is unguarded
        # (LRN-363).
        yield _emit([{"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id}])
        if mapper.terminal_sent:
            return
        yield _emit(
            [{"type": "STATE_SNAPSHOT", "snapshot": body.get("state") or {}}],
            what="invalid state",
        )
        if mapper.terminal_sent:
            return

        sub = None
        record: TaskRecord | None = None
        try:
            if parsed_body is None:
                yield _emit(mapper.run_error("malformed RunAgentInput body", "validation"))
                return
            if (problem := _validate(body)) is not None:
                yield _emit(mapper.run_error(problem, "validation"))
                return

            resume_raw = body.get("resume")
            resume = resume_raw if isinstance(resume_raw, list) else []
            if resume:
                if not isinstance(resume[0], dict):
                    yield _emit(mapper.run_error("invalid resume entry", "validation"))
                    return
                entry = resume[0]
                # accept both casings; emit camelCase (interruptId) ourselves
                interrupt_id = _resume_interrupt_id(body)
                record = store.find_interrupt(interrupt_id, identity)
                if record is None:
                    yield _emit(mapper.run_error("unknown or expired interrupt", "not_found"))
                    return
                # RT-001 (round 6): subscribe THROUGH the admission slot, never
                # against the store directly. That is what registers this task
                # id on the slot — so the shared budget's per-task cap counts
                # AG-UI subscribers instead of under-counting them for the A2A
                # routes that share it — and what makes `slot.release` this
                # subscription's teardown on all three release layers, not just
                # the inner generator's `finally` below.
                sub = slot.subscribe(record.task.id)  # subscribe BEFORE resuming
                delivered = store.deliver_resume(
                    record.task.id,
                    ResumeEnvelope(
                        {"status": entry.get("status"), "payload": entry.get("payload")},
                        identity,
                    ),
                )
                if not delivered:
                    yield _emit(mapper.run_error("interrupt is no longer resumable", "not_found"))
                    return
                owned.append(record)
            else:
                folded = _fold_history(
                    body.get("messages") or [],
                    request.app.state.settings.agui_max_message_chars,
                )
                if folded is None:
                    yield _emit(mapper.run_error("no user message in input", "validation"))
                    return
                task = new_task(thread_id)
                record = store.create(task, identity)
                record.messages.extend(folded)
                # Through the slot, for the same reason as the resume branch:
                # the freshly minted id is what the per-task cap and
                # `slot.release`'s unsubscribe both have to see (RT-001, r6).
                sub = slot.subscribe(task.id)
                # RT-001: context_reusable_messages() scans EVERY terminal
                # task in this thread, not only the most recent one —
                # AG-UI's TaskRecord.messages never inherits a prior run's
                # messages the way A2A's does (record.messages stays scoped
                # to this run's own folded text, §5.3 design), so a
                # __resolved__ marker folded in run N would otherwise stop
                # being visible the moment any later, unrelated run N+1
                # becomes the newest terminal task — decaying after exactly
                # one intervening run instead of surviving for the
                # conversation's life. RT-009: never honours an admin
                # api_key's cross-identity override, same as
                # context_messages() (RT-004) — this side channel produces
                # no frame and no user-visible history, so admin
                # task-inspection privilege must not leak another identity's
                # resolved values in. Only used to seed run_loop's
                # resolved_index (GH-148); never appended to record.messages
                # or shown to the model.
                prior = store.context_reusable_messages(thread_id, identity)
                _start_worker(
                    request, record, mapper.capabilities, identity,
                    extra_resolved_messages=prior,
                    user_timezone=_user_timezone(body),
                )
                owned.append(record)

            while not mapper.terminal_sent:
                try:
                    item = await asyncio.wait_for(sub.get(), timeout=_sse.STREAM_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield HEARTBEAT
                    continue
                if item is None:
                    break
                if chunk := _emit(mapper.map(item.event)):
                    yield chunk
                if item.final:
                    break
        except StreamTerminated:
            pass
        except Exception as exc:
            # SI-2 / LRN-214 (RT-001): mapper.map() runs payload.wire(),
            # translate() and to_plain_text() inside this try, so a domain
            # ContentModel or custom translator that raises a pydantic
            # ValidationError lands here with `input_value='<tool output>'`
            # in its message. `logger.exception`/`exc_info=True` would format
            # that message (and any chained cause) into the log. Log the
            # exception TYPE plus frame_locations() (file:line only, never
            # source text) — the same contract as routes/mcp.py's dispatch
            # catch-all and routes/admin.py's try-tool.
            logger.error(
                "ag-ui stream failed error_type=%s frames=%s",
                type(exc).__name__,
                frame_locations(exc),
            )
            if not mapper.terminal_sent:
                yield _emit(mapper.run_error("internal error", "internal"))
        finally:
            if sub is not None and record is not None:
                store.unsubscribe(record.task.id, sub)

        if not mapper.terminal_sent:
            yield _emit(mapper.run_error("stream ended unexpectedly", "internal"))

    async def stream() -> AsyncIterator[bytes]:
        # RT-002: release the admission slot however the run ends. Layered
        # exactly like the A2A path: this `finally` is the fast path, the
        # BackgroundTask below covers a request task cancelled at Starlette's
        # send(http.response.start) checkpoint before the generator body ever
        # starts, and `_prune_a2a_streams` is the liveness backstop.
        # `slot.release` is idempotent, so the layers overlap harmlessly.
        try:
            async for chunk in _run():
                yield chunk
        finally:
            _cancel_if_unfinished()
            await slot.release()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
        background=BackgroundTask(_finish),
    )
