"""Request-scoped caller identity (GH-185).

``require_identity`` resolves the caller at the route; this module carries that
frozen :class:`Identity` into the worker task, the loop and MCP ``tools/call``
so a tool or SourceAdapter can attribute usage or scope data per user.

Same binding pattern as ``credentials.forwarding``: A2A/AG-UI bind before
``create_task`` (the worker snapshots the context); MCP binds around dispatch
and unbinds in ``finally``. Only the ``Identity`` is held, never tokens, raw
headers or credentials, and this module never logs it (SI-2).
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any

from .identity import Identity

_current: contextvars.ContextVar[Identity | None] = contextvars.ContextVar(
    "agent_sdk_current_identity", default=None
)


def current_identity() -> Identity | None:
    """The caller's identity for this request, or None outside a request."""
    return _current.get()


def bind_identity(identity: Identity) -> contextvars.Token:
    return _current.set(identity)


def unbind_identity(token: contextvars.Token) -> None:
    _current.reset(token)


@dataclass(frozen=True)
class ResumeEnvelope:
    """Resume value plus the resuming caller, delivered atomically through the
    resume future so a losing concurrent resumer can never overwrite it."""

    value: Any
    identity: Identity
    accepted_output_modes: list[str] | None = None
