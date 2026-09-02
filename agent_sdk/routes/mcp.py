"""MCP 2025-06-18 Streamable HTTP routes (DESIGN.md §5.5, §5.6).

Three verbs at ``/mcp``:

- ``POST /mcp`` — JSON-RPC 2.0. Session id allocated on ``initialize`` and
  returned via ``Mcp-Session-Id``; a non-initialize POST bearing an
  unknown/expired session id → 404 (initialize itself is the recovery path).
- ``GET /mcp`` — server→client SSE channel, held open with heartbeats.
  Returning 405 here breaks Claude.ai Desktop (pitchbook LRN-053) — never.
- ``DELETE /mcp`` — session termination, idempotent, 204.

Legacy SSE pair (``GET /mcp/sse`` + ``POST /mcp/messages?session_id=``)
retained for older clients; same dispatch path.

Methods: ``initialize`` (echo the client's protocolVersion when supported,
else our highest), ``ping``, ``tools/list`` (Tier 1 only — surface parity rule
§5.6; ``outputSchema`` only when the tool declares ``emits``), ``tools/call``
(text block always + ``structuredContent`` only under a declared output
schema; tool failures are ``isError: true`` results, NEVER JSON-RPC errors).
A Tier-1 tool that returns/yields no terminal value (``None``) is NOT a
failure — regardless of whether it declares ``emits``, it folds to
``isError: false`` with an empty text block and no ``structuredContent``,
matching agent/loop.py's ``_fold_result_content(None)`` fold on the A2A/AG-UI
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

from ..auth.identity import Identity
from ..auth.middleware import require_identity
from ..common.origin import guard_origin
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
# RT-003: cap legacy SSE sessions to prevent unbounded queue growth under
# long-lived connections (each entry holds an asyncio.Queue(maxsize=256)).
_MAX_SSE_SESSIONS = 500
_MAX_BODY_BYTES = 2 * 1024 * 1024
_HEARTBEAT_SECONDS = 15.0

# JSON-RPC 2.0 standard error codes.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# Session stores (per-app, in-memory — single-process invariant, DESIGN §2)
# ---------------------------------------------------------------------------


def _identity_key(identity: Identity) -> str:
    """Stable per-caller key used to bind a session to its owner."""
    return f"{identity.kind}:{identity.subject}"


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
    except Exception:
        # Defensive: a handler bug must never leak a stack trace to the wire.
        logger.exception("mcp dispatch internal error method=%s", method)
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

    instructions = forwarding_instructions(getattr(app.state, "credential_fields", {}))
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
    ``_fold_result_content(None) -> {"text": ""}`` — a void Tier-1 tool must
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
        # RT-004: raised ONLY by ToolEntry.invoke/invoke_gen's narrow
        # model_validate try — never by the tool body — mirroring
        # agent/loop.py's matching branch. A bare ValidationError (raised
        # while the tool body builds its ContentModel return value) now
        # falls to the generic Exception branch below instead of being
        # mistaken for an input-shape defect. safe_validation_message keeps
        # only loc + type (schema-declared field names and Pydantic type
        # codes), never exc's raw msg/input (SI-2).
        text = safe_validation_message(
            exc.tool_name, exc.validation_error, exc.input_model
        )
        logger.warning("mcp tool input validation failed tool=%s", name)
        return {"content": [{"type": "text", "text": text}], "isError": True}
    except Exception:
        # Message stays generic — nothing caller-supplied is echoed.
        logger.exception("mcp tool unexpected error tool=%s", name)
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
    # (_fold_result_content(None) -> {"text": ""}, status "success") on the
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
        message = json.loads(raw.decode("utf-8")) if raw else {}
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
    request: Request, _identity: Identity = Depends(require_identity)
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

    # Last-Event-ID not implemented: server emits no server-initiated messages (listChanged=False), so nothing to resume.
    async def heartbeats() -> AsyncIterator[bytes]:
        # Padding comment forces proxy buffers to flush the first chunk so the
        # client marks the channel open immediately.
        yield b": " + b"x" * 256 + b"\n\n"
        while True:
            if await request.is_disconnected():
                return
            await asyncio.sleep(_HEARTBEAT_SECONDS)
            yield HEARTBEAT

    return StreamingResponse(
        heartbeats(), media_type="text/event-stream", headers=dict(SSE_HEADERS)
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


@router.get("/sse")
async def mcp_sse(
    request: Request, identity: Identity = Depends(require_identity)
) -> StreamingResponse:
    """Legacy HTTP+SSE pair: announce the session-bound messages endpoint as
    the first event; JSON-RPC responses ride this channel as message events."""
    guard_origin(request)
    session_id = uuid.uuid4().hex
    queues = _sse_queues(request.app)
    # RT-003: evict the oldest entry when the cap is reached so the dict stays
    # bounded even when clients hold connections open indefinitely.
    while len(queues) >= _MAX_SSE_SESSIONS:
        queues.pop(next(iter(queues)), None)
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
    queues[session_id] = (queue, _identity_key(identity))  # bound to the caller

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
            queues.pop(session_id, None)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers=dict(SSE_HEADERS)
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
        message = json.loads(raw.decode("utf-8")) if raw else {}
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
            queue.put_nowait(json.dumps(response))
        except asyncio.QueueFull:
            return Response(status_code=503, content=b"session queue full")
    return Response(status_code=202)
