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

Both streaming verbs here (``POST /v1/message:stream``, ``POST
/v1/tasks/{id}:subscribe``) hold an indefinite ``text/event-stream`` and are
admitted against a bounded concurrency budget shared with AG-UI's ``POST
/ag-ui/run`` — at capacity they return ``429`` + ``Retry-After: 5`` (error
code ``-32000``) rather than evicting a live stream. Recorded in DESIGN.md
§5.5/§6 and docs/protocols.md; see ``_admit`` for the mechanism and the
ordering rule it enforces.

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
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

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
from ..auth.context import ResumeEnvelope, bind_identity, unbind_identity
from ..auth.middleware import require_identity
from ..credentials import forwarding
from ..common.admission import (
    SlotTable,
    StreamSlot,
    count_for_owner,
    count_for_task,
    identity_key,
    prune_finished,
    resolve_per_identity_limit,
    slot_table,
)
from ..common.origin import guard_origin
from ..common.json_strict import dumps_strict, loads_strict, scrub_unencodable
from ..common import sse as _sse
from ..common.sse import HEARTBEAT, SSE_HEADERS, sse_data
from ..common.wire_errors import a2a_error, a2a_invalid_params, a2a_parse_error
from ..models.a2a import (
    INTERRUPT_STATES,
    TERMINAL_STATES,
    DataPart,
    Message,
    MessageSendParams,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from ..credentials.card import EXTENSION_URI as CREDENTIAL_FORWARDING_EXTENSION_URI
from ..models.content_types import A2UI_EXTENSION_URI, A2UI_MIME_TYPE
from ..models.errors import (
    A2A_CONTENT_TYPE_NOT_SUPPORTED,
    A2A_INVALID_AGENT_RESPONSE,
    A2A_PUSH_NOTIFICATION_NOT_SUPPORTED,
    A2A_TASK_NOT_CANCELABLE,
    A2A_TASK_NOT_FOUND,
    A2A_UNSUPPORTED_OPERATION,
    WireError,
)
from ..tasks.store import StreamTerminated, Subscription, TaskRecord

logger = logging.getLogger(__name__)

router = APIRouter()

_SUPPORTED_MODES = {"text", "text/plain", "application/json", A2UI_MIME_TYPE}
_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB — consistent with AG-UI cap

# RT-002 (GH-143 follow-up): message_stream's taskId-resume branch and
# tasks_resubscribe both hold an authenticated, indefinitely-held
# text/event-stream open on the SAME single-process connection pool GET
# /mcp's admission cap (routes/mcp.py's _get_streams()) already protects —
# capping only that surface left this one trivially reachable, including the
# specific harm _open_stream's own docstring names: tasks_resubscribe can be
# invoked unboundedly against ONE task, each call appending a Subscription
# onto record.subscriptions, an unbounded list store.publish walks for every
# frame. Mirrors routes/mcp.py's _get_streams()/_prune_get_streams() pattern:
# a stream id -> (task id, owning ASGI request task, release) slot,
# registered BEFORE store.subscribe()/the StreamingResponse, admitted
# against a global cap (bounds total process load) then a cap on concurrent
# subscribers to THIS task (bounds the specific per-task growth above) —
# reject via HTTPException(429), never evict, for the identical reason
# mcp.py's comment gives: evicting only the admission slot would not stop
# the live gen() loop or free its connection.
#
# RT-001 (round 2): the global cap alone bounds total process load but has NO
# cross-tenant dimension — one identity can consume the entire budget and
# lock every other tenant out of message:stream/tasks:subscribe. The
# per-task cap is vacuous on message:stream's dominant no-taskId path
# (_create_task_record mints a fresh uuid task id on every call, so
# task_count is always 0 there). Mirrors routes/mcp.py's
# _MAX_GET_STREAMS_PER_IDENTITY / _max_streams_per_identity() exactly,
# including the same org-wide-provisioning caveat: Identity.subject is a
# client_id/api-key id, not an end user, so a shared org credential
# collapses every caller in the org onto ONE identity_key() value. See
# _max_a2a_streams_per_identity().
_MAX_A2A_STREAMS = 500
_MAX_A2A_STREAMS_PER_IDENTITY = 200
_MAX_A2A_STREAMS_PER_TASK = 16

# RT-001 (round 4, fresh-lens): the three caps above were correct but ran in
# the wrong PLACE on message:stream's dominant no-taskId path. `_open_stream`
# conflated two different things — the admission DECISION (a pure capacity
# check) and the subscription REGISTRATION (state mutation) — into one call
# that needs a `TaskRecord`. On the no-taskId path there is no record until
# `_create_task_record()` has already run `task_store.create()`, so the
# load-shed check necessarily ran AFTER a durable write to the
# capacity-bounded store: every 429-rejected request still inserted an
# orphan TaskRecord (no worker, permanently 'submitted'), and `create()` ->
# `_evict_over_capacity()` then evicted oldest-first, and `evict()` cancels
# that record's worker, cancels its resume_future and `sub.close()`s its
# subscribers — so the shed path became an eviction vector that severed
# ANOTHER tenant's in-flight SSE stream with no final:true frame. That
# directly contradicts this wave's own reject-not-evict rationale
# (routes/mcp.py's _MAX_GET_STREAMS comment).
#
# The fix is structural, not a rescue: admission is now `_admit()`, which
# takes an identity and an OPTIONAL task id (never a record), performs the
# capacity decision and CLAIMS its slot in the same synchronous step, and
# mutates nothing durable. Callers that must create state run `_admit()`
# first and hand the resulting `_ClaimedSlot` to `_open_stream()`. Claiming
# at decision time (rather than re-checking later) is what makes this safe:
# there is no await between the checks and the insert, so no interleaved
# request can take the last slot in between and force a second rejection
# after the store has already been written.
#
# RT-002 (round 5): the slot record, the identity key, the lazy-init table
# accessor, the liveness prune loop and the override-and-clamp limit resolver
# all now live in `common/admission.py` (C-024) and are shared with
# routes/mcp.py, which held a byte-identical second copy. What stays here is
# only what is genuinely A2A-specific: the cap constants above, the per-task
# cap, `HTTPException`-shaped rejection (so app.py's `_a2a_auth_envelope` wraps
# it in the A2A error shape), and the deferred task binding below.
#
# RT-001 (round 6, fresh-lens): that deferred binding used to be a bare
# `bind(task_id, sub)` callable the admitting route had to remember to call
# AFTER its own `store.subscribe()`. Only `_open_stream` ever remembered;
# `/ag-ui/run` — the other route documented (DESIGN.md §5.5, docs/protocols.md)
# as sharing this budget's per-task subscriber cap — subscribed directly
# against the store and never bound. An unbound slot keeps the `""` placeholder
# task id, so `count_for_task` could not see AG-UI subscribers at all: the
# documented per-task cap was unenforceable on that route AND under-counted for
# the routes that do bind (an A2A client still got its full
# `_MAX_A2A_STREAMS_PER_TASK` subscribers on top of the AG-UI ones on the same
# `record.subscriptions` — the per-frame `store.publish` walk the cap exists to
# bound). Its `release()` also never unsubscribed, leaving AG-UI's subscription
# teardown on the inner generator's `finally` alone — the exact layer
# `_open_stream`'s docstring documents as insufficient — so the layer-2
# BackgroundTask and layer-3 `prune_finished` backstops reclaimed strictly less
# for AG-UI than for A2A.
#
# The fix removes the forgettable step rather than adding it back at the second
# call site: a slot no longer exposes `bind` at all, it exposes `subscribe`,
# which performs `store.subscribe()` and the slot update as ONE synchronous
# operation. Subscribing under an admitted slot without registering the task id
# is now unrepresentable, so a future third stream route cannot reintroduce
# this class of bug by omission.


@dataclass
class _ClaimedSlot:
    """A claimed admission slot, returned by ``_admit``.

    ``release`` is the slot's single, idempotent teardown callable — it drops
    the slot and unsubscribes whatever ``subscribe`` attached to it (nothing,
    if the caller never got that far).

    ``subscribe(task_id)`` is the ONLY way an admitted stream may attach a
    ``Subscription``: it subscribes against the task store and upgrades this
    slot — reserved with no task id — to the real task in the same synchronous
    step. Deliberately not a separate ``bind`` the caller invokes afterwards
    (RT-001, round 6): that made registration an optional courtesy every stream
    route had to remember, and the route that forgot silently disabled the
    per-task cap for itself and under-counted it for everyone else.
    """

    stream_id: str
    release: Callable[[], Awaitable[None]]
    subscribe: Callable[[str], Subscription]


def _max_a2a_streams_per_identity(app: Any) -> int:
    """Effective per-identity A2A-stream cap (RT-001), via the shared resolver.

    ``AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY`` overrides the SDK default for an
    org larger than it accommodates; the shared helper clamps to
    ``_MAX_A2A_STREAMS`` and documents why a ``0`` can never reach it."""
    return resolve_per_identity_limit(
        app,
        "max_a2a_streams_per_identity",
        _MAX_A2A_STREAMS_PER_IDENTITY,
        _MAX_A2A_STREAMS,
    )


def _a2a_streams(app: Any) -> SlotTable:
    """Shared admission budget for every indefinite A2A text/event-stream —
    both streaming verbs here plus ``/ag-ui/run``."""
    return slot_table(app, "a2a_streams")


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


def _unsupported_input_error(message: Message) -> JSONResponse | None:
    """GH-159: input is text only. Reject (never drop) any non-TextPart and
    any message with no text. Names the part kind only, never content (SI-2)."""
    kinds = sorted({p.kind for p in message.parts if not isinstance(p, TextPart)})
    if kinds:
        return a2a_error(
            A2A_CONTENT_TYPE_NOT_SUPPORTED,
            "unsupported message part kind: " + ", ".join(kinds) + "; only text parts are accepted",
        )
    if not _message_text(message).strip():
        return a2a_invalid_params("message must contain non-empty text")
    return None


def _resume_value(message: Message) -> Any | JSONResponse:
    """GH-193: the value delivered to ``resume_handler``. Text resumes stay a
    plain ``str``; exactly one DataPart (and nothing else) becomes
    ``{"status": None, "payload": data}``. Names part kinds only (SI-2)."""
    data_parts = [p for p in message.parts if isinstance(p, DataPart)]
    if not data_parts:
        return _message_text(message)
    others = sorted({p.kind for p in message.parts if not isinstance(p, (DataPart, TextPart))})
    if others:
        return a2a_error(
            A2A_CONTENT_TYPE_NOT_SUPPORTED,
            "unsupported message part kind: " + ", ".join(others) + "; a resume accepts text or one data part",
        )
    if len(message.parts) != 1:
        return a2a_invalid_params("a data resume must contain exactly one data part and no other parts")
    return {"status": None, "payload": data_parts[0].data}


def _capabilities(message: Message, request: Request) -> A2uiCapabilities:
    # Gate A2UI on the opt-in header — clients that never sent X-A2A-Extensions
    # containing A2UI_EXTENSION_URI must not receive A2UI DataParts. The
    # fail-closed default itself lives in A2uiCapabilities.gated (C-006) so
    # this transport cannot drift from ag_ui.py's independently.
    extensions = request.headers.get("x-a2a-extensions", "")
    opted_in = A2UI_EXTENSION_URI in [u.strip() for u in extensions.split(",")]
    raw = (message.metadata or {}).get("a2uiClientCapabilities")
    # GH-240: A2A-only; AG-UI keeps the default.
    return A2uiCapabilities.gated(opted_in, raw, keep_declared_catalogs=True)


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
        body = loads_strict(raw)
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
    # GH-193: a resume may carry one DataPart (validated in _resume_or_error,
    # after the task-state checks); everything else keeps the text-only check.
    msg = params.message
    is_data_resume = bool(msg.task_id) and any(isinstance(p, DataPart) for p in msg.parts)
    if not is_data_resume and (err := _unsupported_input_error(msg)) is not None:
        return err
    return params


def _start_worker(
    request: Request,
    record: TaskRecord,
    capabilities: A2uiCapabilities,
    identity: Identity,
    user_timezone: str | None = None,
) -> None:
    state = request.app.state
    # Bind any per-call forwarded credentials BEFORE create_task so the worker
    # snapshots them (contextvars copy at task creation). Bound to the original
    # submit — a later resume runs in the worker's context, not the resume
    # request's (acceptable: this surface has no credential-bearing resume).
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
                inject_date=state.inject_current_date,
                timezone_name=state.timezone,
                user_timezone=user_timezone,
            )
        )
    finally:
        unbind_identity(identity_token)


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
    record.messages.append({"role": "user", "content": [{"text": _message_text(msg)}]})
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
    value = _resume_value(msg)
    if isinstance(value, JSONResponse):
        return value
    # GH-185: the already-running worker picks this up after its resume wait,
    # so post-resume tools see the resuming caller (not the original submitter).
    delivered = store.deliver_resume(record.task.id, ResumeEnvelope(value, identity))
    if not delivered:
        # lost the race: interrupt was consumed/expired between check and deliver
        return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
    # LRN-048: never mutate the inbound Message; archive a copy with server-assigned
    # contextId only (role='user' entries do not carry server taskId per A2A §3).
    history_entry = msg.model_copy(update={"context_id": record.task.context_id})
    record.task.history = (record.task.history or []) + [history_entry]
    return record


def _strict_json_response(
    content: Any, headers: dict[str, str] | None = None
) -> Response:
    """GH-179: the one place a non-stream A2A body is serialized. Starlette's
    ``dumps_strict`` refuses non-finite values explicitly; answer with a fixed
    -32006 instead of a bare HTTP 500 (SI-2: no value is echoed)."""
    try:
        body = dumps_strict(content)
    except ValueError:
        # w050 RT-001 (round 6): a record stored before the status-commit
        # scrub (or by a durable store) may still hold a lone surrogate.
        # Replace it with U+FFFD rather than fail every read of the task.
        try:
            body = dumps_strict(scrub_unencodable(content))
        except ValueError:
            logger.error("a2a response body not serializable")
            return a2a_error(
                A2A_INVALID_AGENT_RESPONSE, "invalid agent response", headers=headers
            )
        logger.warning("a2a response body held unencodable text; replaced")
    return Response(content=body, media_type="application/json", headers=headers)


def _list_entry(task: Task) -> dict[str, Any] | None:
    """One tasks/list entry, serialized on its own (w050 RT-001 round 6) so
    a single unwritable record cannot fail the whole page for the identity.
    Unencodable text is replaced with U+FFFD; a record that still cannot be
    written (a non-finite value that bypassed validation) is left out and
    logged by id only (SI-2)."""
    wire = task.model_dump(by_alias=True, mode="json", exclude_none=True)
    try:
        dumps_strict(wire)
        return wire
    except ValueError:
        pass
    wire = scrub_unencodable(wire)
    try:
        dumps_strict(wire)
        return wire
    except ValueError:
        logger.error("tasks/list: task %s not serializable; left out", task.id)
        return None


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
    blocking = bool(params.configuration and params.configuration.blocking)
    if params.message.task_id:
        slot: _ClaimedSlot | None = None
        sub: Subscription | None = None
        if blocking:
            # GH-189: subscribe BEFORE delivering the resume so no frame is missed.
            existing = request.app.state.task_store.get(params.message.task_id, identity)
            if existing is not None:
                slot = await _admit(request, identity, existing.task.id)
                sub = slot.subscribe(existing.task.id)
        try:
            record = _resume_or_error(request, params, identity)
            if isinstance(record, JSONResponse):
                return record
            if sub is not None:
                await _wait_blocking(request, sub)
        finally:
            if slot is not None:
                await slot.release()
        # RT-005: a resume never calls _capabilities()/forwarding.bind, so
        # only A2UI can ever be echoed here, and only when the resumed
        # Task's OWN artifacts genuinely carry an A2UI part.
        _echo_a2ui_if_present([record.task], request, response)
        return _strict_json_response(_task_wire(record), dict(response.headers))
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
            return _strict_json_response(bare_msg.wire())
    slot = await _admit(request, identity, None) if blocking else None
    try:
        record = _create_task_record(request, params, identity)
        sub = slot.subscribe(record.task.id) if slot is not None else None
        _start_worker(
            request, record, _capabilities(params.message, request), identity,
            (params.message.metadata or {}).get("timezone"),
        )
        # RT-005: the sole path on this route that can activate either
        # extension — echoed only now that _capabilities()/_start_worker have
        # actually run.
        _echo_extensions(request, response)
        if sub is not None:
            await _wait_blocking(request, sub)
    finally:
        if slot is not None:
            await slot.release()
    history_length = (
        params.configuration.history_length if params.configuration else None
    )
    return _strict_json_response(_task_wire(record, history_length), dict(response.headers))


async def _wait_blocking(request: Request, sub: Subscription) -> None:
    """GH-189: A2A v0.3.0 ``blocking: true`` — wait until the task is
    terminal or interrupted (the runner publishes ``final`` for both), capped
    at ``min(task deadline, blocking_send_max_seconds)``. The worker keeps
    running past the cap. The caller owns subscription teardown."""
    settings = request.app.state.settings
    cap = min(float(settings.task_deadline_seconds), float(settings.blocking_send_max_seconds))

    async def drain() -> None:
        while True:
            try:
                item = await sub.get()
            except StreamTerminated:
                return
            if item is None or item.final:
                return

    try:
        await asyncio.wait_for(drain(), timeout=cap)
    except asyncio.TimeoutError:
        pass


async def _admit(
    request: Request, identity: Identity, task_id: str | None
) -> _ClaimedSlot:
    """Reserve one admission slot for an indefinite A2A ``text/event-stream``.

    RT-002: the shared ``_a2a_streams()`` budget — global cap first (bounds
    total process load), then per-identity (RT-001: stops one authenticated
    tenant consuming the whole budget and locking out every other tenant),
    then per-task when ``task_id`` is known (bounds the unbounded
    ``record.subscriptions`` growth ``tasks_resubscribe`` could otherwise
    drive, since ``store.publish`` walks that list for every frame). Rejects
    with ``HTTPException(429)`` and never evicts, for the identical reason
    ``routes/mcp.py``'s ``_MAX_GET_STREAMS`` comment gives: evicting a slot
    would not stop the live generator or free its connection.

    RT-001 (round 4): this function is the ENTIRE admission decision and it
    deliberately takes no ``TaskRecord`` — only an identity and an optional
    task id — so it can be called before the task exists, i.e. before ANY
    durable state mutation on the request path. It mutates nothing but the
    in-memory admission map, so a rejection here is a pure no-op: no task
    record is written, and therefore nothing can be evicted from the
    capacity-bounded task store as a side effect of shedding load.

    The slot is CLAIMED here, not merely checked: the three checks and the
    ``streams[stream_id] = ...`` insert are separated by no await, so the
    decision is atomic with respect to the event loop. A caller may therefore
    create state after ``_admit`` returns and pass the slot to
    ``_open_stream`` knowing no interleaved request can have taken the last
    slot in the meantime.

    ``HTTPException(429)`` rides the app-level A2A error envelope
    (``app.py``'s ``_a2a_auth_envelope``), the same path ``guard_origin``'s
    403 and the identity rate limiter's 429 already use, so the ``/v1/*``
    caller sees the spec error shape with ``Retry-After`` preserved. On
    ``/ag-ui/run``, which has no such handler, it surfaces as the bare
    ``{"detail": ...}`` shape that surface's other transport-level
    rejections already use.
    """
    streams = _a2a_streams(request.app)
    await prune_finished(streams)
    if len(streams) >= _MAX_A2A_STREAMS:
        raise HTTPException(
            status_code=429,
            detail="too many concurrent A2A streams",
            headers={"Retry-After": "5"},
        )
    owner = identity_key(identity)
    if count_for_owner(streams, owner) >= _max_a2a_streams_per_identity(request.app):
        raise HTTPException(
            status_code=429,
            detail="too many concurrent A2A streams for this identity",
            headers={"Retry-After": "5"},
        )
    if task_id is not None:
        if count_for_task(streams, task_id) >= _MAX_A2A_STREAMS_PER_TASK:
            raise HTTPException(
                status_code=429,
                detail="too many concurrent subscribers for this task",
                headers={"Retry-After": "5"},
            )

    store = request.app.state.task_store
    stream_id = uuid.uuid4().hex
    # RT-001: the ASGI request task itself is the liveness fact
    # prune_finished keys on — it stays not-done for the entire response
    # cycle, StreamingResponse body and background task included, so a
    # still-open stream is never mistaken for a stale one.
    owning_task = asyncio.current_task()
    assert owning_task is not None
    bound: tuple[str, Subscription] | None = None

    async def release() -> None:
        # RT-001: MUST be `async def` — Starlette's BackgroundTask dispatches
        # a plain `def` via run_in_threadpool (an AnyIO worker thread), which
        # would mutate `streams`/`record.subscriptions` (event-loop-owned
        # state `prune_finished`/`InMemoryTaskStore.publish` concurrently
        # iterate) off-loop — racing that iteration and able to skip a live
        # subscriber rather than merely raising. `async def` makes Starlette
        # await it in-loop instead, and every caller (the BackgroundTask and
        # the early-return paths) must `await` it rather than call it bare.
        # Idempotent, so the generator `finally` / BackgroundTask / prune
        # layers overlap harmlessly.
        streams.pop(stream_id, None)
        if bound is not None:
            store.unsubscribe(bound[0], bound[1])

    def subscribe(bound_task_id: str) -> Subscription:
        """Subscribe to ``bound_task_id`` THROUGH this slot.

        Attaches the real task id + ``Subscription`` to the slot, so `release`
        becomes the subscription's lifecycle teardown too and the per-task cap
        can see the slot. Synchronous by design, and it owns the
        ``store.subscribe()`` call itself: there is no point between the
        subscription existing and the slot knowing about it at which the loop
        can be yielded to, and no way for a caller to perform one half without
        the other (RT-001, round 6 — that was exactly how ``/ag-ui/run``
        escaped the per-task cap while still consuming the budget)."""
        nonlocal bound
        sub = store.subscribe(bound_task_id)
        bound = (bound_task_id, sub)
        slot = streams.get(stream_id)
        if slot is not None:
            slot.task_id = bound_task_id
        return sub

    streams[stream_id] = StreamSlot(
        owner=owner,
        owning_task=owning_task,
        release=release,
        task_id=task_id or "",
    )
    return _ClaimedSlot(stream_id=stream_id, release=release, subscribe=subscribe)


async def _open_stream(
    request: Request,
    record: TaskRecord,
    identity: Identity,
    slot: _ClaimedSlot | None = None,
) -> tuple[AsyncIterator[bytes], Any]:
    """Subscribe + snapshot the full-Task first frame EAGERLY (before the
    worker can mutate the record or publish), then return the SSE generator
    plus an abort callback for paths that never iterate it. A
    severed-without-final stream is the documented re-subscribe signal
    (§5.2).

    Admission is ``_admit``'s job, never this function's (see its docstring
    and the module comment above ``_MAX_A2A_STREAMS``). Callers that hold no
    state yet may let this call ``_admit`` for them by omitting ``slot``;
    callers that must create durable state first MUST call ``_admit``
    themselves BEFORE that mutation and pass the resulting ``_ClaimedSlot``
    here, so a 429 can never be raised on a request path that has already
    written to the capacity-bounded task store (RT-001, round 4).

    RT-001 (round 4): ``abort`` is not only for the early-return paths — it
    is the slot's and the subscription's lifecycle release, and EVERY caller
    must also hand it to the ``StreamingResponse`` as a ``BackgroundTask``.
    ``gen()``'s ``finally`` is not a lifecycle hook: it runs only once the
    generator body has actually started, so a request task cancelled at
    Starlette's ``send(http.response.start)`` checkpoint would never
    unsubscribe, leaking a ``Subscription`` onto ``record.subscriptions`` —
    an unbounded list that ``store.publish`` walks for every frame.
    ``store.unsubscribe`` is idempotent, so the two layers overlap
    harmlessly."""
    if slot is None:
        slot = await _admit(request, identity, record.task.id)

    # Subscribing THROUGH the slot is what makes the slot own the
    # subscription's teardown from the instant it exists, and what lets the
    # per-task cap see the real task id before any other request can be
    # served. There is no store.subscribe() call here to get out of step with
    # it (RT-001, round 6).
    sub = slot.subscribe(record.task.id)
    release = slot.release
    snapshot = record.task.wire()
    terminal = record.task.status.state in TERMINAL_STATES

    def _unserializable_tail() -> bytes:
        # GH-173: sse_data refuses non-finite floats (allow_nan=False). Ingress
        # rejects them (loads_strict), but a frame can still carry one from a
        # path that bypassed validation. Never let that ValueError kill the
        # stream mid-body without final:true (§5.2): close it with a fixed,
        # value-free failed status-update instead (SI-2).
        logger.error(
            "a2a stream frame not serializable task_id=%s", record.task.id
        )
        return sse_data(
            TaskStatusUpdateEvent(
                taskId=record.task.id,
                contextId=record.task.context_id,
                status=TaskStatus(
                    state=TaskState.FAILED,
                    error=WireError(
                        code=A2A_INVALID_AGENT_RESPONSE,
                        message="invalid agent response",
                    ),
                ),
                final=True,
            ).wire()
        )

    async def gen() -> AsyncIterator[bytes]:
        try:
            try:
                yield sse_data(snapshot)
            except ValueError:
                yield _unserializable_tail()
                return
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
                    item = await asyncio.wait_for(
                        sub.get(), timeout=_sse.STREAM_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield HEARTBEAT
                    continue
                except StreamTerminated:
                    return
                if item is None:
                    return
                if item.frame is not None:
                    try:
                        chunk = sse_data(item.frame)
                    except ValueError:
                        yield _unserializable_tail()
                        return
                    yield chunk
                if item.final:
                    return
        finally:
            await release()

    async def abort() -> None:
        await release()

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
        if record is None:
            return a2a_error(A2A_TASK_NOT_FOUND, "task not found")
        if record.task.status.state in TERMINAL_STATES:
            # A2A-F1 (matches _resume_or_error's message/send behavior): the task
            # exists but is terminal, so -32001 (TaskNotFound) would misrepresent
            # the failure. Return -32004 directly, never opening a stream
            # subscription for a task that cannot be resumed.
            return a2a_error(
                A2A_UNSUPPORTED_OPERATION, "task is in a terminal state and cannot accept new messages"
            )
        stream, abort = await _open_stream(request, record, identity)
        resumed = _resume_or_error(request, params, identity)
        if isinstance(resumed, JSONResponse):
            await abort()
            return resumed
        # RT-005: a resume never calls _capabilities()/forwarding.bind, so
        # only A2UI can ever be echoed here, and only when the task's OWN
        # (already-existing) artifacts genuinely carry an A2UI part.
        _echo_a2ui_if_present([record.task], request, response)
    else:
        # RT-001 (round 4): admit BEFORE _create_task_record, never after.
        # _create_task_record() -> task_store.create() is a durable write to
        # an LRU-bounded store whose overflow eviction cancels the evicted
        # record's worker and sub.close()s its subscribers — so shedding load
        # after it would sever another tenant's in-flight stream with no
        # final:true frame. The task id does not exist yet, hence None: the
        # per-task cap is vacuous on this path anyway (a fresh uuid per call
        # always counts 0), while the global and per-identity caps — the two
        # that actually bound process load and cross-tenant fairness — are
        # fully enforced here. The slot is claimed, not merely checked, so
        # passing it to _open_stream below cannot 429 a second time.
        slot = await _admit(request, identity, None)
        record = _create_task_record(request, params, identity)
        stream, abort = await _open_stream(request, record, identity, slot=slot)
        _start_worker(
            request, record, _capabilities(params.message, request), identity,
            (params.message.metadata or {}).get("timezone"),
        )
        # RT-005: the sole path on this route that can activate either
        # extension — echoed only now that _capabilities()/_start_worker
        # have actually run.
        _echo_extensions(request, response)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **dict(response.headers)},
        background=BackgroundTask(abort),
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
        "tasks": [e for e in (_list_entry(t) for t in tasks) if e is not None],
        "totalSize": total,
        "pageSize": size,
        "nextPageToken": next_token or "",
    }
    return _strict_json_response(body, dict(response.headers))


def _push_config_not_supported(request: Request, response: Response) -> JSONResponse:
    # GH-190: identical reply for known, foreign and unknown tasks; the task id
    # is never looked up and the request body is never read.
    guard_origin(request)
    return a2a_error(
        A2A_PUSH_NOTIFICATION_NOT_SUPPORTED,
        "push notifications are not supported",
        headers=dict(response.headers),
    )


@router.post("/v1/tasks/{task_id}/pushNotificationConfigs")
@router.get("/v1/tasks/{task_id}/pushNotificationConfigs")
async def push_configs_unsupported(
    task_id: str,
    request: Request,
    response: Response,
    identity: Identity = Depends(require_identity),
) -> Any:
    return _push_config_not_supported(request, response)


@router.get("/v1/tasks/{task_id}/pushNotificationConfigs/{config_id}")
@router.delete("/v1/tasks/{task_id}/pushNotificationConfigs/{config_id}")
async def push_config_unsupported(
    task_id: str,
    config_id: str,
    request: Request,
    response: Response,
    identity: Identity = Depends(require_identity),
) -> Any:
    return _push_config_not_supported(request, response)


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
    return _strict_json_response(_task_wire(record, historyLength), dict(response.headers))


def cancel_task_record(record: TaskRecord, store: Any) -> None:
    """Shared teardown for an already identity-scoped, non-terminal record.

    Used by ``tasks/cancel`` and by the AG-UI route when its SSE stream ends
    before a terminal frame. Takes a record, never a task id: callers resolve
    the record under the request identity first (SI-5).
    """
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
            record.task.id,
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
            record.task.id,
            StreamItem(
                frame=frame,
                event=DoneEvent(ok=False, error=_CANCELLED_RUN_ERROR_TEXT),
                final=True,
            ),
        )
    finally:
        store.close_streams(record.task.id)


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
    cancel_task_record(record, store)
    body = _task_wire(record)
    # spec-required: HTTP 200 with the full canceled Task (§5.1)
    return _strict_json_response(body, hdrs)


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
    identity_token = bind_identity(identity)
    try:
        stream, abort = await _open_stream(request, record, identity)
    finally:
        unbind_identity(identity_token)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **hdrs},
        background=BackgroundTask(abort),
    )
