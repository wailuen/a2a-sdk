"""MCP 2025-06-18 Streamable HTTP routes (DESIGN.md §5.5, §5.6).

Three verbs at ``/mcp``:

- ``POST /mcp`` — JSON-RPC 2.0. Session id allocated on ``initialize`` and
  returned via ``Mcp-Session-Id``; a non-initialize POST bearing an
  unknown/expired session id → 404 (initialize itself is the recovery path).
- ``GET /mcp`` — server→client SSE channel, held open with heartbeats.
  Returning 405 here breaks Claude.ai Desktop (pitchbook LRN-053) — never.
  Two outcomes per spec, three here: see the stream-admission deviation
  below.
- ``DELETE /mcp`` — session termination, idempotent, 204.

Legacy SSE pair (``GET /mcp/sse`` + ``POST /mcp/messages?session_id=``)
retained for older clients; same dispatch path. ``GET /mcp`` and
``GET /mcp/sse`` both hold an indefinite ``text/event-stream`` open and are
admitted against the SAME global + per-identity cap (RT-001/GH-143 —
``_get_streams()``), rejecting once at capacity rather than evicting, since
they consume the same single-process connection pool.

**Stream-admission deviation (RT-003, documented — DESIGN.md §5.5 and
docs/protocols.md carry the same ruling; the A2A/AG-UI half of the shared
rule lives in routes/a2a.py's ``_admit``).** ``harness/reference/
mcp-protocol.md`` §"GET (optional SSE)" specifies exactly TWO outcomes for
this verb — ``text/event-stream``, or **405** if no stream is offered. At
capacity we return a THIRD: ``429`` + ``Retry-After: 5``. Deliberate: the
server is single-process/single-worker by design (config.py,
template/Dockerfile ``--workers 1``), so an unbounded number of open
streams degrades the whole process for every tenant, and the spec offers no
in-band way to say "offered, but not right now". Scoped strictly to
load-shedding — never returned on a first connection under normal load.
``harness/reference/mcp-claude-platforms.md`` records a 429 on this path as
a known Claude.ai *"Couldn't connect"* failure mode (its P8 checklist), and
mcp_get is connection-critical per the LRN-053 note above, which is why the
per-identity default is sized in the low hundreds (an org-wide OAuth client
collapses an entire org onto one ``_identity_key()``) and is operator-
raisable via ``AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`` without a code
change. See ``_MAX_GET_STREAMS`` for the reject-over-evict rationale.

Methods: ``initialize`` (echo the client's protocolVersion when supported,
else our highest), ``ping``, ``tools/list`` (Tier 1 only — surface parity rule
§5.6; ``outputSchema`` only when the tool declares ``emits``), ``tools/call``
(text block always + ``structuredContent`` only under a declared output
schema; tool failures are ``isError: true`` results, NEVER JSON-RPC errors).
A Tier-1 tool that returns/yields no terminal value (``None``) is NOT a
failure — regardless of whether it declares ``emits``, it folds to
``isError: false`` with an empty text block and no ``structuredContent``,
matching agent/loop.py's ``fold_result_content(None)`` fold on the A2A/AG-UI
surfaces exactly (§5.6 parity rule extends to result verdicts, not just tool
visibility) (RT-001/RT-002).
``notifications/*`` → 202 empty, never answered. Per spec §10 the client
MUST send ``MCP-Protocol-Version`` on every non-``initialize`` request, and
the server MUST 400 a present-but-unrecognized version — both hold on every
path below. Only the ABSENT-header case is a spec SHOULD (assume
2025-03-26 for pre-header clients), and handling of that case is where the
paths diverge: Streamable HTTP (``POST /mcp``) is stricter than the SHOULD
and 400s on absent too, present-but-unrecognized → 400 (§10 MUST);
``GET``/``DELETE /mcp`` — absent → allowed (no negotiation context to
validate against), present-but-unrecognized → 400 (GH-111, mirrors the POST
check); Legacy SSE (``POST /mcp/messages``) — absent → allowed, assume
2025-03-26 per the §10 SHOULD-assume carve-out for pre-header clients — but
that "assume" is a rationale only: ``_dispatch()`` is version-agnostic, so no
version value is threaded or materialized (admission ≡ treat-as-pre-header),
present-but-unrecognized → 400 (§10 MUST).

Auth: ``Depends(require_identity)`` — api_key and oauth kinds both accepted;
401s carry the PRM-pointing ``WWW-Authenticate`` via auth/middleware. OAuth
audience enforcement lives inside ``OAuthTokenStore.verify`` (two-value set,
hard reject), so the resolved identity here is already audience-checked.

POST responses use JSON mode (``application/json``) — permitted by the
Streamable HTTP spec for single responses even when the client's Accept
prefers ``text/event-stream``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from collections import OrderedDict
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ..auth.identity import Identity
from ..auth.middleware import require_identity
from ..common.admission import (
    SlotTable,
    StreamSlot,
    count_for_owner,
    identity_key,
    prune_finished,
    resolve_per_identity_limit,
    slot_table,
)
from ..common.json_strict import dumps_strict, loads_strict
from ..common.origin import guard_origin
from ..common.redact import frame_locations
from ..common.sse import HEARTBEAT, SSE_HEADERS
from ..agent.loop import ToolInterrupt, resolve_tool_timeout, safe_validation_message
from ..agent.registry import ToolInputValidationError
from ..credentials import forwarding
from ..models.content_types import ContentModel, MarketBriefing
from ..models.errors import AgentError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# Newest first; initialize echoes the client's version when it appears here.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
# RTGA-004: guard the ordering invariant — the index comparison for
# _TITLE_MIN_VERSION gating only works when the tuple is newest-first.
assert SUPPORTED_PROTOCOL_VERSIONS == tuple(
    sorted(SUPPORTED_PROTOCOL_VERSIONS, reverse=True)
), "SUPPORTED_PROTOCOL_VERSIONS must be newest-first (newest at index 0)"

# Spec introduced serverInfo.title in 2025-06-18 (mcp-protocol.md §2), but
# GH-43 observed Claude.ai rejecting the handshake when title was present
# under a 2025-06-18-negotiated session. We conservatively gate at 2025-11-25
# until that can be re-tested live. Omitting an optional field is spec-valid.
# REVIEWS.md Round 4 documents this as a deferred spec-annotation finding.
_TITLE_MIN_VERSION = "2025-11-25"
_PROTOCOL_VERSION_HEADER = "MCP-Protocol-Version"
# Sentinel returned by _negotiated_version when the MCP-Protocol-Version header
# is absent.  Distinct from None (unrecognized version) so call sites can
# enforce MCP spec §10 — absent header on a non-initialize request → 400.
_HEADER_ABSENT = object()
_SESSION_ID_HEADER = "Mcp-Session-Id"

SESSION_TTL_SECONDS = 30 * 60  # idle TTL
_MAX_SESSIONS = 1_000
_MAX_BODY_BYTES = 2 * 1024 * 1024
_HEARTBEAT_SECONDS = 15.0
# GH-143 (+ RT-001 follow-up): bound concurrent open indefinite
# text/event-stream connections — global first, then per-identity — before a
# StreamingResponse (and its indefinite heartbeat loop) is ever created. The
# server is single-process/single-worker by design (config.py,
# template/Dockerfile --workers 1), so an unbounded number of open streams
# degrades the whole process for every tenant.
#
# This budget is shared by BOTH transports that hold such a stream open —
# Streamable HTTP's GET /mcp (mcp_get) and the legacy GET /mcp/sse (mcp_sse)
# — via the same _get_streams()/_prune_get_streams() tracking structure.
# They consume the same single-process connection pool, so a cap on only one
# of them is trivially bypassed by calling the other.
#
# Strategy: 429-reject, NOT evict-oldest, on both routes. Evicting a stream's
# bookkeeping entry would not stop its live loop or free its connection: the
# generator keeps running, untracked, until the client itself goes away —
# and for mcp_sse specifically, evict-oldest also let one caller silently
# make another tenant's still-open session unroutable (POST /mcp/messages
# -> 404 "session not found") purely by opening enough streams of their own,
# regardless of who owned the evicted entry. Only refusing new streams once
# at capacity keeps the number of live streams actually bounded, for every
# tenant.
_MAX_GET_STREAMS = 500
# RT-001 (round 2, GH-143 follow-up): Identity.subject is an OAuth client_id
# (auth/oauth_tokens.py) or API-key id (auth/api_keys.py) — a *registration*,
# never an end user. Org-wide OAuth client provisioning
# (`python -m agent_sdk provision-org-oauth-client`, config.py) and a shared
# API key both deliberately collapse every caller in the org onto ONE
# _identity_key() value, so a per-identity cap here is really a per-ORG cap
# under that (documented, supported) deployment mode. 8 was sized for "one
# caller can't consume every other tenant's share" without accounting for
# that collapse — it silently capped an entire org at 8 concurrent
# connectors. Default raised to the low hundreds; operators with a larger
# org can raise it further via AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY
# (config.py) without a code change. See _max_streams_per_identity().
_MAX_GET_STREAMS_PER_IDENTITY = 200
# RT-001: a slot is registered in _get_streams() before the StreamingResponse
# is ever constructed, so nothing guarantees the generator body — and thus
# heartbeats()'s `finally` — ever runs (Starlette's spec_version<2.4 path can
# cancel stream_response() at the send(http.response.start) checkpoint before
# the async-for pulls the first chunk). A wall-clock TTL backstop is NOT safe
# here: a live stream whose send() is backpressured, or whose heartbeat sleep
# overshoots under event-loop congestion (exactly the load this cap exists to
# bound), would age out and be reclaimed while still open, defeating the cap.
# _prune_get_streams therefore reclaims a slot only on a liveness fact — the
# owning ASGI request task has actually finished (task.done()) — never on
# elapsed time.
#
# RT-001 (round 4): _MAX_SSE_SESSIONS — the old hard bound on _sse_queues() —
# is deliberately NOT reinstated, because the slot record now carries its own
# release callable and _prune_get_streams invokes it (see _get_streams()).
# mcp_sse registers its _get_streams() slot and its _sse_queues() record
# together and releases them together, on every one of the three layers, so
#     set(_sse_queues()) ⊆ set(_get_streams())
# is an invariant and _sse_queues() is bounded by _MAX_GET_STREAMS by
# construction. A second, independent bound would be dead code that hides a
# broken invariant rather than enforcing one.

# JSON-RPC 2.0 standard error codes.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Session stores (per-app, in-memory — single-process invariant, DESIGN §2)
# ---------------------------------------------------------------------------


# RT-002 (round 5): `_identity_key` is now `common.admission.identity_key`
# (C-024), shared with routes/a2a.py which held a byte-identical copy. Aliased
# rather than renamed at ~8 call sites, several of which key `_sse_queues()`
# session ownership rather than stream admission.
_identity_key = identity_key


def _max_streams_per_identity(app: Any) -> int:
    """Effective per-identity GET-stream cap (RT-001, GH-143 follow-up), via
    the shared resolver (C-024).

    ``AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`` overrides the SDK default for an
    org larger than it accommodates; the shared helper clamps to
    ``_MAX_GET_STREAMS`` and documents why a ``0`` can never reach it."""
    return resolve_per_identity_limit(
        app,
        "max_mcp_streams_per_identity",
        _MAX_GET_STREAMS_PER_IDENTITY,
        _MAX_GET_STREAMS,
    )


def _sessions(app: Any) -> "OrderedDict[str, tuple[float, str]]":
    """Streamable HTTP sessions: id → (last-seen, owner identity key).
    Bounded LRU + idle TTL. The owner binding makes a stolen/guessed session
    id useless to any other caller (cross-identity session hijack defense)."""
    sessions = getattr(app.state, "mcp_sessions", None)
    if sessions is None:
        sessions = OrderedDict()
        app.state.mcp_sessions = sessions
    return sessions


def _prune_sessions(sessions: "OrderedDict[str, tuple[float, str]]") -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    for sid in [s for s, rec in sessions.items() if rec[0] <= cutoff]:
        sessions.pop(sid, None)
    while len(sessions) > _MAX_SESSIONS:
        sessions.popitem(last=False)


def _session_alive(
    sessions: "OrderedDict[str, tuple[float, str]]", session_id: str, owner: str
) -> bool:
    """Presence + idle-TTL + ownership check; touches last-seen (LRU) when
    alive AND owned. A mismatched owner is treated as not-found (no existence
    oracle; the client's recovery path is identical — re-initialize). Never
    evict on owner mismatch, only on TTL expiry, so one caller can't delete
    another's live session."""
    rec = sessions.get(session_id)
    if rec is None:
        return False
    last_seen, sess_owner = rec
    if last_seen <= time.time() - SESSION_TTL_SECONDS:
        sessions.pop(session_id, None)
        return False
    if sess_owner != owner:
        return False
    sessions[session_id] = (time.time(), owner)
    sessions.move_to_end(session_id)
    return True


# RT-002 (round 5): the slot record is `common.admission.StreamSlot` (C-024),
# shared with routes/a2a.py. Its `release` field is the slot's COMPLETE
# teardown — every structure the admitting route registered under this key, not
# just this dict — which is what lets the layer-3 backstop reclaim the whole
# surface (RT-001). See that dataclass's docstring for the full contract.


def _get_streams(app: Any) -> SlotTable:
    """Shared admission budget for every indefinite text/event-stream this
    router holds open: stream id -> (owner identity key, owning ASGI request
    task, release callable). Both ``mcp_get`` (Streamable HTTP ``GET /mcp``)
    and ``mcp_sse`` (legacy ``GET /mcp/sse``) register their stream here
    before their
    ``StreamingResponse`` is created and count against the SAME
    ``_MAX_GET_STREAMS``/``_MAX_GET_STREAMS_PER_IDENTITY`` cap — they consume
    the same single-process connection pool, so a cap on only one transport
    is trivially bypassed by calling the other (RT-001). Mirrors
    ``_sse_queues()``'s lazy-init accessor pattern; ``_sse_queues()`` itself
    remains a separate structure, purely for legacy session→queue routing.

    RELEASE IS LAYERED THREE WAYS (RT-001 — a bare generator ``finally`` is
    not a lifecycle hook and does not run when the generator body never
    starts):
    1. ``heartbeats()``'s ``finally`` — fast path, fires whenever the
       generator body actually started (normal disconnect/cancellation).
    2. The ``StreamingResponse``'s ``BackgroundTask`` — fires after the ASGI
       response cycle completes even when the generator body was never
       entered (e.g. Starlette's spec_version<2.4 path cancelling
       ``stream_response`` at the ``send(http.response.start)`` checkpoint).
    3. ``_prune_get_streams`` — reclaims any entry neither of the above
       released, keyed on the owning task's ``.done()`` (a liveness fact,
       never a wall-clock guess), so a missed release is bounded without
       ever discounting a slot that is still genuinely open. It reclaims by
       CALLING the record's own ``release``, so it always reclaims exactly
       what the fast paths reclaim — see ``_prune_get_streams``.

    RT-001 (round 4): the third element exists because layers 1 and 2 can
    BOTH be skipped — a hard cancellation of the owning ASGI request task
    (as opposed to a client disconnect, which Starlette absorbs in the
    StreamingResponse cancel scope so the BackgroundTask still runs) unwinds
    the response cycle before ``stream_response`` pulls the first chunk AND
    before ``await self.background()`` is reached. ``mcp_sse`` registers TWO
    structures under one key (this slot and its ``_sse_queues()`` session
    router record); a backstop that only popped this dict left the other half
    pinned for the process lifetime, each orphan holding an
    ``asyncio.Queue(maxsize=256)``, and — because the slot half self-healed —
    the admission cap never throttled the repetition."""
    return slot_table(app, "mcp_get_streams")


# RT-002 (round 5): the layer-3 backstop is `common.admission.prune_finished`
# (C-024), shared with routes/a2a.py. Aliased to keep this module's ~6 call
# sites and their surrounding commentary readable.
_prune_get_streams = prune_finished


def _sse_queues(app: Any) -> dict[str, "tuple[asyncio.Queue[str], str]"]:
    """Legacy SSE transport sessions: id → (response queue, owner identity
    key); dropped when the SSE generator exits. Owner binding mirrors the
    Streamable HTTP path."""
    queues = getattr(app.state, "mcp_sse_queues", None)
    if queues is None:
        queues = {}
        app.state.mcp_sse_queues = queues
    return queues


# ---------------------------------------------------------------------------
# JSON-RPC helpers + dispatch
# ---------------------------------------------------------------------------


def _result(request_id: Any, payload: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _is_writable(payload: Any) -> bool:
    """True when ``payload`` survives the strict writers both transports use
    (Starlette ``JSONResponse`` and the legacy queue both refuse non-finite
    floats, GH-173, and both encode to UTF-8, so a lone surrogate must fail
    here, not mid-stream: ``dumps_strict`` checks both). Never raises."""
    try:
        dumps_strict(payload)
    except (ValueError, TypeError):
        return False
    return True


def _writable_response(response: dict[str, Any]) -> dict[str, Any]:
    """Writer backstop for both MCP transports (GH-173): a response the strict
    writer would refuse becomes a fixed -32603 error for the same id, so the
    client always gets exactly one reply and the route never raises a bare
    HTTP 500 (Streamable HTTP) or drops the reply (legacy SSE). tools/call
    output is caught earlier, as an isError result (§5.5); this covers any
    other path. SI-2: never log the payload."""
    if _is_writable(response):
        return response
    logger.error("mcp response not serializable has_result=%s", "result" in response)
    request_id = response.get("id")
    if not _is_writable(request_id):
        request_id = None
    return _error(request_id, _INTERNAL_ERROR, "internal error")


def _negotiated_version(request: Request) -> "str | object | None":
    """Validate ``MCP-Protocol-Version``.

    Returns:
    - ``_HEADER_ABSENT`` sentinel — header not present at all; caller must 400
      on non-initialize requests (MCP spec §10).
    - A version string — header present and recognized; use this version.
    - ``None`` — header present but unrecognized; caller must 400.
    """
    value = request.headers.get(_PROTOCOL_VERSION_HEADER)
    if value is None:
        return _HEADER_ABSENT
    if value in SUPPORTED_PROTOCOL_VERSIONS:
        return value
    return None


async def _dispatch(app: Any, message: dict[str, Any]) -> dict[str, Any] | None:
    """Route one JSON-RPC message. Returns None for notifications (never
    answered — even when the client fabricates an id on one)."""
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params")
    if params is None:
        params = {}

    if not isinstance(method, str) or not method:
        return _error(request_id, _INVALID_REQUEST, "missing method")
    if method.startswith("notifications/"):
        return None
    if not isinstance(params, dict):
        # Defensive: reject non-dict params before any handler touches them.
        return _error(request_id, _INVALID_PARAMS, "params must be an object")

    try:
        if method == "initialize":
            return _result(request_id, _handle_initialize(app, params))
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, _handle_tools_list(app, params))
        if method == "tools/call":
            result = await _handle_tools_call(app, params)
            if isinstance(result, dict) and "__jrpc_error__" in result:
                return _error(request_id, _INVALID_PARAMS, result["__jrpc_error__"])
            if isinstance(result, dict) and "__jrpc_not_found__" in result:
                return _error(request_id, _METHOD_NOT_FOUND, result["__jrpc_not_found__"])
            return _result(request_id, result)
        # SI-2: never reflect user-supplied method name in error text.
        return _error(request_id, _METHOD_NOT_FOUND, "method not found")
    except Exception as exc:
        # Defensive: a handler bug must never leak a stack trace to the wire.
        # SI-2: log class and frame locations only; an exception message can
        # embed a rejected tool-output value (pydantic `input_value=`).
        logger.error(
            "mcp dispatch internal error type=%s at=%s",
            type(exc).__name__,
            frame_locations(exc),
        )
        return _error(request_id, _INTERNAL_ERROR, "internal error")


def _handle_initialize(app: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Echo the client's protocolVersion when we support it; otherwise return
    our highest and let the client decide whether to continue (§5.5).

    serverInfo deliberately carries name/version only (plus title when the
    negotiated version is 2025-11-25 or newer) — ``icons`` makes Claude.ai's
    schema validator reject the handshake (pitchbook LRN-087). ``title`` is
    spec-valid at 2025-06-18 per mcp-protocol.md §2, but we gate it at
    2025-11-25 conservatively (GH-43 observed a rejection; see REVIEWS.md
    Round 4). A future wave can re-test and lower the gate to 2025-06-18.
    """
    client_version = params.get("protocolVersion")
    version = (
        client_version
        if isinstance(client_version, str) and client_version in SUPPORTED_PROTOCOL_VERSIONS
        else SUPPORTED_PROTOCOL_VERSIONS[0]
    )
    settings = app.state.settings
    # display_name normalizes the placeholder/blank to a neutral sentinel so
    # DEV_MODE sessions with AGENT_NAME unset don't advertise "agent" verbatim.
    # In production build_app()'s ValueError prevents the placeholder from
    # reaching here, but DEV_MODE allows it — so normalize consistently.
    display_name = settings.display_name
    server_info: dict[str, Any] = {
        "name": display_name,
        "version": settings.agent_version,
    }
    # title was added in 2025-11-25; only emit it when the negotiated version
    # is that version or newer.  SUPPORTED_PROTOCOL_VERSIONS is newest-first,
    # so an index comparison is sufficient.
    if (
        SUPPORTED_PROTOCOL_VERSIONS.index(version)
        <= SUPPORTED_PROTOCOL_VERSIONS.index(_TITLE_MIN_VERSION)
    ):
        server_info["title"] = display_name
    result: dict[str, Any] = {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": server_info,
    }
    # Surface the per-call credential header to Claude.ai, which injects
    # instructions into model context (a2a-advisor). Omitted entirely when no
    # source declares credentials, so the handshake stays minimal otherwise.
    from ..credentials.card import forwarding_instructions

    parts = [
        forwarding_instructions(getattr(app.state, "credential_fields", {})),
        getattr(app.state, "mcp_instructions", None),
    ]
    instructions = "\n\n".join(p for p in parts if p)
    if instructions:
        result["instructions"] = instructions
    return result


_PAGE_SIZE = 64


def _decode_cursor(cursor: Any) -> int:
    """Decode an opaque base64-encoded cursor to an int offset.
    Invalid or absent cursor → 0."""
    if not cursor or not isinstance(cursor, str):
        return 0
    try:
        return int(base64.b64decode(cursor.encode()).decode())
    except Exception:
        return 0


def _encode_cursor(offset: int) -> str:
    return base64.b64encode(str(offset).encode()).decode()


def _handle_tools_list(app: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Tier 1 only (§5.6). ``outputSchema`` appears ONLY when the tool
    declares ``emits`` — structuredContent is never emitted unclaimed.
    Supports cursor/nextCursor pagination (PAGE_SIZE=64)."""
    if params is None:
        params = {}
    all_entries = app.state.registry.tier1()
    # RT-001: clamp to ≥0 — a crafted negative base64 cursor wraps Python list
    # slicing to the tail of the list, bypassing forward-only pagination.
    offset = max(0, _decode_cursor(params.get("cursor")))
    page_entries = all_entries[offset : offset + _PAGE_SIZE]

    tools: list[dict[str, Any]] = []
    for entry in page_entries:
        tool: dict[str, Any] = {
            "name": entry.name,
            "description": entry.description,
            "inputSchema": entry.input_schema(),
        }
        if entry.title:
            tool["title"] = entry.title
        output_schema = entry.output_schema()
        if output_schema is not None:
            tool["outputSchema"] = output_schema
        if entry.annotations:
            tool["annotations"] = entry.annotations
        tools.append(tool)

    result: dict[str, Any] = {"tools": tools}
    next_offset = offset + _PAGE_SIZE
    if next_offset < len(all_entries):
        result["nextCursor"] = _encode_cursor(next_offset)
    return result


def _tool_text(artifact: Any) -> str:
    """Serialized text block — ALWAYS present in a tools/call result.

    RT-001: ``None`` folds to the empty string, mirroring agent/loop.py's
    ``fold_result_content(None) -> {"text": ""}`` — a void Tier-1 tool must
    report the same success/failure verdict on every surface (§5.6 parity
    rule), never the literal string ``"None"``.
    """
    if artifact is None:
        return ""
    if isinstance(artifact, ContentModel):
        return artifact.to_plain_text()
    if isinstance(artifact, BaseModel):
        return artifact.model_dump_json(exclude_none=True)
    return str(artifact)


async def _handle_tools_call(app: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Validate → invoke → fold. Protocol-shape faults surface via sentinels:
    - ``__jrpc_error__``: invalid-params (-32602) — missing/non-string name,
      non-dict arguments.
    - ``__jrpc_not_found__``: method-not-found (-32601) — unknown tool name
      (Tier 2 tools are indistinguishable from unknown on this surface, §5.6).
    Anything raised INSIDE the tool — AgentError or otherwise — is an
    ``isError: true`` RESULT, never a JSON-RPC error (§5.5)."""
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return {"__jrpc_error__": "tools/call requires a 'name' string"}
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return {"__jrpc_error__": "tools/call 'arguments' must be an object"}

    entry = app.state.registry.get(name)
    # A Tier 2 tool must be indistinguishable from an unknown name on this
    # surface (§5.6 — MCP exposes Tier 1 only).
    if entry is None or entry.tier != 1:
        # SI-2: never reflect user-supplied tool name in error text.
        return {"__jrpc_not_found__": "tool not found"}

    timeout = resolve_tool_timeout(name, entry, app.state.loop_policies)
    try:
        # RT-001: dispatch through the shared ToolEntry.invoke_any() helper
        # (registry.py) rather than re-implementing the is_generator branch
        # here — it also resolves a long_running=True coroutine tool's
        # DeferredResult inline (tools/call has no background task delivery
        # channel to hand it off to, unlike agent/runner.py), under the
        # SAME single timeout deadline as the initial invoke/drain (RT-003:
        # the handle gets only the REMAINING budget, never a fresh `timeout`
        # seconds on top) — never folding the DeferredResult itself (its
        # repr, including the raw handle coroutine object, must never reach
        # the wire, and the handle must never be silently dropped unawaited).
        artifact = await entry.invoke_any(arguments, app.state.adapters, timeout=timeout)
    except ToolInterrupt:
        # RT-001: mirror agent/loop.py's dedicated ToolInterrupt branches
        # (lines 474/498) rather than falling through to the generic
        # Exception fallback below. MCP has no HITL/resume channel (no
        # wait_resume equivalent) to service the interrupt, so surface a
        # distinct, diagnosable isError instead of an opaque generic failure.
        logger.warning("mcp tool interrupt tool=%s", name)
        return {
            "content": [
                {
                    "type": "text",
                    "text": "tool requires interactive confirmation, unsupported over MCP",
                }
            ],
            "isError": True,
        }
    except AgentError as exc:
        # AgentError.public() is the consumer-safe shape (no inputs/secrets).
        public = exc.public()
        text = f"[{public['category']}] {public['message']}"
        logger.warning("mcp tool error tool=%s category=%s", name, public["category"])
        return {"content": [{"type": "text", "text": text}], "isError": True}
    except asyncio.TimeoutError:
        # RT-004: mirror agent/loop.py's timeout branch (lines 476-477/500-501)
        # so a timeout is diagnosable rather than folding into the generic
        # fallback below. `name` is a registry-resolved tool identifier, not
        # caller-controlled free text (SI-2).
        text = f"tool '{name}' timed out after {timeout:g}s"
        logger.warning("mcp tool timeout tool=%s timeout=%s", name, timeout)
        return {"content": [{"type": "text", "text": text}], "isError": True}
    except ToolInputValidationError as exc:
        # RT-004/GH-135: mirror agent/loop.py's ToolInputValidationError branch
        # — safe_validation_message keeps only loc + type (schema-declared
        # field names and Pydantic type codes), never exc's raw msg/input
        # (SI-2), so the model gets a correctable diagnostic instead of the
        # opaque generic fallback below. GH-135: this discriminator is raised
        # ONLY by the input-model coercion step, never by the tool body, so a
        # body-raised ValidationError falls through to that generic fallback
        # instead of being misreported as caller input here.
        text = safe_validation_message(name, exc.validation_error, entry.decl.input_model)
        logger.warning("mcp tool input validation failed tool=%s", name)
        return {"content": [{"type": "text", "text": text}], "isError": True}
    except Exception as exc:
        # Message stays generic — nothing caller-supplied is echoed.
        # SI-2/RT-001: a body-raised ValidationError (GH-135's discriminator
        # only catches the input-model coercion step above) has a __str__
        # that embeds the raw rejected value (`input_value=...`) — same for
        # any other exception whose message interpolates caller/tool-derived
        # data. `logger.exception`/`exc_info=True` would format that message
        # straight into the log, so we never log exc's message or its
        # formatted traceback text. RT-010: dropping the traceback ENTIRELY
        # over-corrected — a genuine bug (AttributeError, KeyError, TypeError)
        # in a tool body became undiagnosable (bare class name, no file/line).
        # frame_locations() (common/redact.py) carries no interpolated values
        # (FrameSummary.filename/lineno only — never `.line`, which echoes
        # source text that could itself contain a caller-derived literal), so
        # logging it satisfies SI-2 (suppresses the message) without
        # sacrificing diagnosability. RT-004: the same helper backs
        # routes/admin.py's try-tool and every agent/loop.py dispatch site so
        # the cross-surface parity this comment claims is actually true.
        frames = frame_locations(exc)
        logger.error(
            "mcp tool unexpected error tool=%s error_type=%s frames=%s",
            name,
            type(exc).__name__,
            frames,
        )
        # SI-2: never reflect user-supplied / tool-derived names in error text;
        # the tool name is already recorded in the structured log above.
        return {
            "content": [{"type": "text", "text": "tool execution failed"}],
            "isError": True,
        }

    emits_type = entry.decl.emits
    # RT-001/RT-002: a drained async-generator with no terminal yield resolves
    # to ToolTerminalResult(value=None) (registry.py's invoke_gen), and a plain
    # coroutine tool may simply `return None` — symmetric cases, and this holds
    # REGARDLESS of whether the tool declares `emits`. loop.py's run_loop folds
    # this identical None result into a SUCCESS toolResult
    # (fold_result_content(None) -> {"text": ""}, status "success") on the
    # A2A/AG-UI surfaces. §5.6 requires Tier-1 tools to behave identically
    # across surfaces, so MCP must not diverge into isError: true here — that
    # would make the same void tool call succeed over A2A/AG-UI yet fail over
    # MCP. _tool_text(None) below folds to "" (not the literal "None"); no
    # structuredContent is emitted (the SC-C1 coercion attempt below is
    # skipped for a None artifact, so `emits_type.model_validate(None)` is
    # never reached to raise), which is spec-consistent: MCP §4 only requires
    # structuredContent when the tool actually produces output to describe.
    if artifact is None:
        logger.info(
            "mcp tool produced no result tool=%s emits_declared=%s",
            name,
            emits_type is not None,
        )
    elif emits_type is not None and not isinstance(artifact, BaseModel):
        # SC-C1: if the tool declares emits but the artifact is a raw dict/scalar,
        # attempt to coerce it into the declared emits model so structuredContent
        # can be emitted (MCP §4 MUST when outputSchema is advertised).
        try:
            artifact = emits_type.model_validate(artifact)
        except Exception as exc:
            # MCP §4: structuredContent MUST be present when outputSchema is declared.
            # Coercion failure → surface as isError so clients can detect the contract
            # violation rather than receiving a silent success with no structuredContent.
            # SI-2: tool name and exc type go to the structured log only — never echoed
            # to the caller in the isError text.
            logger.warning(
                "mcp tool output coercion failed tool=%s exc_type=%s",
                name,
                type(exc).__name__,
            )
            return {
                "content": [{"type": "text", "text": "tool output coercion failed"}],
                "isError": True,
            }

    result: dict[str, Any] = {
        "content": [{"type": "text", "text": _tool_text(artifact)}],
        "isError": False,
    }
    # structuredContent ONLY under a declared output schema (emits), and only
    # when the artifact actually is a model we can serialize against it.
    # RTGA-001: MarketBriefing is the sole prose-exception type. On the
    # AG-UI/A2A wire its value is a bare markdown string (to_markdown()),
    # never the field dict (wire()) — see DESIGN §4.3: "MarketBriefing is
    # the only type whose wire data is a markdown string — the translator
    # emits model.to_markdown(), never model_dump()."
    # GH-105: on THIS (MCP) surface, MCP 2025-06-18 requires structuredContent
    # to always be a JSON object, so the markdown is wrapped as
    # {"markdown": to_markdown()}; content[0].text still carries the raw
    # markdown unchanged, and the AG-UI/A2A bare-string wire contract
    # (translator.py) is untouched.
    if entry.output_schema() is not None and isinstance(artifact, BaseModel):
        result["structuredContent"] = (
            {"markdown": artifact.to_markdown()}
            if isinstance(artifact, MarketBriefing)
            else artifact.wire()
            if isinstance(artifact, ContentModel)
            else artifact.model_dump(mode="json", exclude_none=True)
        )
    # GH-173: a value that bypassed validation (model_construct, assignment
    # after construction, a domain list[float]) can still hold nan/inf here.
    # The strict writers would refuse it and the route would 500 or drop the
    # reply. A tool fault is a RESULT on this surface (§5.5), so report it as
    # isError with fixed text; log the tool name only, never the value (SI-2).
    if not _is_writable(result):
        logger.error("mcp tool output not serializable tool=%s", name)
        return {
            "content": [{"type": "text", "text": "tool output not serializable"}],
            "isError": True,
        }
    return result


# ---------------------------------------------------------------------------
# Streamable HTTP — POST / GET / DELETE /mcp
# ---------------------------------------------------------------------------


@router.post("")
async def mcp_post(
    request: Request, identity: Identity = Depends(require_identity)
) -> Response:
    guard_origin(request)
    sessions = _sessions(request.app)
    _prune_sessions(sessions)
    owner = _identity_key(identity)

    # MCP Streamable HTTP 2025-06-18 §3.2.1: clients MUST send
    # Content-Type: application/json.  Reject non-conforming requests with 415;
    # guard with `if ct` to preserve no-header pass-through (dev tools often omit it).
    ct = request.headers.get("content-type", "").split(";")[0].strip()
    if ct and ct != "application/json":
        return JSONResponse(
            status_code=415,
            content={"error": "Content-Type must be application/json"},
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )

    raw = await request.body()
    # RTGA-006: parse the message FIRST so we can determine is_initialize before
    # validating MCP-Protocol-Version.  initialize must bypass the version-header
    # 400 and proceed to body-level negotiation (DESIGN §5.5).
    if len(raw) > _MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413, content={"error": "request body too large"},
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )
    try:
        message = loads_strict(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(
            content=_error(None, _PARSE_ERROR, "parse error"),
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )
    if not isinstance(message, dict):
        return JSONResponse(
            content=_error(None, _INVALID_REQUEST, "invalid request"),
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )

    is_initialize = message.get("method") == "initialize"

    # RTGA-006: validate MCP-Protocol-Version only on post-init requests.  An
    # initialize request must always proceed — the negotiation result in the
    # response body is authoritative, so even a future/unsupported header value
    # is not grounds for 400 here.
    version = _negotiated_version(request)
    if (version is None or version is _HEADER_ABSENT) and not is_initialize:
        # MCP spec §10: absent or unrecognized version header on a non-initialize
        # request → 400; advertise a version we support so the client can retry.
        return JSONResponse(
            status_code=400,
            content={"error": "MCP-Protocol-Version header required"},
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )
    # For initialize with an absent/unrecognized header, fall back to our
    # highest so base_headers is always a valid version string.
    effective_version = (
        version
        if isinstance(version, str)
        else SUPPORTED_PROTOCOL_VERSIONS[0]
    )
    base_headers = {_PROTOCOL_VERSION_HEADER: effective_version}

    # Session lifecycle: an unknown/expired Mcp-Session-Id is a 404 — except
    # for initialize itself, the recovery path after a server restart.
    presented_session = request.headers.get(_SESSION_ID_HEADER)
    # SI-3: cap header length before any lookup — server-issued ids are
    # uuid4().hex (32 chars); 64 chars is generous for any future format while
    # bounding memory and comparison cost. Value is never logged or echoed (SI-2).
    if presented_session is not None and len(presented_session) > 64:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid session id"},
            headers=base_headers,
        )
    if presented_session is not None and not is_initialize:
        if not _session_alive(sessions, presented_session, owner):
            return JSONResponse(
                status_code=404, content={"error": "session not found"}, headers=base_headers
            )
    # If the header is absent on a non-initialize request AND the owner already
    # has at least one live session, the client is misbehaving — reject with 400
    # so it can recover via re-initialize rather than silently creating orphaned
    # dispatch without a session context.
    if presented_session is None and not is_initialize:
        owner_has_session = any(rec[1] == owner for rec in sessions.values())
        if owner_has_session:
            return JSONResponse(
                status_code=400,
                content={"error": "Mcp-Session-Id required"},
                headers=base_headers,
            )

    # Per-call forwarded credentials are request-scoped: bind around dispatch
    # (synchronous, same task as the tool invoke) and unbind in finally.
    token = forwarding.bind(forwarding.parse_header(request.headers.get(forwarding.HEADER_NAME)))
    try:
        response = await _dispatch(request.app, message)
    finally:
        forwarding.unbind(token)

    # Notifications (and fabricated-id notifications) → 202 Accepted, empty.
    if response is None or message.get("id") is None:
        return Response(status_code=202, headers=base_headers)

    response = _writable_response(response)
    headers = dict(base_headers)
    if is_initialize and "result" in response:
        # RTGA-010: evict any existing sessions for this owner before allocating
        # a new one.  Re-initialization with an existing session leaks an orphan
        # slot that counts against the LRU cap until TTL expiry.  The old session
        # is worthless to the caller anyway (they're reinitializing), so eager
        # eviction keeps the session map compact.
        for orphan_sid in [s for s, rec in list(sessions.items()) if rec[1] == owner]:
            sessions.pop(orphan_sid, None)
        session_id = uuid.uuid4().hex
        sessions[session_id] = (time.time(), owner)  # bound to the caller
        _prune_sessions(sessions)
        headers[_SESSION_ID_HEADER] = session_id
        # P6-00: override the response version header with the negotiated
        # version from the initialize result body (the request may have carried
        # no MCP-Protocol-Version header, so base_headers holds the fallback
        # default; the body always contains the real negotiated version).
        negotiated_ver = response["result"].get("protocolVersion")
        if negotiated_ver:
            headers[_PROTOCOL_VERSION_HEADER] = negotiated_ver

    return JSONResponse(content=response, headers=headers)


@router.get("", response_model=None)
async def mcp_get(
    request: Request, identity: Identity = Depends(require_identity)
) -> StreamingResponse | JSONResponse:
    """Server→client SSE channel. We send no server-initiated messages
    (``listChanged: false``) so the stream is idle heartbeats — but it MUST
    exist: Claude.ai Desktop treats the connection as established only once
    this GET returns 200 text/event-stream (LRN-053; 405 breaks it)."""
    guard_origin(request)

    # GH-111: mirror mcp_post's validation — a present-but-unrecognized
    # MCP-Protocol-Version must 400 here too; absent is allowed (no
    # negotiation body to validate against on this verb).  The message names
    # the ACTUAL trigger (present-but-unrecognized): unlike mcp_post, an absent
    # header is accepted here, so "header required" would misdirect a client
    # that DID send a version into thinking it omitted the header (RT-005).
    if _negotiated_version(request) is None:
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported MCP-Protocol-Version"},
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )

    # GH-143: cap concurrent open heartbeat streams — global cap first (bounds
    # total process load, shared with mcp_sse below), then per-identity cap
    # (one caller can't consume every other tenant's share) — BEFORE the
    # StreamingResponse is created. See _MAX_GET_STREAMS's comment for why
    # this rejects rather than evicts.
    streams = _get_streams(request.app)
    # RT-001: reclaim any slot layers 1/2 in _get_streams()'s docstring missed
    # — keyed on owning-task liveness, not elapsed time — before checking the
    # cap against it.
    await _prune_get_streams(streams)
    if len(streams) >= _MAX_GET_STREAMS:
        return JSONResponse(
            status_code=429,
            content={"error": "too many concurrent MCP GET streams"},
            headers={
                "Retry-After": "5",
                _PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0],
            },
        )
    owner = _identity_key(identity)
    owner_count = count_for_owner(streams, owner)
    if owner_count >= _max_streams_per_identity(request.app):
        return JSONResponse(
            status_code=429,
            content={"error": "too many concurrent MCP GET streams for this identity"},
            headers={
                "Retry-After": "5",
                _PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0],
            },
        )
    stream_id = uuid.uuid4().hex
    # RT-001: the ASGI request task itself is the liveness fact _prune_get_streams
    # keys on — it stays not-done for the entire response cycle, StreamingResponse
    # body and background task included, so a still-open stream is never mistaken
    # for a stale one no matter how long it has held its connection.
    owning_task = asyncio.current_task()
    assert owning_task is not None

    async def release() -> None:
        # The COMPLETE teardown for this slot — this route registers nothing
        # else, so it is a single pop. Idempotent: all three release layers
        # (heartbeats()'s finally, the BackgroundTask, _prune_get_streams)
        # call this same callable.
        #
        # RT-001: MUST be `async def`, not `def` — Starlette's BackgroundTask
        # dispatches a plain `def` via run_in_threadpool (an AnyIO worker
        # thread), which would mutate `streams` (event-loop-owned state the
        # loop concurrently iterates in `_prune_get_streams` and the
        # per-identity `owner_count` scan above) off-loop, racing that
        # iteration and able to raise "dict mutated during iteration".
        # `async def` makes Starlette await it in-loop instead.
        streams.pop(stream_id, None)

    streams[stream_id] = StreamSlot(owner=owner, owning_task=owning_task, release=release)

    # Last-Event-ID not implemented: server emits no server-initiated messages (listChanged=False), so nothing to resume.
    async def heartbeats() -> AsyncIterator[bytes]:
        try:
            # Padding comment forces proxy buffers to flush the first chunk so
            # the client marks the channel open immediately.
            yield b": " + b"x" * 256 + b"\n\n"
            while True:
                if await request.is_disconnected():
                    return
                await asyncio.sleep(_HEARTBEAT_SECONDS)
                yield HEARTBEAT
        finally:
            # Fast path — fires on any disconnect/cancellation once the
            # generator body has actually started running.
            await release()

    return StreamingResponse(
        heartbeats(),
        media_type="text/event-stream",
        headers=dict(SSE_HEADERS),
        background=BackgroundTask(release),
    )


@router.delete("")
async def mcp_delete(
    request: Request, identity: Identity = Depends(require_identity)
) -> Response:
    """Session termination — idempotent (an already-gone id is still 204).
    Only the owning caller can terminate a session; a mismatch is a silent
    no-op 204 so one caller can never delete another's session."""
    guard_origin(request)
    # GH-111: mirror mcp_post / mcp_get's validation — a present-but-
    # unrecognized MCP-Protocol-Version must 400 here too; absent is allowed.
    # Message names the actual trigger (present-but-unrecognized), since an
    # absent header is accepted on this verb — "header required" would mislead
    # a client that DID send a version (RT-005).
    if _negotiated_version(request) is None:
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported MCP-Protocol-Version"},
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )
    session_id = request.headers.get(_SESSION_ID_HEADER)
    # SI-3: cap header length before any lookup — mirrors mcp_post() (line 517)
    # and mcp_messages() (line 700). A value over 64 chars can never be a
    # server-issued uuid4().hex (32 chars), so reject it with 400 rather than
    # letting an oversized id fall through to a silent idempotent 204.
    if session_id is not None and len(session_id) > 64:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid session id"},
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )
    if session_id:
        sessions = _sessions(request.app)
        rec = sessions.get(session_id)
        if rec is not None and rec[1] == _identity_key(identity):
            sessions.pop(session_id, None)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Legacy SSE transport — GET /mcp/sse + POST /mcp/messages
# ---------------------------------------------------------------------------


@router.get("/sse", response_model=None)
async def mcp_sse(
    request: Request, identity: Identity = Depends(require_identity)
) -> StreamingResponse | JSONResponse:
    """Legacy HTTP+SSE pair: announce the session-bound messages endpoint as
    the first event; JSON-RPC responses ride this channel as message events.

    RT-001 (GH-143 follow-up): this is an authenticated, indefinitely-held
    text/event-stream identical in kind to mcp_get's — it must be admitted
    under the SAME global + per-identity budget (_get_streams(), see its
    docstring), checked BEFORE the StreamingResponse is created, and rejected
    (never evicted) once at capacity. See _MAX_GET_STREAMS's comment for the
    reject-over-evict rationale, including why evict-oldest here specifically
    was also a cross-tenant DoS on other callers' live session routes.
    """
    guard_origin(request)

    streams = _get_streams(request.app)
    await _prune_get_streams(streams)
    if len(streams) >= _MAX_GET_STREAMS:
        return JSONResponse(
            status_code=429,
            content={"error": "too many concurrent MCP GET streams"},
            headers={"Retry-After": "5"},
        )
    owner = _identity_key(identity)
    owner_count = count_for_owner(streams, owner)
    if owner_count >= _max_streams_per_identity(request.app):
        return JSONResponse(
            status_code=429,
            content={"error": "too many concurrent MCP GET streams for this identity"},
            headers={"Retry-After": "5"},
        )

    session_id = uuid.uuid4().hex
    owning_task = asyncio.current_task()
    assert owning_task is not None

    queues = _sse_queues(request.app)
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)

    async def release() -> None:
        # RT-001: the COMPLETE teardown for this slot — this route registers
        # TWO structures under `session_id`, so both are dropped here. All
        # three release layers (stream()'s finally, the BackgroundTask, and
        # _prune_get_streams) call this same callable, so the backstop can
        # never reclaim less than the fast paths do. Idempotent.
        #
        # RT-001: MUST be `async def` — see mcp_get's `release` for why a
        # plain `def` here races the loop's own iteration of `streams` off
        # a threadpool worker thread (Starlette's BackgroundTask dispatch).
        streams.pop(session_id, None)
        queues.pop(session_id, None)

    # Registered together under one key and released together — that pairing
    # is the invariant set(_sse_queues()) ⊆ set(_get_streams()), which is what
    # bounds _sse_queues() by _MAX_GET_STREAMS. No await separates these two
    # statements, so no other task can observe a half-registered session.
    streams[session_id] = StreamSlot(owner=owner, owning_task=owning_task, release=release)
    queues[session_id] = (queue, owner)  # bound to the caller

    async def stream() -> AsyncIterator[bytes]:
        try:
            yield (
                f"event: endpoint\ndata: /mcp/messages?session_id={session_id}\n\n"
            ).encode()
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield HEARTBEAT
                    continue
                yield f"event: message\ndata: {payload}\n\n".encode()
        finally:
            await release()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=dict(SSE_HEADERS),
        background=BackgroundTask(release),
    )


@router.post("/messages")
async def mcp_messages(
    request: Request,
    session_id: str,
    identity: Identity = Depends(require_identity),
) -> Response:
    """Same JSON-RPC dispatch as POST /mcp; the response is enqueued onto the
    session's SSE channel and the POST acks with 202. The caller must own the
    session (mismatch → 404, no existence oracle)."""
    guard_origin(request)
    # SI-3: cap query-param length before any lookup — mirrors the 64-char guard
    # in mcp_post() on the Mcp-Session-Id header.  Value is never logged or
    # echoed in the error response (SI-2).
    if session_id and len(session_id) > 64:
        raise HTTPException(status_code=400, detail="session_id too long")
    rec = _sse_queues(request.app).get(session_id)
    if rec is None or rec[1] != _identity_key(identity):
        return JSONResponse(status_code=404, content={"error": "session not found"})
    queue = rec[0]

    # RT-001/RTGA-006: parse the body FIRST so is_initialize can be detected
    # before the MCP-Protocol-Version gate — mirroring mcp_post (lines 451-487).
    # An initialize request on the legacy HTTP+SSE path carries no version header
    # on first contact and must not be rejected with 400 before negotiation.
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413, content={"error": "request body too large"},
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )
    try:
        message = loads_strict(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        # RTGA-003: use put_nowait to avoid blocking indefinitely on a full/dead queue.
        try:
            queue.put_nowait(json.dumps(_error(None, _PARSE_ERROR, "parse error")))
        except asyncio.QueueFull:
            return Response(status_code=503, content=b"session queue full")
        return Response(status_code=202)
    if not isinstance(message, dict):
        try:
            queue.put_nowait(json.dumps(_error(None, _INVALID_REQUEST, "invalid request")))
        except asyncio.QueueFull:
            return Response(status_code=503, content=b"session queue full")
        return Response(status_code=202)

    is_initialize = message.get("method") == "initialize"

    version = _negotiated_version(request)
    # Legacy path: _HEADER_ABSENT (header omitted) → tolerate for back-compat (§10 SHOULD);
    # None (header present but unrecognized) → 400. Streamable path rejects both.
    # NOTE: _dispatch() below is version-agnostic — no resolved version value is threaded
    # into it, so this branch is purely an admission check, not a version assumption.
    if version is None and not is_initialize:
        return JSONResponse(
            status_code=400,
            content={"error": "MCP-Protocol-Version header required"},
            headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
        )

    token = forwarding.bind(forwarding.parse_header(request.headers.get(forwarding.HEADER_NAME)))
    try:
        response = await _dispatch(request.app, message)
    finally:
        forwarding.unbind(token)
    if response is not None and message.get("id") is not None:
        # RTGA-003: put_nowait matches the SDK pattern in tasks/store.py (lines 44-54);
        # await queue.put() would block indefinitely when the SSE consumer is slow or gone.
        try:
            queue.put_nowait(dumps_strict(_writable_response(response)))
        except asyncio.QueueFull:
            return Response(status_code=503, content=b"session queue full")
    return Response(status_code=202)
