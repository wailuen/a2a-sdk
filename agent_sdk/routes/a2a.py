"""A2A v0.3.0 HTTP+JSON routes (DESIGN.md §5.1).

Success bodies are the bare result object (Task | Message); errors are the
spec ``{"error": {code, message, data?}}`` shape with the §5.1 HTTP status
mapping. All endpoints require an authenticated identity; task access is
identity-bound (mismatch → 404 + -32001, existence never leaked).

A disallowed ``Origin`` is rejected by the shared transport guard
(``common/origin.py``), which raises ``HTTPException(403, "origin not
allowed")``. On this ``/v1/*`` surface that exception does NOT reach the wire
as FastAPI's bare ``{"detail": ...}``: the app-level ``_a2a_auth_envelope``
handler (``app.py``) rewrites EVERY ``/v1/*`` ``HTTPException`` into the A2A
error envelope, so the 403 body is ``{"error": {"code": -32000, "message":
"origin not allowed"}}`` — identical in shape to the 401/403 auth failures on
this surface. A client SHOULD therefore read ``response.json()["error"]``
here. Only the MCP (``/mcp``) and AG-UI (``/ag-ui/run``) surfaces, which have
no such envelope handler, return the guard's bare ``{"detail": ...}`` shape.

RT-B-203: ``X-A2A-Extensions`` means an extension was ACTIVATED for this
response, not merely that the caller asked for it (§5.1) — a conformant
consumer is expected to parse a response for an extension's content only
when the header comes back activated.

RT-002 (debug round 4): that rule is applied per ROUTE, against what each
route actually runs, not per "mutating vs read-only" surface. Only two routes
activate anything: ``message:send`` and ``message:stream`` call
``_capabilities()`` (A2UI) and, via ``_start_worker``, ``forwarding.bind`` /
``forwarding.parse_header`` (credential forwarding). They echo the full
requested subset. Every other route:

- ``tasks/list``, ``tasks/get``, ``tasks/cancel`` — return Task objects and
  run no extension logic at all, so they never echo
  ``CREDENTIAL_FORWARDING_EXTENSION_URI`` (nothing is forwarded) and echo
  ``A2UI_EXTENSION_URI`` only when a Task actually being returned carries a
  part whose ``metadata.mimeType`` is ``application/a2ui+json``
  (``_echo_a2ui_if_present``).
- ``tasks/resubscribe`` — replays a running task's own frames, which genuinely
  can carry A2UI DataParts, so A2UI stays request-gated there; the
  credential-forwarding URI is never echoed, since nothing is forwarded on a
  resubscribe either.

The earlier split (all four "mutating" routes echoing unconditionally)
rationalised itself with a claim that is false for two of them: ``tasks/cancel``
and ``tasks/resubscribe`` cannot activate either extension and both were
returning ``X-A2A-Extensions: <credential-forwarding URI>`` on responses where
nothing had been forwarded.

RT-005: the same false-activation gap survived on ``message:send`` and
``message:stream`` THEMSELVES. Both called ``_echo_extensions`` with the full
activatable set from the route PROLOGUE — before the body was even parsed and
before the resume-vs-new-task branch was known — then reused that same
pre-computed header on every subsequent return: parse errors, config errors,
and the entire resume branch (``_resume_or_error``, which never calls
``_capabilities()`` or ``forwarding.bind``). Fixed by deferring the echo
until the branch that determines it is known: the fresh-task path echoes the
full set only once it has actually called ``_capabilities()`` and
``_start_worker``; parse/config-error returns echo nothing (no branch was
even reached); the resume branch echoes A2UI only via
``_echo_a2ui_if_present`` — the resumed Task's own artifacts, not the
request header alone — and never echoes the credential-forwarding URI, since
a resume never calls ``forwarding.bind``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator, Sequence

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from ..a2ui.translator import A2uiCapabilities
from ..agent.events import DoneEvent
from ..agent.loop import bridge_context_messages
from ..agent.runner import (
    StreamItem,
    new_task,
    repair_dangling_tool_use_safe,
    run_task_worker,
    set_task_status,
)
from ..auth.identity import Identity
from ..auth.middleware import require_identity
from ..credentials import forwarding
from ..common.origin import guard_origin
from ..common.sse import SSE_HEADERS, sse_data
from ..common.wire_errors import a2a_error, a2a_invalid_params, a2a_parse_error
from ..models.a2a import (
    INTERRUPT_STATES,
    TERMINAL_STATES,
    Message,
    MessageSendParams,
    Task,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)
from ..credentials.card import EXTENSION_URI as CREDENTIAL_FORWARDING_EXTENSION_URI
from ..models.content_types import A2UI_EXTENSION_URI, A2UI_MIME_TYPE
from ..models.errors import (
    A2A_CONTENT_TYPE_NOT_SUPPORTED,
    A2A_PUSH_NOTIFICATION_NOT_SUPPORTED,
    A2A_TASK_NOT_CANCELABLE,
    A2A_TASK_NOT_FOUND,
    A2A_UNSUPPORTED_OPERATION,
)
from ..tasks.store import StreamTerminated, TaskRecord

logger = logging.getLogger(__name__)

router = APIRouter()

_SUPPORTED_MODES = {"text", "text/plain", "application/json", A2UI_MIME_TYPE}
_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB — consistent with AG-UI cap

# GH-150: fixed, SDK-authored — never interpolates a tool name, argument, or
# upstream exception text (SI-2). The synthetic toolResult is replayed back
# to the model on the next contextId turn and can reach logs.
_CANCELLED_TOOL_RESULT_TEXT = "tool call cancelled: task was canceled before a result was returned"

# RT-B-204: fixed, SDK-authored (SI-2) — published as the DoneEvent alongside
# tasks_cancel's terminal StreamItem so an AG-UI subscriber's _RunMapper maps
# it to a cancellation-specific RUN_ERROR frame instead of falling through to
# the generic "stream ended unexpectedly" once the frame loop exits with
# terminal_sent still False.
_CANCELLED_RUN_ERROR_TEXT = "task canceled"


_ECHO_EXTENSION_URIS = frozenset({A2UI_EXTENSION_URI, CREDENTIAL_FORWARDING_EXTENSION_URI})

# RT-002 (debug round 4): the subset a route that never calls
# ``forwarding.bind``/``forwarding.parse_header`` may echo. Only
# ``_start_worker`` binds forwarded credentials, so ONLY ``message:send`` and
# ``message:stream`` can ever activate CREDENTIAL_FORWARDING_EXTENSION_URI.
# ``tasks/resubscribe`` replays an already-running task's frames — those frames
# genuinely can carry A2UI DataParts, so A2UI stays request-gated there, but
# nothing is forwarded on a resubscribe and the credential URI must never be
# echoed back as "activated".
_STREAM_ONLY_EXTENSION_URIS = frozenset({A2UI_EXTENSION_URI})


def _echo_extensions(
    request: Request,
    response: Response,
    *,
    activatable: frozenset[str] = _ECHO_EXTENSION_URIS,
) -> None:
    """X-A2A-Extensions: response echoes the activated subset (§5.1).

    SC-A4: credential-forwarding URI is echoed alongside A2UI when requested.

    RT-B-203: reserved for routes where a request genuinely CAN activate an
    extension. ``tasks/list`` and ``tasks/get`` run no extension logic at all
    and must never call this — see ``_echo_a2ui_if_present``.

    RT-002 (debug round 4): ``activatable`` narrows the echo to the URIs THIS
    route can actually activate, because the activation rule is per-route, not
    per-surface. The full default set is correct only for ``message:send`` and
    ``message:stream`` — the two routes that call both ``_capabilities()`` and
    ``forwarding.bind`` (via ``_start_worker``). ``tasks/resubscribe`` passes
    ``_STREAM_ONLY_EXTENSION_URIS``; ``tasks/cancel`` does not call this at
    all (it returns a Task, so it uses ``_echo_a2ui_if_present`` exactly like
    ``tasks/get``).

    RT-005: callers must invoke this ONLY on the code path that has actually
    reached the activation it echoes for — never unconditionally from a route
    entry prologue, before the request's own branch (parse/config failure,
    resume vs. fresh task) is known. ``message:send``/``message:stream`` call
    this exactly once, from the fresh-task branch, immediately after
    ``_capabilities()`` and ``_start_worker`` have run; their resume branch
    uses ``_echo_a2ui_if_present`` instead, and their parse/config-error
    returns call neither helper.
    """
    requested = request.headers.get("x-a2a-extensions", "")
    activated = [
        uri.strip()
        for uri in requested.split(",")
        if uri.strip() in activatable
    ]
    if activated:
        response.headers["X-A2A-Extensions"] = ", ".join(activated)


def _echo_a2ui_if_present(
    tasks: Sequence[Task], request: Request, response: Response
) -> None:
    """RT-B-203: ``tasks/list``/``tasks/get`` echo `A2UI_EXTENSION_URI` only
    when a Task actually being returned carries a part whose
    ``metadata.mimeType`` is ``A2UI_MIME_TYPE`` — never merely because the
    request's own header asked for it (that would echo "activated" on a
    response where no extension behaviour ran at all, see module docstring).
    ``CREDENTIAL_FORWARDING_EXTENSION_URI`` is never echoed here: nothing is
    forwarded on a read.
    """
    requested = request.headers.get("x-a2a-extensions", "")
    if A2UI_EXTENSION_URI not in [u.strip() for u in requested.split(",")]:
        return
    for task in tasks:
        for artifact in task.artifacts or []:
            for part in artifact.parts:
                if (part.metadata or {}).get("mimeType") == A2UI_MIME_TYPE:
                    response.headers["X-A2A-Extensions"] = A2UI_EXTENSION_URI
                    return


def _message_text(message: Message) -> str:
    return "\n".join(p.text for p in message.parts if isinstance(p, TextPart))


def _capabilities(message: Message, request: Request) -> A2uiCapabilities:
    # Gate A2UI on the opt-in header — clients that never sent X-A2A-Extensions
    # containing A2UI_EXTENSION_URI must not receive A2UI DataParts. The
    # fail-closed default itself lives in A2uiCapabilities.gated (C-006) so
    # this transport cannot drift from ag_ui.py's independently.
    extensions = request.headers.get("x-a2a-extensions", "")
    opted_in = A2UI_EXTENSION_URI in [u.strip() for u in extensions.split(",")]
    raw = (message.metadata or {}).get("a2uiClientCapabilities")
    return A2uiCapabilities.gated(opted_in, raw)


def _config_error(params: MessageSendParams) -> JSONResponse | None:
    # RT-005: never takes `headers` — a config error means _capabilities()/
    # _start_worker never ran, so nothing on this request was ever activated.
    config = params.configuration
    if config is None:
        return None
    if config.push_notification_config is not None:
        return a2a_error(
            A2A_PUSH_NOTIFICATION_NOT_SUPPORTED,
            "push notifications are not supported",
        )
    if config.blocking:
        return a2a_error(
            A2A_UNSUPPORTED_OPERATION,
            "blocking send is not supported; poll tasks/{id}",
        )
    if config.accepted_output_modes is not None and config.accepted_output_modes:
        if not _SUPPORTED_MODES.intersection(config.accepted_output_modes):
            return a2a_error(
                A2A_CONTENT_TYPE_NOT_SUPPORTED,
                "no acceptable output mode; supported: " + ", ".join(sorted(_SUPPORTED_MODES)),
            )
    return None


async def _parse_send(request: Request) -> MessageSendParams | JSONResponse:
    # RT-005: never takes `headers` — a parse failure means no branch of the
    # route ever ran, so nothing was activated.
    # GH-15: reject non-JSON Content-Type before parsing (A2A §5.1 → -32005/HTTP 415)
    ct = request.headers.get("content-type", "").split(";")[0].strip()
    if ct and ct != "application/json":
        return a2a_error(A2A_CONTENT_TYPE_NOT_SUPPORTED, "Content-Type must be application/json")
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return a2a_invalid_params("request body too large")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return a2a_parse_error("request body is not valid JSON")
    except ValueError:
        return a2a_invalid_params("request body is not valid JSON")
    try:
        params = MessageSendParams.model_validate(body)
    except ValidationError as exc:
        # report offending field LOCATIONS only — never echo submitted values
        # (secrets hygiene). e.g. "message.messageId, message.parts".
        fields = ", ".join(
            ".".join(str(loc) for loc in e["loc"]) for e in exc.errors()[:3]
        )
        detail = f"invalid message params (check: {fields})" if fields else "invalid message params"
        return a2a_invalid_params(detail)
    return params


def _start_worker(request: Request, record: TaskRecord, capabilities: A2uiCapabilities) -> None:
    state = request.app.state
    # Bind any per-call forwarded credentials BEFORE create_task so the worker
    # snapshots them (contextvars copy at task creation). Bound to the original
    # submit — a later resume runs in the worker's context, not the resume
    # request's (acceptable: this surface has no credential-bearing resume).
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


def _create_task_record(request: Request, params: MessageSendParams, identity: Identity) -> TaskRecord:
    msg = params.message
    task = new_task(msg.context_id)
    # LRN-048: never mutate the inbound Message; archive a copy with server-assigned
    # contextId only (A2A §3 — role='user' entries do not carry server taskId).
    history_entry = msg.model_copy(update={"context_id": task.context_id})
    task.history = [history_entry]
    record = request.app.state.task_store.create(task, identity)
    # A2A §3 contextId continuation: carry prior conversation history into the
    # new task so the model can reference entities from earlier turns.
    # RT-002/RT-B-202: bridge_context_messages (agent/loop.py) re-asserts the
    # never-ends-on-`user` invariant on the store-supplied transcript — a
    # durable TaskStore subclass, or any record persisted before GH-147's
    # fix, can return one ending on `user` — without this route calling the
    # loop-internal bridge helper directly (LRN-144: that helper has exactly
    # one call site, inside agent/runner.py::repair_dangling_tool_use).
    prior = request.app.state.task_store.context_messages(task.context_id, identity)
    record.messages.extend(bridge_context_messages(prior))
    record.messages.append({"role": "user", "content": [{"text": _message_text(msg) or " "}]})
    return record


def _resume_or_error(
    request: Request, params: MessageSendParams, identity: Identity
) -> TaskRecord | JSONResponse:
    # RT-005: never takes `headers` — a resume never calls _capabilities()/
    # forwarding.bind, so none of its error returns ever activated anything.
    # Its success return echoes A2UI itself, via _echo_a2ui_if_present.
    msg = params.message
    store = request.app.state.task_store
    record = store.get(msg.task_id, identity)
    if record is None:
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    state = record.task.status.state
    if state in TERMINAL_STATES:
        # A2A-F1: use -32004 (UnsupportedOperation) for terminal-task message/send.
        # -32002 (TaskNotCancelable) is exclusively for tasks/cancel; using it here
        # misleads consumers that check the method→code mapping table.
        return a2a_error(
            A2A_UNSUPPORTED_OPERATION,
            "task is in a terminal state and cannot accept new messages",
        )
    if state not in INTERRUPT_STATES:
        # working task not awaiting input: continuing it is not a supported op
        return a2a_error(A2A_UNSUPPORTED_OPERATION, "task is not awaiting input")
    if msg.context_id and msg.context_id != record.task.context_id:
        return a2a_invalid_params("contextId does not match the task")
    delivered = store.deliver_resume(record.task.id, _message_text(msg))
    if not delivered:
        # lost the race: interrupt was consumed/expired between check and deliver
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    # LRN-048: never mutate the inbound Message; archive a copy with server-assigned
    # contextId only (role='user' entries do not carry server taskId per A2A §3).
    history_entry = msg.model_copy(update={"context_id": record.task.context_id})
    record.task.history = (record.task.history or []) + [history_entry]
    return record


def _task_wire(record: TaskRecord, history_length: int | None = None) -> dict[str, Any]:
    wire = record.task.wire()
    if history_length is not None and "history" in wire:
        n = max(history_length, 0)  # negative clamps to 0 (empty), never full
        wire["history"] = wire["history"][-n:] if n else []
    return wire


# ── endpoints ──


@router.post("/v1/message:send")
async def message_send(
    request: Request, response: Response, identity: Identity = Depends(require_identity)
) -> Any:
    guard_origin(request)
    # RT-005: no echo here — the request's own branch (parse/config failure,
    # resume vs. fresh task) is not known yet, so nothing has activated
    # anything. Each return below decides its own echo, if any.
    params = await _parse_send(request)
    if isinstance(params, JSONResponse):
        return params
    if (err := _config_error(params)) is not None:
        return err
    if params.message.task_id:
        record = _resume_or_error(request, params, identity)
        if isinstance(record, JSONResponse):
            return record
        # RT-005: a resume never calls _capabilities()/forwarding.bind, so
        # only A2UI can ever be echoed here, and only when the resumed
        # Task's OWN artifacts genuinely carry an A2UI part.
        _echo_a2ui_if_present([record.task], request, response)
        return JSONResponse(_task_wire(record), headers=dict(response.headers))
    # SC-A1: bare-Message quick-response path (A2A v0.3.0 §2).
    # Call the optional sync_reply hook BEFORE task creation; if it returns a
    # non-empty string, skip task creation and return a bare Message directly.
    # Neither extension can activate here either: no task/worker is created.
    sync_reply_fn = getattr(request.app.state, "sync_reply", None)
    if sync_reply_fn is not None:
        reply_text = sync_reply_fn(params.message)
        if reply_text:
            ctx_id = params.message.context_id or uuid.uuid4().hex
            bare_msg = Message(
                kind="message",
                role="agent",
                messageId=uuid.uuid4().hex,
                contextId=ctx_id,
                parts=[TextPart(kind="text", text=reply_text)],
            )
            return JSONResponse(bare_msg.wire())
    record = _create_task_record(request, params, identity)
    _start_worker(request, record, _capabilities(params.message, request))
    # RT-005: the sole path on this route that can activate either
    # extension — echoed only now that _capabilities()/_start_worker have
    # actually run.
    _echo_extensions(request, response)
    history_length = (
        params.configuration.history_length if params.configuration else None
    )
    return JSONResponse(_task_wire(record, history_length), headers=dict(response.headers))


def _open_stream(
    request: Request, record: TaskRecord
) -> tuple[AsyncIterator[bytes], Any]:
    """Subscribe + snapshot the full-Task first frame EAGERLY (before the
    worker can mutate the record or publish), then return the SSE generator
    plus an abort callback for paths that never iterate it. A severed-
    without-final stream is the documented re-subscribe signal (§5.2)."""
    store = request.app.state.task_store
    sub = store.subscribe(record.task.id)
    snapshot = record.task.wire()
    terminal = record.task.status.state in TERMINAL_STATES

    async def gen() -> AsyncIterator[bytes]:
        try:
            yield sse_data(snapshot)
            if terminal:
                # already terminal: emit the closing status-update so the
                # consumer sees final:true and stops, never a bare snapshot (§5.2).
                yield sse_data(
                    TaskStatusUpdateEvent(
                        taskId=record.task.id,
                        contextId=record.task.context_id,
                        status=record.task.status,
                        final=True,
                    ).wire()
                )
                return
            while True:
                try:
                    item = await sub.get()
                except StreamTerminated:
                    return
                if item is None:
                    return
                if item.frame is not None:
                    yield sse_data(item.frame)
                if item.final:
                    return
        finally:
            store.unsubscribe(record.task.id, sub)

    def abort() -> None:
        store.unsubscribe(record.task.id, sub)

    return gen(), abort


@router.post("/v1/message:stream")
async def message_stream(
    request: Request, response: Response, identity: Identity = Depends(require_identity)
) -> Any:
    guard_origin(request)
    # RT-005: see message_send's identical comment — no echo until the
    # request's own branch is known.
    params = await _parse_send(request)
    if isinstance(params, JSONResponse):
        return params
    if (err := _config_error(params)) is not None:
        return err
    if params.message.task_id:
        # subscribe BEFORE delivering the resume so no frame is missed
        record = request.app.state.task_store.get(params.message.task_id, identity)
        if record is None or record.task.status.state in TERMINAL_STATES:
            # not found OR terminal: no resumable task (consistent with resume path)
            return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
        stream, abort = _open_stream(request, record)
        resumed = _resume_or_error(request, params, identity)
        if isinstance(resumed, JSONResponse):
            abort()
            return resumed
        # RT-005: a resume never calls _capabilities()/forwarding.bind, so
        # only A2UI can ever be echoed here, and only when the task's OWN
        # (already-existing) artifacts genuinely carry an A2UI part.
        _echo_a2ui_if_present([record.task], request, response)
    else:
        record = _create_task_record(request, params, identity)
        stream, _ = _open_stream(request, record)
        _start_worker(request, record, _capabilities(params.message, request))
        # RT-005: the sole path on this route that can activate either
        # extension — echoed only now that _capabilities()/_start_worker
        # have actually run.
        _echo_extensions(request, response)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **dict(response.headers)},
    )


@router.get("/v1/tasks")
async def tasks_list(
    request: Request,
    response: Response,
    pageSize: int = 50,
    pageToken: str | None = None,
    identity: Identity = Depends(require_identity),
) -> Any:
    guard_origin(request)
    size = min(max(pageSize, 1), 100)
    tasks, next_token, total = request.app.state.task_store.list_tasks_for_identity(
        identity, page_size=size, page_token=pageToken
    )
    _echo_a2ui_if_present(tasks, request, response)
    body: dict[str, Any] = {
        "tasks": [t.model_dump(by_alias=True, mode="json", exclude_none=True) for t in tasks],
        "totalSize": total,
        "pageSize": size,
        "nextPageToken": next_token or "",
    }
    return JSONResponse(body, headers=dict(response.headers))


@router.get("/v1/tasks/{task_id}")
async def tasks_get(
    task_id: str,
    request: Request,
    response: Response,
    historyLength: int | None = None,
    identity: Identity = Depends(require_identity),
) -> Any:
    guard_origin(request)
    # GH-25 AC-3 (w012, locked): a colon-bearing task_id (e.g. GET on the shape of
    # /v1/tasks/{id}:cancel) is a wrong-HTTP-verb-on-a-mutation-path miss, not a
    # genuinely unknown task — -32001 there would misleadingly imply "no such task".
    if ":" in task_id:
        return a2a_error(
            A2A_UNSUPPORTED_OPERATION,
            "method not found on this resource",
            headers=dict(response.headers),
        )
    record = request.app.state.task_store.get(task_id, identity)
    if record is None:
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found", headers=dict(response.headers))
    # RT-B-203: echo only if THIS task actually carries an A2UI part — see
    # _echo_a2ui_if_present and the module docstring.
    _echo_a2ui_if_present([record.task], request, response)
    return JSONResponse(_task_wire(record, historyLength), headers=dict(response.headers))


@router.post("/v1/tasks/{task_id}:cancel")
async def tasks_cancel(
    task_id: str, request: Request, response: Response, identity: Identity = Depends(require_identity)
) -> Any:
    guard_origin(request)
    store = request.app.state.task_store
    record = store.get(task_id, identity)
    if record is None:
        return a2a_error(
            A2A_TASK_NOT_FOUND, "task not found", headers=dict(response.headers)
        )
    if record.task.status.state in TERMINAL_STATES:
        return a2a_error(
            A2A_TASK_NOT_CANCELABLE,
            "task is already terminal",
            headers=dict(response.headers),
        )
    # RT-002 (debug round 4): tasks/cancel activates NEITHER extension — it
    # never calls _capabilities() and never calls forwarding.bind/parse_header
    # — so it must not echo either URI merely because the request asked. Its
    # response body is the full canceled Task, exactly like tasks/get's, so it
    # uses the same activation-accurate helper: echo A2UI only when the Task
    # actually being returned carries a real A2UI part. Placed after the
    # not-found / not-cancelable returns for the same reason tasks/get places
    # it after its own: with no Task there is nothing that could have been
    # activated, so those error responses carry no echo (matching
    # test_tasks_get_not_found_never_echoes_credential_forwarding).
    _echo_a2ui_if_present([record.task], request, response)
    hdrs = dict(response.headers)  # RT-B-005: see message_send's identical comment
    if record.worker is not None and not record.worker.done():
        record.worker.cancel()
    # RT-B-001: mirrors InMemoryTaskStore.evict — a long_running (GH-87) tool
    # still deferred at cancel time has already exited run_task_worker's
    # for-loop (record.worker is done), so only record.bg_task's own
    # background awaiter is still running. Leaving it uncancelled lets it
    # resolve the tool call after this CANCELED transition and revert it.
    if record.bg_task is not None and not record.bg_task.done():
        record.bg_task.cancel()
    if record.resume_future is not None and not record.resume_future.done():
        record.resume_future.cancel()
        record.resume_future = None
    record.interrupted = False
    # RT-001/RT-003/RT-004: repair the transcript, then commit CANCELED
    # unconditionally through set_task_status — the single choke point
    # (agent/runner.py, RT-B-008) every other terminal transition already
    # goes through. This call's own response below always reports canceled,
    # so record.task.status must never be rolled back to fake a durable-store
    # failure the client never sees: set_task_status gates the durable
    # persist_status flush on its own persist_messages flush having actually
    # landed, giving the same fail-closed durability the old hand-rolled
    # guard here gave, without defeating the `state in TERMINAL_STATES`
    # guards (e.g. runner.py's `_fail`) that assume a CANCELED task stays
    # CANCELED once this endpoint has returned it as such.
    # RT-B-106/RT-003/RT-001 (debug round 4): a False here means exactly one
    # thing — the in-memory repair failed, so record.messages is untouched and
    # still ends on the dangling toolUse tail. It is threaded straight into
    # set_task_status's own `repaired` gate below, which is what stops the
    # CANCELED status from being durably persisted over that unrepaired
    # transcript. It NEVER reports a durable-write failure: set_task_status
    # owns the durable flush (persist_messages first, persist_status only if
    # that landed), and folding a write failure into this flag would skip that
    # correct path entirely and strand the durable record non-terminal
    # forever. The response below always reports canceled either way.
    repaired = repair_dangling_tool_use_safe(
        record, default_content=[{"text": _CANCELLED_TOOL_RESULT_TEXT}]
    )
    if not repaired:
        logger.warning(
            "repair_dangling_tool_use_safe reported an unrepaired transcript "
            "for task %s during cancel; the CANCELED status will not be "
            "durably persisted over it — see its own error log line above",
            task_id,
        )
    set_task_status(record, TaskState.CANCELED, store=store, repaired=repaired)
    frame = TaskStatusUpdateEvent(
        taskId=record.task.id,
        contextId=record.task.context_id,
        status=record.task.status,
        final=True,
    ).wire()
    body = _task_wire(record)
    try:
        # RT-B-204: pair the A2A frame with its DoneEvent so an AG-UI
        # subscriber's _RunMapper (routes/ag_ui.py) maps this terminal item
        # to a cancellation-specific RUN_ERROR frame — mirroring every other
        # terminal publisher in the SDK (run_task_worker, _run_deferred_background)
        # — instead of falling through to the generic "stream ended
        # unexpectedly" once the frame loop exits with terminal_sent unset.
        store.publish(
            task_id,
            StreamItem(
                frame=frame,
                event=DoneEvent(ok=False, error=_CANCELLED_RUN_ERROR_TEXT),
                final=True,
            ),
        )
    finally:
        store.close_streams(task_id)
    # spec-required: HTTP 200 with the full canceled Task (§5.1)
    return JSONResponse(body, headers=hdrs)


# Handler name reflects JSON-RPC method tasks/resubscribe; REST path is :subscribe per A2A v0.3.0 §2 binding table (see LRN-099).
@router.post("/v1/tasks/{task_id}:subscribe")
async def tasks_resubscribe(
    task_id: str, request: Request, response: Response, identity: Identity = Depends(require_identity)
) -> Any:
    guard_origin(request)
    # RT-B-005: echo BEFORE the not-found return (was after, so that error
    # response never carried it — same gap message_send/tasks_get/tasks_cancel
    # had).
    # RT-002 (debug round 4): narrowed to A2UI only. A resubscribe replays the
    # task's own frames, which genuinely can carry A2UI DataParts, so A2UI stays
    # request-gated here (suppressing it would tell a conformant consumer not to
    # parse A2UI content this stream does deliver). But this route never calls
    # forwarding.bind/parse_header — nothing is ever forwarded on a resubscribe
    # — so echoing the credential-forwarding URI back as "activated" is the same
    # false-activation signal RT-B-203 removed from tasks/get.
    _echo_extensions(request, response, activatable=_STREAM_ONLY_EXTENSION_URIS)
    hdrs = dict(response.headers)
    record = request.app.state.task_store.get(task_id, identity)
    if record is None:
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found", headers=hdrs)
    stream, _ = _open_stream(request, record)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **hdrs},
    )
