"""A2A v0.3.0 HTTP+JSON routes (DESIGN.md §5.1).

Success bodies are the bare result object (Task | Message); errors are the
spec ``{"error": {code, message, data?}}`` shape with the §5.1 HTTP status
mapping. All endpoints require an authenticated identity; task access is
identity-bound (mismatch → 404 + -32001, existence never leaked).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from ..a2ui.translator import A2uiCapabilities
from ..agent.runner import StreamItem, new_task, run_task_worker
from ..auth.identity import Identity
from ..auth.middleware import require_identity
from ..credentials import forwarding
from ..common.sse import SSE_HEADERS, sse_data
from ..common.wire_errors import a2a_error, a2a_invalid_params
from ..models.a2a import (
    INTERRUPT_STATES,
    TERMINAL_STATES,
    Message,
    MessageSendParams,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from ..models.content_types import A2UI_EXTENSION_URI, A2UI_MIME_TYPE
from ..models.errors import (
    A2A_CONTENT_TYPE_NOT_SUPPORTED,
    A2A_PUSH_NOTIFICATION_NOT_SUPPORTED,
    A2A_TASK_NOT_CANCELABLE,
    A2A_TASK_NOT_FOUND,
    A2A_UNSUPPORTED_OPERATION,
)
from ..tasks.store import StreamTerminated, TaskRecord

router = APIRouter()

_SUPPORTED_MODES = {"text", "text/plain", "application/json", A2UI_MIME_TYPE}


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _echo_extensions(request: Request, response: Response) -> None:
    """X-A2A-Extensions: response echoes the activated subset (§5.1)."""
    requested = request.headers.get("x-a2a-extensions", "")
    activated = [
        uri.strip() for uri in requested.split(",") if uri.strip() == A2UI_EXTENSION_URI
    ]
    if activated:
        response.headers["X-A2A-Extensions"] = ", ".join(activated)


def _message_text(message: Message) -> str:
    return "\n".join(p.text for p in message.parts if getattr(p, "kind", "") == "text")


def _capabilities(message: Message) -> A2uiCapabilities:
    raw = (message.metadata or {}).get("a2uiClientCapabilities")
    return A2uiCapabilities.from_metadata(raw)


def _config_error(params: MessageSendParams) -> JSONResponse | None:
    config = params.configuration
    if config is None:
        return None
    if config.push_notification_config is not None:
        return a2a_error(
            A2A_PUSH_NOTIFICATION_NOT_SUPPORTED, "push notifications are not supported"
        )
    if config.blocking:
        return a2a_error(
            A2A_UNSUPPORTED_OPERATION, "blocking send is not supported; poll tasks/{id}"
        )
    if config.accepted_output_modes is not None and config.accepted_output_modes:
        if not _SUPPORTED_MODES.intersection(config.accepted_output_modes):
            return a2a_error(
                A2A_CONTENT_TYPE_NOT_SUPPORTED,
                "no acceptable output mode; supported: " + ", ".join(sorted(_SUPPORTED_MODES)),
            )
    return None


async def _parse_send(request: Request) -> MessageSendParams | JSONResponse:
    try:
        body = await request.json()
    except json.JSONDecodeError:
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
    msg.task_id = task.id
    msg.context_id = task.context_id
    task.history = [msg]
    record = request.app.state.task_store.create(task, identity)
    record.messages.append({"role": "user", "content": [{"text": _message_text(msg) or " "}]})
    return record


def _resume_or_error(
    request: Request, params: MessageSendParams, identity: Identity
) -> TaskRecord | JSONResponse:
    msg = params.message
    store = request.app.state.task_store
    record = store.get(msg.task_id, identity)
    if record is None:
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    state = record.task.status.state
    if state in TERMINAL_STATES:
        # terminal: no resumable interrupt remains — the resumable task is gone
        # (-32002 TaskNotCancelable is cancel-specific and wrong here).
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    if state not in INTERRUPT_STATES:
        # working task not awaiting input: continuing it is not a supported op
        return a2a_error(A2A_UNSUPPORTED_OPERATION, "task is not awaiting input")
    # reject a contextId that contradicts the task BEFORE we mutate anything
    if msg.context_id and msg.context_id != record.task.context_id:
        return a2a_invalid_params("contextId does not match the task")
    msg.context_id = record.task.context_id
    delivered = store.deliver_resume(record.task.id, _message_text(msg))
    if not delivered:
        # lost the race: interrupt was consumed/expired between check and deliver
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    # record the resume message only once it is actually accepted (race fix)
    record.task.history = (record.task.history or []) + [msg]
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
    _echo_extensions(request, response)
    params = await _parse_send(request)
    if isinstance(params, JSONResponse):
        return params
    if (err := _config_error(params)) is not None:
        return err
    if params.message.task_id:
        record = _resume_or_error(request, params, identity)
        if isinstance(record, JSONResponse):
            return record
        return JSONResponse(_task_wire(record), headers=dict(response.headers))
    record = _create_task_record(request, params, identity)
    _start_worker(request, record, _capabilities(params.message))
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
                        task_id=record.task.id,
                        context_id=record.task.context_id,
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
    _echo_extensions(request, response)
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
    else:
        record = _create_task_record(request, params, identity)
        stream, _ = _open_stream(request, record)
        _start_worker(request, record, _capabilities(params.message))
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **dict(response.headers)},
    )


@router.get("/v1/tasks")
async def tasks_list(identity: Identity = Depends(require_identity)) -> Any:
    return a2a_error(A2A_UNSUPPORTED_OPERATION, "tasks/list is not supported")


@router.get("/v1/tasks/{task_id}")
async def tasks_get(
    task_id: str,
    request: Request,
    historyLength: int | None = None,
    identity: Identity = Depends(require_identity),
) -> Any:
    record = request.app.state.task_store.get(task_id, identity)
    if record is None:
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    return JSONResponse(_task_wire(record, historyLength))


@router.post("/v1/tasks/{task_id}:cancel")
async def tasks_cancel(
    task_id: str, request: Request, identity: Identity = Depends(require_identity)
) -> Any:
    store = request.app.state.task_store
    record = store.get(task_id, identity)
    if record is None:
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    if record.task.status.state in TERMINAL_STATES:
        return a2a_error(A2A_TASK_NOT_CANCELABLE, "task is already terminal")
    if record.worker is not None and not record.worker.done():
        record.worker.cancel()
    if record.resume_future is not None and not record.resume_future.done():
        record.resume_future.cancel()
        record.resume_future = None
    record.interrupted = False
    record.task.status = TaskStatus(state=TaskState.CANCELED, timestamp=_now_iso())
    frame = TaskStatusUpdateEvent(
        task_id=record.task.id,
        context_id=record.task.context_id,
        status=record.task.status,
        final=True,
    ).wire()
    store.publish(task_id, StreamItem(frame=frame, event=None, final=True))
    store.close_streams(task_id)
    # spec-required: HTTP 200 with the full canceled Task (§5.1)
    return JSONResponse(_task_wire(record))


@router.post("/v1/tasks/{task_id}:subscribe")
async def tasks_subscribe(
    task_id: str, request: Request, response: Response, identity: Identity = Depends(require_identity)
) -> Any:
    record = request.app.state.task_store.get(task_id, identity)
    if record is None:
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    _echo_extensions(request, response)
    stream, _ = _open_stream(request, record)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **dict(response.headers)},
    )
