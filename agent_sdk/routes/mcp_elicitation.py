"""GH-224 — MCP elicitation helpers: schema converter, content validator,
pending-request table and the per-call state of SSE answer mode.

Pure building blocks only. The orchestration (trigger, worker, stream) lives in
``routes/mcp.py`` because it needs the session table and the tool dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from ..common.json_strict import dumps_strict
from ..common.redact import _SECRET_KEY
from ..common.schema import flatten_schema

__all__ = [
    "MAX_PENDING_PER_SESSION",
    "CallState",
    "ElicitationCancelled",
    "ElicitationDisconnected",
    "PendingTable",
    "convert_schema",
    "validate_content",
]

MAX_PENDING_PER_SESSION = 8

logger = logging.getLogger(__name__)

_STRING_FORMATS = frozenset({"email", "uri", "date", "date-time"})
_NON_FLAT = ("$ref", "anyOf", "oneOf", "allOf", "not", "if", "then", "else")


class ElicitationCancelled(Exception):
    """The session ended while a call waited for the user's answer."""


class ElicitationDisconnected(Exception):
    """The client dropped the stream while a call waited for the answer."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _kept_text(src: dict[str, Any], out: dict[str, Any]) -> None:
    for key in ("title", "description"):
        if isinstance(src.get(key), str):
            out[key] = src[key]


def _property_type(prop: dict[str, Any]) -> str | None:
    kind = prop.get("type")
    if isinstance(kind, list):
        rest = [k for k in kind if k != "null"]
        kind = rest[0] if len(rest) == 1 and len(kind) == 2 else None
    if kind is None and "enum" in prop:
        return "string"
    return kind if isinstance(kind, str) else None


_COMMON_KEYS = frozenset({"type", "title", "description", "default"})
_ALLOWED_KEYS = {
    "string": _COMMON_KEYS | {"enum", "enumNames", "minLength", "maxLength", "format"},
    "number": _COMMON_KEYS | {"minimum", "maximum"},
    "integer": _COMMON_KEYS | {"minimum", "maximum"},
    "boolean": _COMMON_KEYS,
}


def _convert_property(prop: Any) -> dict[str, Any] | None:
    if not isinstance(prop, dict) or any(k in prop for k in _NON_FLAT):
        return None
    kind = _property_type(prop)
    if kind not in _ALLOWED_KEYS or not set(prop) <= _ALLOWED_KEYS[kind]:
        return None
    out: dict[str, Any] = {}
    if kind == "string":
        out["type"] = "string"
        enum = prop.get("enum")
        if enum is not None:
            if not isinstance(enum, list) or not enum or not all(isinstance(v, str) for v in enum):
                return None
            out["enum"] = list(enum)
            names = prop.get("enumNames")
            if isinstance(names, list) and len(names) == len(enum) and all(isinstance(n, str) for n in names):
                out["enumNames"] = list(names)
        for key in ("minLength", "maxLength"):
            if key in prop:
                if not _is_int(prop[key]) or prop[key] < 0:
                    return None
                out[key] = prop[key]
        if "format" in prop:
            if prop["format"] not in _STRING_FORMATS:
                return None
            out["format"] = prop["format"]
    elif kind in ("number", "integer"):
        out["type"] = kind
        for key in ("minimum", "maximum"):
            if key in prop:
                if not _is_num(prop[key]):
                    return None
                out[key] = prop[key]
    elif kind == "boolean":
        out["type"] = "boolean"
        if isinstance(prop.get("default"), bool):
            out["default"] = prop["default"]
    else:
        return None
    _kept_text(prop, out)
    return out


_TOP_LEVEL_KEYS = frozenset(
    {"type", "properties", "required", "additionalProperties", "title", "description", "$schema"}
)


def convert_schema(response_schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """JSON Schema → MCP's flat ``requestedSchema``, or ``None`` = not
    convertible (the call then ends with today's ``isError``)."""
    if not response_schema:
        return {"type": "object", "properties": {}}
    flat = flatten_schema(response_schema)
    if not isinstance(flat, dict) or flat.get("type") != "object":
        return None
    if not flat.keys() <= _TOP_LEVEL_KEYS:
        return None
    if flat.get("additionalProperties") not in (None, False):
        return None
    props = flat.get("properties", {})
    if not isinstance(props, dict):
        return None
    converted: dict[str, Any] = {}
    for name, prop in props.items():
        if not isinstance(name, str) or _SECRET_KEY.search(name):
            return None
        one = _convert_property(prop)
        if one is None:
            return None
        converted[name] = one
    out: dict[str, Any] = {"type": "object", "properties": converted}
    required = flat.get("required")
    if isinstance(required, list) and required and all(
        isinstance(r, str) and r in converted for r in required
    ):
        out["required"] = list(required)
    try:
        dumps_strict(out)
    except (ValueError, TypeError):
        return None
    return out


_DATE_TIME_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}")


def _valid_format(fmt: str, value: str) -> bool:
    try:
        if fmt == "date":
            date.fromisoformat(value)
        elif fmt == "date-time":
            if _DATE_TIME_SHAPE.match(value) is None:
                return False
            if datetime.fromisoformat(value).tzinfo is None:
                return False
        elif fmt == "email":
            local, sep, domain = value.partition("@")
            return bool(sep and local and domain and "@" not in domain)
        elif fmt == "uri":
            return bool(urlsplit(value).scheme)
    except ValueError:
        return False
    return True


def _valid_value(prop: dict[str, Any], value: Any) -> bool:
    kind = prop["type"]
    if kind == "string":
        if not isinstance(value, str):
            return False
        if "enum" in prop and value not in prop["enum"]:
            return False
        if len(value) < prop.get("minLength", 0) or len(value) > prop.get("maxLength", math.inf):
            return False
        return "format" not in prop or _valid_format(prop["format"], value)
    if kind == "boolean":
        return isinstance(value, bool)
    if not _is_num(value) or (kind == "integer" and not _is_int(value)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return prop.get("minimum", -math.inf) <= value <= prop.get("maximum", math.inf)


def validate_content(requested: dict[str, Any], content: Any) -> bool:
    """True when ``content`` satisfies every constraint ``convert_schema`` kept."""
    if not isinstance(content, dict):
        return False
    props = requested["properties"]
    if any(k not in props for k in content):
        return False
    if any(r not in content for r in requested.get("required", ())):
        return False
    return all(_valid_value(props[k], v) for k, v in content.items())


@dataclass
class _Entry:
    owner: str
    session_id: str
    call_id: str
    rpc_id: Any
    future: "asyncio.Future[dict[str, Any]]"


class PendingTable:
    """Server requests awaiting a client answer, keyed by request id.

    Sibling of C-024's single-use store, not that store: over the cap a new
    entry is refused (evicting would kill a live waiting call), expiry comes
    from the waiting call's own timeout, every removal fails the Future, and a
    binding mismatch is ignored rather than burned (ids are unguessable)."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, request_id: object) -> bool:
        return request_id in self._entries

    def add(
        self, request_id: str, owner: str, session_id: str, call_id: str, rpc_id: Any = None
    ) -> "asyncio.Future[dict[str, Any]] | None":
        if request_id in self._entries:
            return None
        if sum(1 for e in self._entries.values() if e.session_id == session_id) >= MAX_PENDING_PER_SESSION:
            return None
        future: "asyncio.Future[dict[str, Any]]" = asyncio.get_running_loop().create_future()
        future.add_done_callback(lambda f: f.cancelled() or f.exception())
        self._entries[request_id] = _Entry(owner, session_id, call_id, rpc_id, future)
        return future

    def resolve(self, request_id: Any, owner: str, session_id: str, message: dict[str, Any]) -> bool:
        entry = self._entries.get(request_id) if isinstance(request_id, str) else None
        if entry is None or entry.owner != owner or entry.session_id != session_id:
            return False
        del self._entries[request_id]
        if entry.future.done():
            return False
        entry.future.set_result(message)
        return True

    def fail(self, request_id: str, exc: Exception) -> None:
        entry = self._entries.pop(request_id, None)
        if entry is not None and not entry.future.done():
            entry.future.set_exception(exc)

    def discard(self, request_id: str) -> None:
        self._entries.pop(request_id, None)

    def fail_session(self, session_id: str, exc_type: type[Exception]) -> None:
        for rid in [r for r, e in self._entries.items() if e.session_id == session_id]:
            self.fail(rid, exc_type())

    def cancel_call(self, rpc_id: Any, owner: str, session_id: str) -> bool:
        """``notifications/cancelled`` for a waiting ``tools/call``: fail its
        entries when session, identity and the JSON-RPC id (same type, so ``1``
        never matches ``True`` or ``"1"``) all match."""
        hit = [
            rid
            for rid, e in self._entries.items()
            if e.owner == owner
            and e.session_id == session_id
            and e.rpc_id is not None
            and type(e.rpc_id) is type(rpc_id)
            and e.rpc_id == rpc_id
        ]
        for rid in hit:
            self.fail(rid, ElicitationCancelled())
        return bool(hit)

    def drop_call(self, call_id: str) -> None:
        for rid in [r for r, e in self._entries.items() if e.call_id == call_id]:
            self.fail(rid, ElicitationDisconnected())


class CallState:
    """One SSE-mode call: phase record, disconnect flag and frame hand-off."""

    def __init__(self, call_id: str, session_id: str, owner: str, version: str) -> None:
        self.call_id = call_id
        self.session_id = session_id
        self.owner = owner
        self.version = version
        self.phase = "body"
        self.tool = ""
        self.rpc_id: Any = None
        self.delivered = False
        self.disconnected = False
        self.request_id: str | None = None
        self.ended = False
        self.worker: "asyncio.Task[None] | None" = None
        self.anchor: "asyncio.Task[None] | None" = None
        self.queue: "asyncio.Queue[tuple[bytes, bool]]" = asyncio.Queue()

    def put(self, frame: bytes, *, final: bool = False) -> None:
        if not self.disconnected:
            self.queue.put_nowait((frame, final))
        elif final:
            # SI-2: tool name and phase only, never the dropped value.
            logger.info("mcp stream result dropped, client gone tool=%s phase=%s", self.tool, self.phase)
