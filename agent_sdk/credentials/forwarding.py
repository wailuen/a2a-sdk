"""Per-call credential forwarding (DESIGN.md §6.4).

A caller MAY forward upstream credentials on the ``X-Agent-Credentials``
request header so a tool's :class:`~agent_sdk.sources.SourceAdapter` resolves a
per-request value instead of the encrypted-at-rest store. This is the
multi-tenant path: an A2A/MCP orchestrator in front of the agent injects the
end-tenant's vendor key per request (Claude.ai connectors cannot send custom
headers — they fall back to the stored key; see DESIGN §6.4).

Wire format — ``X-Agent-Credentials: base64(json)`` where the JSON is
NAMESPACED to mirror the store layout::

    {"<source_name>": {"<field>": "<value>"}}   e.g. {"alphageo": {"api_key": "..."}}

The resolver checks this request-scoped context FIRST, then the store — so an
empty/absent header is exactly today's stored behavior (non-breaking).

Security invariants:
- **Fail closed.** ANY malformed/oversized/illegal envelope yields ``{}`` — no
  partial parse, never an exception to the caller, resolution simply falls back
  to the store. A tampered header is indistinguishable from an absent one.
- **Request scoped.** Held in a :class:`contextvars.ContextVar`, never on the
  adapter singleton (that would be a cross-request data race). The A2A path
  binds it before ``create_task`` (the worker snapshots the context); the MCP
  path binds it around synchronous dispatch and unbinds in ``finally``.
- **No echo.** This module never logs the header, its decoded bytes, or any
  value. The value lives only here and in the resolver return.
- **Reserved namespaces refused.** Dunder source names (the store's reserved
  auth/model namespaces, e.g. ``__bedrock__``) are rejected outright, so a
  header can never shadow auth material even though no resolver queries them.
"""

from __future__ import annotations

import base64
import binascii
import contextvars
import re
from typing import Mapping

from ..common.json_strict import loads_strict

HEADER_NAME = "X-Agent-Credentials"

# Strict envelope limits (ADR-082 parity, adapted to the namespaced shape).
_MAX_DECODED_BYTES = 16 * 1024
_MAX_FIELDS = 16  # total fields across all sources
_MAX_SOURCES = 16
_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
_MAX_VALUE_LEN = 4096
_MAX_VALUE_LEN_JWT = 8192
_JWT_FIELD = "jwt_private_key"

# {source_name: {field: value}} for the current request; empty by default so
# the resolver transparently falls back to the store.
_forwarded: contextvars.ContextVar[dict[str, dict[str, str]]] = contextvars.ContextVar(
    "agent_sdk_forwarded_credentials", default={}
)


def parse_header(raw: str | None) -> dict[str, dict[str, str]]:
    """Decode + strictly validate the ``X-Agent-Credentials`` envelope.

    Returns ``{}`` on ANY error (fail closed). Never raises; never logs the
    value. The returned mapping is safe to bind into the request context.
    """
    if not raw:
        return {}
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return {}
    if len(decoded) > _MAX_DECODED_BYTES:
        return {}
    try:
        obj = loads_strict(decoded, reject_duplicate_keys=True)
    except (ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(obj, dict) or len(obj) > _MAX_SOURCES:
        return {}

    out: dict[str, dict[str, str]] = {}
    total_fields = 0
    for source_name, fields in obj.items():
        if not isinstance(source_name, str) or not _NAME_RE.match(source_name):
            return {}
        # Dunder names are the store's reserved auth/model namespaces — a
        # header must never be able to name them.
        if source_name.startswith("__"):
            return {}
        if not isinstance(fields, dict):
            return {}
        clean: dict[str, str] = {}
        for field, value in fields.items():
            total_fields += 1
            if total_fields > _MAX_FIELDS:
                return {}
            if not isinstance(field, str) or not _NAME_RE.match(field):
                return {}
            if not isinstance(value, str):
                return {}
            cap = _MAX_VALUE_LEN_JWT if field == _JWT_FIELD else _MAX_VALUE_LEN
            if len(value) > cap:
                return {}
            clean[field] = value
        out[source_name] = clean
    return out


def bind(creds: Mapping[str, dict[str, str]]) -> contextvars.Token:
    """Install forwarded creds for the current context; returns a reset token.

    A2A: call after parsing, before ``create_task`` — the spawned worker copies
    the context and keeps the snapshot (the token is not reset; the request task
    ends and its context is discarded). MCP: pair with :func:`unbind` in a
    ``finally`` around synchronous dispatch.
    """
    return _forwarded.set(dict(creds))


def unbind(token: contextvars.Token) -> None:
    _forwarded.reset(token)


def lookup(source_name: str, field: str) -> str | None:
    """Per-request value for ``(source_name, field)`` or None. Called only by
    the per-source resolver, which exists only for non-reserved namespaces."""
    return _forwarded.get().get(source_name, {}).get(field)
