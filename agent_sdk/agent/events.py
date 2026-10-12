"""Typed loop events — the seam between the agent loop and protocol routes.

The loop yields these; each route owns a translator to its wire format
(DESIGN.md §2). The loop knows nothing about protocols; translators never
reach into the loop. ``TurnStartedEvent`` is first-class so the AG-UI STEP
translator never parses progress text for turn boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LoopEvent:
    pass


@dataclass(slots=True)
class TurnStartedEvent(LoopEvent):
    turn: int  # 1-based
    max_turns: int


@dataclass(slots=True)
class ProgressEvent(LoopEvent):
    message: str


@dataclass(slots=True)
class NoteEvent(LoopEvent):
    """Agent-side caveat surfaced to the consumer (AG-UI AGENT_NOTE)."""

    note: str


@dataclass(slots=True)
class AuditEvent(LoopEvent):
    """Internal audit record for a policy action the loop took on a tool
    call before invocation (e.g. GH-148 ``$ref`` substitution) — NEVER
    user-facing.

    Unlike ``NoteEvent``, routes never fold this into agent chat text:
    ``runner.py`` logs it and stashes ``detail`` under
    ``TaskStatusUpdateEvent.metadata["audit"]``, never ``status.message``;
    the AG-UI route emits no frame for it at all. ``detail`` carries only
    schema-declared identifiers (tool/field names, kinds) — never a resolved
    value or label (SI-2).
    """

    code: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolProgressEvent(LoopEvent):
    """Interim progress notification yielded by an async-generator tool (GH-88).

    Generator tools may yield ``ToolProgressEvent`` instances during a
    long-running call; the loop forwards each one downstream before the
    terminal result.  A2A consumers see ``TaskStatusUpdateEvent{state:"working",
    final:false}``; AG-UI consumers see a ``CUSTOM`` frame with
    ``name="TOOL_PROGRESS"``.
    """

    message: str
    tool_name: str


@dataclass(slots=True)
class ToolCallEvent(LoopEvent):
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ToolResultEvent(LoopEvent):
    tool_call_id: str
    tool_name: str
    ok: bool
    result: Any = None
    error: str | None = None  # human-safe message; never an AgentError object


@dataclass(slots=True)
class TextEvent(LoopEvent):
    """A completed assistant text segment (Bedrock Converse is non-streaming)."""

    text: str


@dataclass(slots=True)
class ArtifactEvent(LoopEvent):
    """A structured artifact produced by a tool.

    ``model`` is a content-type model instance (Standard Profile or registered
    domain type); ``data_type`` is its snake_case identifier.
    """

    data_type: str
    tool_name: str
    model: Any


@dataclass(slots=True)
class UsageEvent(LoopEvent):
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class InterruptEvent(LoopEvent):
    """Loop pauses for input (action_gate). Routes map this to
    input-required (A2A) / RUN_FINISHED interrupt outcome (AG-UI)."""

    interrupt_id: str
    reason: str
    message: str
    response_schema: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str | None = None
    # Seconds remaining until the interrupt expires (relative, clock-agnostic —
    # NOT a raw TaskStore.clock() reading; see TaskStore.interrupt_ttl_remaining).
    expires_in: float | None = None


@dataclass(slots=True)
class DoneEvent(LoopEvent):
    ok: bool = True
    error: str | None = None  # human-safe message; never an AgentError object
    # GH-155: user-facing summary/notice of a cap-exit failure (also streamed as TextEvent)
    summary: str | None = None
