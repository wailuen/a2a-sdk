"""DeferredResult and DeferredEvent — first-class long-running / deferred-task
delivery for tools that wrap minutes-long background jobs (GH-87).

A tool can return ``DeferredResult(handle)`` instead of an immediate result.
The runner detects this and keeps the A2A task in WORKING state while awaiting
the handle in a background asyncio.Task. When the handle resolves the runner
transitions the task to COMPLETED with a terminal artifact; on timeout it
transitions to FAILED.

The ``handle`` must be an ``Awaitable[Any]`` — typically a coroutine or a
``asyncio.Future``. Optionally, ``estimated_seconds`` gives the runner a hint
used for logging / progress; it does not affect timeout enforcement
(``tool_timeout_override`` on the ``@tool`` decorator does that).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable

from .events import LoopEvent


@dataclass(slots=True)
class DeferredResult:
    """Returned by a long-running tool to hand off execution to the runner.

    ``handle`` — an ``Awaitable[Any]`` whose resolved value becomes the
    terminal tool result (same semantics as a direct ``return``).

    ``estimated_seconds`` — optional caller hint for progress reporting; it
    does NOT control the timeout (use ``tool_timeout_override`` on the
    ``@tool`` decorator for that).
    """

    handle: Awaitable[Any]
    estimated_seconds: float | None = None


@dataclass(slots=True)
class DeferredEvent(LoopEvent):
    """Emitted by the loop when a tool returns ``DeferredResult``.

    Carries enough information for the runner to launch a background task:
    the ``DeferredResult`` itself (its ``handle`` is awaited in the
    background), plus the tool name / call identifiers needed to build the
    terminal ``ArtifactEvent`` / ``ToolResultEvent`` pair when the handle
    resolves.

    The loop does NOT emit a ``DoneEvent`` when it sees a ``DeferredEvent``
    — that is the runner's responsibility after the background task finishes.
    """

    deferred: DeferredResult
    tool_name: str
    tool_call_id: str
    emits: type | None  # ToolDecl.emits — used to decide ArtifactEvent wrapping
    timeout_seconds: float  # effective timeout for the background await
