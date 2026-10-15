"""Tool-use loop (DESIGN.md §8) — protocol-agnostic async generator.

Yields the typed events in ``events.py``; the A2A/AG-UI route layers own the
wire mapping. Policies enforced here, not in routes:

- max turns (default 20)
- per-tool timeout: Tier 1 = 130s, Tier 2 = 180s
- per-task wall-clock deadline (default 600s) — SUSPENDED while the task
  waits in an interrupt state; the interrupted-task TTL (§5.2) owns that
  period instead
- cumulative token budget across resume cycles (it guards spend; resumes
  don't reset it) — pass prior spend back in via ``spent_tokens``
- task-local result cache (identical tool call → cached result, no re-invoke)
- AgentError from a tool becomes a tool result, never a crash
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Sequence,
    TypeGuard,
    Union,
    get_args,
    get_origin,
)

logger = logging.getLogger(__name__)

from pydantic import BaseModel, ValidationError
from pydantic_core import to_jsonable_python

from ..common.redact import frame_locations
from ..common.redact import sanitize_text
from ..models.content_types import TRANSCRIPT_DUMP_CONTEXT
from ..models.errors import AgentError
from .deferred import DeferredEvent, DeferredResult
from .events import (
    ArtifactEvent,
    AuditEvent,
    DoneEvent,
    InterruptEvent,
    LoopEvent,
    TextEvent,
    ToolCallEvent,
    ToolProgressEvent,
    ToolResultEvent,
    TurnStartedEvent,
    UsageEvent,
)
from .model_client import ModelClient
from .registry import ToolEntry, ToolInputValidationError, ToolRegistry, ToolTerminalResult
from .reuse import (
    RESOLVED_MARKER_KEY,
    Reusable,
    index_entry_key,
    resolve_reuse_fields,
    scan_resolved,
)
from .skills import SkillsRegistry
from ..sources import SourceAdapter

TIER_TIMEOUTS = {1: 130.0, 2: 180.0}
LOAD_SKILL_TOOL = "load_skill"
DEFAULT_MAX_OUTPUT_TOKENS = 8192

# SI-2 control-char stripping + length cap for model-supplied names lives in
# ONE place: agent_sdk.common.redact.sanitize_text (component C-007). This
# module previously carried a byte-identical private copy
# (`_CONTROL_CHAR_MAP` + `_sanitize_model_name`); it was deleted when C-007
# landed so the two cannot drift apart on the control-char set or the cap.
# sanitize_text's default max_len is 64 — the cap the old copy hard-coded.


# RT-007 (debug round 6): ONE definition of "this message's ``content`` is a
# sequence of content blocks", shared by all four of this module's tail/content
# helpers (``close_dangling_tool_use``, ``is_user_turn_boundary``,
# ``bridge_context_messages``, ``append_assistant_turn``).
#
# They disagreed before this existed. ``close_dangling_tool_use`` accepted
# ``(list, tuple)``; the other three tested ``isinstance(content, list)`` alone,
# so a tuple — the ordinary shape a durable ``TaskStore`` subclass produces when
# it round-trips a transcript through a serializer that emits immutable
# sequences — fell down each one's SCALAR branch. The results were not
# cosmetic: ``bridge_context_messages`` stringified a tuple of ``toolResult``
# blocks into ``{"text": "({'toolResult': ...},)"}``, turning structured tool
# output into user prose the model reads back as if the user had typed a Python
# repr; ``append_assistant_turn`` did the same to a tuple assistant tail,
# breaking its own docstring promise to preserve "whatever real content that
# tail carried"; and ``is_user_turn_boundary`` read a tuple-content
# ``toolResult`` orphan as "not a list, therefore no toolResult, therefore a
# legal conversation head", admitting exactly the head shape
# ``bridge_context_messages`` trims for.
#
# A tuple is a sequence of content blocks in every sense that matters here, so
# it is normalised to a list rather than wrapped as text. ``str``/``bytes`` are
# excluded deliberately: they are iterable but are scalar TEXT, and are the one
# shape the wrap branch genuinely exists for.
CONTENT_SEQUENCE_TYPES = (list, tuple)


def is_content_sequence(content: Any) -> TypeGuard[list[Any] | tuple[Any, ...]]:
    """Is ``content`` a sequence of Converse content blocks (as opposed to
    scalar text, or nothing at all)? See ``CONTENT_SEQUENCE_TYPES`` above.

    DBG-7: annotated ``TypeGuard``, not ``bool``. Every call site below reads
    ``content`` straight out of a ``dict.get()`` — i.e. ``Any | None`` — and
    then iterates or unpacks it on the strength of this check. When this
    centralising helper replaced the inline ``isinstance`` calls it also
    replaced the NARROWING those calls carried, so the four call sites started
    failing type checking (``union-attr`` on the iteration, ``misc`` on the
    star-unpack) even though the runtime behaviour was unchanged. A predicate
    extracted purely so several call sites can share one isinstance test has to
    carry that test's narrowing with it, or it is not a drop-in replacement.
    """
    return isinstance(content, CONTENT_SEQUENCE_TYPES)


class DanglingToolUseUnreadable(Exception):
    """RT-004 (``agent/runner.py`` review): raised by ``close_dangling_tool_use``
    when ``messages[-1]`` is unambiguously an assistant turn whose dangling
    ``toolUse`` shape cannot be reliably parsed into a ``toolUseId`` to
    repair against — a non-list ``content``, a ``toolUse``-keyed block whose
    value is not a dict, or one missing ``toolUseId``.

    This is deliberately NOT the same outcome as ``close_dangling_tool_use``
    returning ``False``. ``False`` means the tail is CONFIRMED clean — not an
    assistant/``toolUse`` turn at all, or an assistant turn whose blocks carry
    no ``toolUse`` key whatsoever — and is safe to treat as a no-op. This
    exception means the tail's shape says a dangling tool call is (or may be)
    present but this function could not close it out. A caller that catches
    ``Exception`` broadly and reports "not safe to persist" (``agent/runner.py``
    ``repair_dangling_tool_use_safe``) handles this correctly already; a
    caller that let a prior "hardening" fix silently return ``False`` here
    instead turned that fail-closed persist gate into a fail-open one — the
    exact regression this type exists to prevent from recurring.
    """


class ToolInterrupt(Exception):
    """Raised by a tool to pause the task (input-required / auth-required).

    ``resume_handler``, when set, receives the user's resume value and its
    return becomes the tool result (the contrib action_gate "confirmed
    execution" path). Without it, the raw resume value is folded back to
    the model as the tool result.
    """

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        response_schema: dict[str, Any] | None = None,
        resume_handler: Callable[[Any], Awaitable[Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.response_schema = response_schema
        self.resume_handler = resume_handler


@dataclass(slots=True)
class LoopPolicies:
    max_turns: int = 20
    deadline_seconds: float = 600.0
    token_budget: int = 200_000
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    tool_timeouts: dict[int, float] = field(default_factory=lambda: dict(TIER_TIMEOUTS))
    # GH-87: per-tool timeout override map (tool name → seconds).
    # Entries here take precedence over ``tool_timeouts`` (tier-based defaults).
    # Populated automatically from ToolDecl.tool_timeout_override at invocation
    # time; callers may also pass explicit overrides for testing.
    per_tool_timeouts: dict[str, float] = field(default_factory=dict)
    # RT-C-001/RT-002: ReuseKind bounded-recovery budget (agent/reuse.py's
    # MAX_CONSECUTIVE_REUSE_REJECTIONS is a suggested starting value an
    # operator may opt into, not an enforced ceiling — nothing clamps this
    # field to it) — the number of consecutive rejections of the
    # exact SAME raw value on the same (tool, field) before
    # resolve_reuse_fields grants a forced passthrough instead of rejecting
    # again. RT-002: defaults to 0 — reject-forever — because the GH-148
    # gate this budget lives inside of is a correctness gate (DESIGN.md
    # §8.1 states its guarantee as "the exact GH-148 substitution bug, now
    # caught instead of silently executed"); a correctness gate must never
    # default to fail-open. An operator who needs the liveness fallback
    # (a stuck retry loop on one identical wrong value would otherwise run
    # until max_turns) opts IN by setting this to a positive value — the
    # SAME opt-in shape as ReuseKind's own `strict`/`allow_raw_override`
    # flags — never the other way around.
    reuse_forced_passthrough_limit: int = 0
    # GH-155 (maintainer ruling 2026-10-11): on the max-turns / token-budget
    # exits make ONE tools-disabled model call so the user gets an answer
    # from what was gathered; only if that call fails (raises, or returns no
    # usable text) is the fixed SDK notice sent. The run still ends ok=False.
    # ``final_summary_max_tokens`` is that call's OUTPUT cap only (also
    # bounded by ``max_output_tokens``); it is not a spend allowance. The
    # cost of a cap exit is therefore bounded by exactly one extra call
    # whose output is at most this many tokens; its input is the transcript
    # re-send, the same size the next turn would have sent. 0 disables the
    # call (notice only).
    final_summary: bool = True
    final_summary_max_tokens: int = 1024


def resolve_tool_timeout(name: str, entry: ToolEntry, policies: LoopPolicies) -> float:
    """Effective per-call timeout (seconds) for one tool invocation.

    Shared by every invocation surface (``agent/loop.py``, ``routes/mcp.py``)
    so the resolution order can never drift between them (LRN-116 Prevention).
    Priority order:
      1. ``policies.per_tool_timeouts[name]`` (explicit caller override)
      2. ``entry.decl.tool_timeout_override`` (``@tool`` decorator kwarg)
      3. ``policies.tool_timeouts[tier]`` (tier default)
      4. ``TIER_TIMEOUTS[2]`` (hard fallback)
    """
    if name in policies.per_tool_timeouts:
        return policies.per_tool_timeouts[name]
    if entry.decl.tool_timeout_override is not None:
        return entry.decl.tool_timeout_override
    return policies.tool_timeouts.get(entry.tier, TIER_TIMEOUTS[2])


class Deadline:
    """Wall-clock budget that suspends while interrupted (§8)."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._seconds = seconds
        self._clock = clock
        self._started = clock()
        self._consumed_before_suspend = 0.0
        self._suspended = False

    def suspend(self) -> None:
        if not self._suspended:
            self._consumed_before_suspend += self._clock() - self._started
            self._suspended = True

    def resume(self) -> None:
        if self._suspended:
            self._started = self._clock()
            self._suspended = False

    def consumed(self) -> float:
        if self._suspended:
            return self._consumed_before_suspend
        return self._consumed_before_suspend + (self._clock() - self._started)

    def exceeded(self) -> bool:
        return self.consumed() > self._seconds


def fold_result_content(result: Any) -> dict[str, Any]:
    """toolResult content block for the Converse API.

    Shared with ``agent/runner.py``'s deferred (GH-87) background awaiter
    (RT-004) so a deferred tool's terminal ``toolResult`` message is folded
    from the exact same content-shaping rule as every synchronous tool call.

    RT-001 (GH-148 follow-up, control-plane isolation): strips a top-level
    ``__resolved__`` key from a dict result or a BaseModel dump before
    folding. ``__resolved__`` is the SDK's OWN reuse-marker namespace
    (``reuse.RESOLVED_MARKER_KEY``, consumed by ``scan_resolved``) — the
    genuine marker is always appended as a SEPARATE content block, built
    directly (``{"json": {RESOLVED_MARKER_KEY: resolved_marker}}`` below and
    in ``runner.py``'s deferred awaiter), never through this function.
    Without the strip, a tool that relays upstream JSON verbatim (the normal
    shape for a tool wrapping an API response) could return a dict carrying
    its own ``__resolved__`` key — folded here as ordinary tool output —
    which ``scan_resolved`` could not distinguish from a real marker,
    letting attacker/upstream data forge a resolution and steer which value
    a later ``$ref:<kind>``/raw-value call substitutes. A tool has no
    legitimate reason to name a top-level field ``__resolved__``, so this
    drops the key rather than renaming it.
    """
    if isinstance(result, BaseModel):
        dump = result.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            context={TRANSCRIPT_DUMP_CONTEXT: True},
        )
        # RT-A-04: model_dump() is not guaranteed to return a dict — a
        # RootModel or a custom @model_serializer can legitimately dump to a
        # list or a scalar. Only a dict dump can carry a forged
        # RESOLVED_MARKER_KEY (SI-2 threat this strip guards against), so
        # only pop from one; a non-dict dump is wrapped exactly like the
        # plain-list branch below (a JSON array is a legal Converse
        # toolResult `json` document) instead of crashing on `.pop`.
        if isinstance(dump, dict):
            dump.pop(RESOLVED_MARKER_KEY, None)
            return {"json": dump}
        return {"json": {"result": dump}}
    if isinstance(result, list):
        return {"json": {"result": result}}
    if isinstance(result, dict):
        if RESOLVED_MARKER_KEY in result:
            result = {k: v for k, v in result.items() if k != RESOLVED_MARKER_KEY}
        return {"json": result}
    return {"text": "" if result is None else str(result)}


def jsonable_reuse_value(value: Any) -> Any:
    """JSON-safe form of a ``Reusable.value`` for the ``__resolved__`` marker
    folded into ``messages`` (RT-005 / RT-002). ``Reusable.value`` is typed
    ``Any`` — a tool may wrap anything in it, not just a ``BaseModel``
    (``ToolDecl.emits`` matching is checked against the unwrapped value): a
    ``UUID``, ``datetime``, ``Decimal``, ``Enum``, a dataclass, or any other
    domain object. A ``BaseModel``-only guard leaves every one of those to be
    planted raw into the marker and crash ``json.dumps`` on the very next
    model call — the exact failure this function exists to prevent — so this
    applies the same *total* JSON-safe rule ``fold_result_content`` applies
    to a tool's raw result, via pydantic's own jsonable-python conversion
    (natively normalizes ``BaseModel``, dataclasses, ``UUID``, ``datetime``,
    ``Decimal``, ``Enum``, etc., matching ``fold_result_content``'s
    ``by_alias``/``exclude_none`` BaseModel dump), with any remaining
    genuinely unknown type stringified rather than raising.

    Shared with ``agent/runner.py``'s deferred (GH-87) background awaiter
    (RT-001, cross-surface parity with this synchronous branch) so a
    ``Reusable`` resolved via a ``DeferredResult`` handle folds the identical
    JSON-safe ``__resolved__`` marker value."""
    return to_jsonable_python(value, exclude_none=True, fallback=str)


# GH-147 AC3: fixed, SDK-authored — never derived from model/tool output
# (SI-2). Folded in as a synthetic assistant turn only to keep the stored
# transcript alternating; replayed back to the model as ordinary context on
# contextId continuation, never surfaced to the end user (record.messages is
# separate from task.history / the A2A status message).
_TRAILING_USER_BRIDGE_TEXT = "(no response)"


def bridge_trailing_user(messages: list[dict[str, Any]], text: str | None = None) -> None:
    """RT-001 (GH-147 AC3): ``record.messages`` must never end on a ``user``
    message at any run_loop exit. contextId continuation replays the most
    recent terminal task's messages verbatim and then appends a new ``user``
    turn (routes/a2a.py::_create_task_record) — two consecutive ``user``
    messages is rejected outright by Bedrock's Converse API. FAILED is a
    terminal state too, so every ok=False exit is just as reachable via
    continuation as the happy-path completion.

    RT-008: ``text`` defaults to ``_TRAILING_USER_BRIDGE_TEXT`` ("(no
    response)"), correct for every exit where the model genuinely produced
    nothing. A caller whose bridged turn followed something that DID
    succeed (e.g. a deferred GH-87 tool completing in the background) must
    pass its own fixed, SDK-authored string instead — never derived from
    model/tool output (SI-2) — so the replayed transcript doesn't claim the
    model produced no response when it actually did.

    A trailing ``user`` message here is always the toolResult fold from a
    completed tool round (``messages.append({"role": "user", ...})`` below)
    or the very first turn's inbound user message — never mid-round, since
    every exit point this guards runs at a turn boundary. Call before every
    ``DoneEvent``/``return`` out of ``run_loop`` (deadline, token budget,
    max-turns, an upstream ``AgentError``) and on the no-tool-call branch
    when there is no text to fold instead.

    RT-004 (GH-147 AC3, out-of-loop callers): ``run_loop`` itself only
    guards its OWN exit points — a ``DeferredEvent`` handoff (GH-87) returns
    without reaching any of them, and ``record.messages`` is then repaired
    later by code that never re-enters ``run_loop`` at all. Exported
    (mirroring ``fold_result_content``'s identical RT-004 promotion) so
    ``runner.py``'s ``repair_dangling_tool_use`` — the one shared helper
    every out-of-loop writer of ``record.messages`` calls (its own COMPLETED
    and FAILED paths in ``_run_deferred_background``; ``routes/a2a.py``'s
    ``tasks_cancel``; and ``run_task_worker``'s own terminal
    ``except AgentError`` / ``except Exception`` handlers, RT-A-002 — those
    two were NOT covered until RT-A-002, despite this paragraph's prior
    "every ... caller" claim: they set the task FAILED and published the
    terminal frame without calling ``repair_dangling_tool_use`` at all,
    reachable mid-turn via e.g. ``store.mark_interrupted``'s §5.2 cap raising
    ``AgentError``, or ``build_artifact`` raising from inside the
    per-tool-call loop) — can call this bridge itself immediately after
    appending its synthetic ``toolResult``, covering every current and
    future caller from one place instead of requiring each to remember its
    own follow-up call.

    RT-B-008 (``agent/runner.py::repair_dangling_tool_use``): guards the tail
    read with ``isinstance(messages[-1], dict)`` — this function is called
    unconditionally by that helper (after its own, identically-guarded tail
    check), so a non-dict tail entry reaching THIS read would otherwise still
    raise ``AttributeError`` here even once the caller's own read is guarded.
    """
    if messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "user":
        messages.append(
            {"role": "assistant", "content": [{"text": text or _TRAILING_USER_BRIDGE_TEXT}]}
        )


# RT-004 (debug round 4): fixed, SDK-authored (SI-2). Reported on the
# DoneEvent when ``run_loop`` stops because another owner already committed
# the task terminal. ``run_task_worker``'s own terminal guard drops this
# event before it can reach a stream, so it exists to keep run_loop's
# "always terminates with a DoneEvent" contract, not to be shown to a user.
_SEALED_TRANSCRIPT_ERROR = "task was already terminated by another owner"

_FINAL_SUMMARY_INSTRUCTION = (
    "You have reached the limit for this task and can call no more tools. "
    "Using only what you have gathered so far, write a short final answer for "
    "the user. Say clearly what is still missing or uncertain."
)
_FINAL_SUMMARY_NOTICE_TURNS = (
    "I reached my step limit before finishing. The work so far may be "
    "incomplete. Please try again with a narrower request."
)
_FINAL_SUMMARY_NOTICE_BUDGET = (
    "I reached my budget limit before finishing. The work so far may be "
    "incomplete. Please try again with a narrower request."
)


def _summary_request_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy of ``messages`` whose trailing user turn also carries the summarize
    instruction (never two same-role messages in a row). The real transcript is
    left untouched so the instruction is never persisted."""
    tail = messages[-1] if messages else None
    if isinstance(tail, dict) and tail.get("role") == "user":
        content = tail.get("content")
        blocks = list(content) if isinstance(content, list) else (
            [{"text": str(content)}] if content else []
        )
        blocks.append({"text": _FINAL_SUMMARY_INSTRUCTION})
        return [*messages[:-1], {**tail, "content": blocks}]
    return [*messages, {"role": "user", "content": [{"text": _FINAL_SUMMARY_INSTRUCTION}]}]


def _summary_max_tokens(policies: LoopPolicies) -> int:
    """GH-155: output cap for the summary call at a cap exit. 0 means: skip it
    and send the fixed notice. Per the maintainer ruling the cap bounds the
    summary's OUTPUT only — the re-sent transcript is not charged against it,
    so the summary is reachable on the token-budget exit, not just max-turns."""
    return max(min(policies.final_summary_max_tokens, policies.max_output_tokens), 0)


async def _final_summary(
    *,
    model: ModelClient,
    system: str,
    messages: list[dict[str, Any]],
    tool_specs: list[dict[str, Any]],
    policies: LoopPolicies,
    max_tokens: int,
    notice: str,
    is_sealed: Callable[[], bool],
) -> AsyncIterator[LoopEvent]:
    """GH-155: one tools-disabled call at a cap exit. Yields TextEvent (+
    UsageEvent) and folds the reply into ``messages``; on any failure or an
    unusable reply yields the fixed SDK ``notice`` and only bridges the
    transcript. Nothing is yielded or folded if the task was sealed during the
    await — the caller re-checks ``is_sealed()``. The notice never carries
    provider text (SI-2)."""
    if not policies.final_summary:
        bridge_trailing_user(messages)
        return
    segments: list[str] = []
    if max_tokens > 0:
        try:
            response = await model.converse(
                system=system,
                messages=_summary_request_messages(messages),
                tools=tool_specs,
                max_tokens=max_tokens,
                tool_choice="none",
            )
        except Exception as exc:
            logger.warning(
                "final summary call failed error_type=%s frames=%s",
                type(exc).__name__, frame_locations(exc),
            )
            response = None
        if is_sealed():
            return
        if response is not None:
            yield UsageEvent(
                input_tokens=response.input_tokens, output_tokens=response.output_tokens
            )
            segments = [seg for seg in response.text_segments if seg.strip()]
    if segments:
        yield TextEvent(text="\n\n".join(segments))
        append_assistant_turn(messages, [{"text": seg} for seg in segments])
        return
    yield TextEvent(text=notice)
    bridge_trailing_user(messages)


# RT-003 (debug round 4): fixed, SDK-authored — never derived from model or
# tool output (SI-2). Closes a dangling assistant ``toolUse`` tail found on a
# transcript read back OUT of a ``TaskStore``, where the real result is
# unknowable by definition: whatever produced it is gone.
_STALE_TOOL_RESULT_TEXT = (
    "tool call result unavailable: the prior task ended before a result was recorded"
)


def close_dangling_tool_use(
    messages: list[dict[str, Any]],
    *,
    default_content: list[dict[str, Any]],
    default_status: str = "error",
    resolved: dict[str, tuple[list[dict[str, Any]], str]] | None = None,
) -> bool:
    """C-018's fold rule, as ONE shared implementation: if ``messages`` ends on
    an assistant turn carrying ``toolUse`` blocks with no matching
    ``toolResult``, append the synthetic ``user``/``toolResult`` turn that
    closes it. Returns whether it appended anything.

    Bedrock's Converse API rejects a transcript whose assistant ``toolUse``
    has no answering ``toolResult`` outright, so this shape must never reach a
    model — and it is produced on every mid-turn exit (``run_loop`` folds the
    assistant ``toolUse`` message BEFORE running the turn's per-tool-call
    loop, and appends the matching ``toolResult`` only once every call in the
    turn has finished).

    RT-003 (debug round 4): extracted from
    ``agent/runner.py::repair_dangling_tool_use`` so the WRITE side (that
    function, closing the tail it is about to persist) and the READ side
    (``bridge_context_messages`` below, re-asserting the invariant on a
    transcript a ``TaskStore`` subclass handed back) share one rule instead of
    keeping two copies that can drift. Lives here rather than in ``runner.py``
    because ``runner.py`` already imports from this module and the reverse
    would be circular.

    ``resolved`` maps a ``toolUseId`` to the ``(content, status)`` actually
    known for it — the write side passes this turn's completed sibling results
    (``record.pending_tool_results``) merged under any explicit caller
    overrides. Any id not in it falls back to ``default_content`` /
    ``default_status``. The read side has no such knowledge and passes nothing.

    Each block DEEP-copies its content (RT-B-007/RT-B-206): several dangling
    ids in one turn can otherwise share the same list object AND the same
    inner dicts, so one later mutation by the caller or a store's serializer
    would silently rewrite every entry at once.

    RT-B-008: a non-dict tail entry — reachable from a durable store
    deserialising loosely — degrades to "nothing to repair" (``False``)
    rather than raising, since a non-dict tail can't even be confirmed to be
    an assistant turn, let alone a dangling one.

    RT-004 (correction to an intermediate RT-001 "hardening" that regressed
    this): ONE level deeper — the tail message IS confirmed to be an
    assistant dict — a non-list ``content``, or a block carrying a
    ``"toolUse"`` key whose value is not a dict or is missing
    ``"toolUseId"``, is NOT treated the same as "nothing to repair" anymore.
    That prior degrade-to-``False`` made this function indistinguishable
    from a genuinely clean tail to every caller, which let
    ``repair_dangling_tool_use_safe`` report a still-dangling, unrepaired
    transcript as safe to persist — the exact fail-open its own gate exists
    to prevent (see ``DanglingToolUseUnreadable``'s docstring). Each such
    case now raises ``DanglingToolUseUnreadable`` instead: the WRITE side
    (``repair_dangling_tool_use``) lets it propagate up to
    ``repair_dangling_tool_use_safe``'s existing broad ``except Exception``,
    which already reports "not safe to persist" for any in-memory repair
    failure; the READ side (``bridge_context_messages`` below) catches it
    and drops the unreadable tail rather than crashing the caller building a
    fresh task record. A content block with no ``"toolUse"`` key at all
    (ordinary text) is unambiguous and still silently skipped — only a block
    that IS shaped like an attempted ``toolUse`` but can't be read is
    unreadable.

    RT-006 (debug round 4, correction to the RT-004 paragraph above): "not a
    list" is NOT the same question as "could be carrying a ``toolUse`` claim
    I can't read", and conflating the two made this the only one of this
    module's three tail-shape helpers to call a plain-text assistant tail
    unreadable. ``is_user_turn_boundary`` below already reads a non-list
    ``content`` as text ("no ``toolResult`` block, therefore a boundary"),
    and ``append_assistant_turn`` below already preserves one by wrapping it
    into a single ``{"text": ...}`` block — both because a ``str`` (or a
    missing/empty value) provably cannot contain a ``toolUse`` block at all.
    Raising on that shape was a FALSE unreadable: it propagated through
    ``repair_dangling_tool_use_safe`` into ``set_task_status(...,
    repaired=False)``, which skips BOTH ``persist_messages`` and
    ``persist_status``, so a durable store never observed the terminal
    transition of a task whose transcript was never dangling — permanently,
    and for e.g. any AG-UI ``_fold_history`` transcript ending on a
    client-resubmitted assistant text turn. A ``str``/``bytes`` or falsy
    ``content`` is therefore "nothing to repair" (``False``) now, agreeing
    with the other two helpers. Every OTHER non-list shape — a bare ``dict``
    such as ``{"toolUse": {...}}`` from a store deserialising loosely, or any
    other object — still raises: those CAN be an attempted ``toolUse`` claim,
    and calling one text would be the fail-open this gate exists to prevent.
    """
    if not messages:
        return False
    tail = messages[-1]
    if not isinstance(tail, dict):
        # RT-005: a non-empty tail that isn't even a dict can't be confirmed
        # clean — it might be an unreadably-serialised assistant toolUse
        # turn — so this degrades to "nothing to repair" no longer; see the
        # RT-B-008/RT-004 docstring paragraphs above for the two narrower
        # shapes (falsy/non-list content) that still correctly return False.
        raise DanglingToolUseUnreadable("tail message is not a dict")
    if tail.get("role") != "assistant":
        return False
    last_content = tail.get("content")
    if isinstance(last_content, (str, bytes)) or not last_content:
        # Provably carries no toolUse block: plain text, or nothing at all.
        return False
    if not is_content_sequence(last_content):
        raise DanglingToolUseUnreadable("assistant tail message content is not a list")
    tool_use_ids: list[str] = []
    for block in last_content:
        if not (isinstance(block, dict) and "toolUse" in block):
            continue
        tool_use = block["toolUse"]
        if not (isinstance(tool_use, dict) and "toolUseId" in tool_use):
            raise DanglingToolUseUnreadable("assistant tail message has a malformed toolUse block")
        tool_use_ids.append(tool_use["toolUseId"])
    if not tool_use_ids:
        return False
    resolved = resolved or {}
    result_blocks: list[dict[str, Any]] = []
    for tool_use_id in tool_use_ids:
        content, status = resolved.get(tool_use_id, (default_content, default_status))
        result_blocks.append(
            {
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": copy.deepcopy(content),
                    "status": status,
                }
            }
        )
    messages.append({"role": "user", "content": result_blocks})
    return True


def is_user_turn_boundary(msg: Any) -> bool:
    """Is ``msg`` a genuine user-authored turn — the only message shape that
    may legally HEAD a Bedrock Converse conversation?

    True for a ``role == "user"`` message carrying no ``toolResult`` block;
    only a continuation of an in-flight tool round carries one. Guarded the
    same way ``close_dangling_tool_use`` guards a loosely deserialised store
    record: a non-dict message or non-list ``content`` never raises here, it
    just fails the predicate.

    RT-004 (debug round 5): ONE implementation, C-017-registered, for both
    halves of a single invariant — the WRITE/read-repair side here
    (``bridge_context_messages``'s head trim) and the READ/cap side
    (``tasks/memory.py::_turn_boundary_slice``, which imports this name for
    the new head a cap introduces). It also matches the shape
    ``routes/ag_ui.py::_fold_history``'s leading-prefix strip enforces for the
    AG-UI carrier. It existed as two byte-equivalent private copies, one per
    module, each docstring naming the other instead of importing it — the same
    duplication ``close_dangling_tool_use`` was extracted to end. Two copies
    are exactly what lets a change to the boundary rule desync a capped
    window's head from the read-side head repair.
    """
    if not (isinstance(msg, dict) and msg.get("role") == "user"):
        return False
    content = msg.get("content")
    # RT-007 (debug round 6): a TUPLE of content blocks is scanned for a
    # toolResult exactly like a list. Testing `isinstance(content, list)` alone
    # made a tuple-content toolResult orphan answer True here — "not a list,
    # therefore carries no toolResult, therefore a legal head" — which is the
    # one shape this predicate exists to reject. See CONTENT_SEQUENCE_TYPES.
    if not is_content_sequence(content):
        return True
    return not any(isinstance(block, dict) and "toolResult" in block for block in content)


def bridge_context_messages(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """``TaskStore.context_messages()`` consumption helper (LRN-144/RT-B-202).

    ``context_messages()`` is a non-abstract, overridable ``TaskStore`` ABC
    method (C-005, tasks/store.py) — its whole reason to exist is external
    durable subclasses. Every ``run_loop`` writer bridges its own exit
    (``bridge_trailing_user``, above) so ``record.messages`` never ends on
    ``user``, but a store override — an AzureTableTaskStore-shaped store, or
    any record persisted before GH-147's writer-side guards existed — can
    return a transcript that already ends on ``user``. ``routes/a2a.py``'s
    ``_create_task_record`` is the one consumption site of that data and
    must re-assert the invariant on read rather than trust the writers that
    produced it — but must never call ``bridge_trailing_user`` itself:
    LRN-144's Check requires that bridge to have exactly one call site,
    inside ``agent/runner.py::repair_dangling_tool_use``. Route the
    re-assertion through here instead, so routes/a2a.py stays at zero direct
    ``bridge_trailing_user`` calls.

    RT-003 (debug round 4, corrected): re-asserts THREE transcript invariants
    a store override can break — the docstring previously claimed "BOTH",
    but only ever enumerated the tail ones. Ending on ``user`` was only part
    of it: ``TaskStore.persist_messages``'s own docstring (RT-B-205,
    tasks/store.py) documents that the SDK deliberately flushes a transcript
    "GUARANTEED to end on a dangling assistant ``toolUse`` with no matching
    ``toolResult``" into durable storage on every ``INTERRUPT_STATES``
    transition, and an in-memory repair that failed
    (``repair_dangling_tool_use_safe`` returning False) leaves a TERMINAL
    record in the same shape. A durable subclass whose own
    resume-after-restart path later marks such a task terminal, or one that
    overrode ``context_messages`` without the repair, hands
    ``_create_task_record`` exactly the shape this route already decided it
    cannot trust — and it would be folded straight into the new task's
    ``record.messages`` and sent to Bedrock's Converse API, which rejects it
    outright.

    A third, HEAD-shaped break survives both of those tail re-assertions
    untouched: a leading ``user``/``toolResult`` orphan whose matching
    ``toolUse`` was truncated away by the store's own windowing (exactly the
    shape ``TaskStore.context_messages()``'s own docstring, RT-007, makes a
    concrete store responsible for never producing — nothing on this read
    side enforced it), or a leading ``assistant`` message (the shape
    ``routes/ag_ui.py::_fold_history`` already strips for the AG-UI carrier
    but which had no A2A equivalent). Drop leading messages via
    ``is_user_turn_boundary`` above — the same predicate
    ``tasks/memory.py::_turn_boundary_slice`` uses for a capped window's new
    head — FIRST, before either tail re-assertion: a store's window can be
    both truncated AND end on a dangling tail in the same broken record, and
    trimming the head first means the tail check below always sees this
    transcript's genuine trailing shape, never a truncated-head artifact of
    it. Then close the dangling tail (``close_dangling_tool_use`` above,
    C-018's one shared fold rule — not a second inline copy), then bridge, in
    exactly the order ``repair_dangling_tool_use`` uses.

    Returns a NEW list (never mutates ``messages`` in place — a ``Sequence``
    may be immutable, e.g. a tuple returned by a durable subclass) with all
    three re-assertions already applied, ready to extend into a fresh
    ``record.messages``. Every element is DEEP-COPIED (see the RT-006/RT-008
    paragraph below), so the caller's element dicts are never touched either.
    Can return an empty list — when ``messages`` is empty to begin with, when
    every message is dropped by the content-coercion step below for carrying
    no content at all, or when NO message in it can legally head a
    conversation (DBG-5 below).

    DBG-5 (debug round 5, correcting round 4's RT-007): the head trim is
    UNCONDITIONAL — it pops until the head is Converse-legal, even if that
    empties the list. Round 4 guarded the pop loop behind "only if a genuine
    boundary exists somewhere to trim toward", borrowing
    ``_turn_boundary_slice``'s "capping must never rewrite a transcript it
    didn't need to shrink" rule. That rule does not transfer: it is a CAP
    rule, and the case it protects (``len(messages) <= cap``) always has a
    legal head already — the task's own seed user turn from
    ``_create_task_record``. This function is a REPAIR rule, and its
    no-boundary-anywhere case is by definition the one where the head is
    broken, so the guard disabled the repair in exactly the situation it
    exists for: ``[user(toolResult orphan), assistant(...)]`` kept an orphan
    at index 0, and ``[assistant(toolUse), user(toolResult)]`` kept an
    assistant message as the head. Both are folded verbatim into the new
    task's ``record.messages`` by ``routes/a2a.py::_create_task_record`` and
    handed to Bedrock's Converse API, which rejects a conversation that does
    not start on ``user`` and a ``toolResult`` with no matching ``toolUse``
    — failing the whole request rather than losing one prior turn.

    Emptying is therefore the correct outcome for a transcript with no legal
    head anywhere, not a contract violation: it is the same outcome
    ``_turn_boundary_slice`` itself chooses (with its own WARNING) when no
    boundary exists anywhere in a transcript it DID have to rewrite, and a
    continuation with no prior context is valid — ``_create_task_record``
    appends the fresh user turn immediately after. Both outcomes are logged:
    a partial trim keeps round 4's "resuming from the first turn boundary"
    WARNING, and a full drop gets its own distinct one back.

    RT-004: ``close_dangling_tool_use`` can now raise
    ``DanglingToolUseUnreadable`` for a tail that is confirmed to be a
    dangling ``toolUse`` turn but cannot be parsed into a repairable
    ``toolUseId``. The WRITE side (``repair_dangling_tool_use``) wants that
    raise — it is what lets ``repair_dangling_tool_use_safe`` gate the
    durable flush. This READ side has no such gate to fall back on: this
    function's whole job is to make whatever a ``TaskStore`` override hands
    back safe to fold into a brand-new task, so it must never crash
    ``_create_task_record`` over a corrupted stored transcript. Catch it
    here and drop the unreadable tail message outright — the same
    "no synthetic toolResult can be built without a readable toolUseId"
    reasoning ``close_dangling_tool_use`` itself uses, just with nothing
    left to replay it into — then bridge the remainder as usual.

    RT-006/RT-008 (debug round 4): this function is the READ-side normaliser
    for a store-supplied transcript, so it now DEEP-COPIES each message and
    coerces a non-list ``content`` into a single ``{"text": ...}`` block
    before any of the three re-assertions run. Both halves are load-bearing:

    * Coercion, because ``close_dangling_tool_use`` above no longer rejects a
      plain-text assistant tail (its RT-006 paragraph), so without this a raw
      ``content: "hello"`` string would survive the fold into
      ``record.messages`` and reach ``bedrock.py``'s Converse call, which
      passes ``messages`` through verbatim and requires a list of content
      blocks. ``append_assistant_turn`` below already applies exactly this
      coercion for the tail it merges into; doing it here covers every
      message, including the non-list ``user`` content that
      ``is_user_turn_boundary`` deliberately admits as a boundary.
    * Deep copy, because the docstring above promises "the caller's element
      dicts are never touched either" while ``list(messages)`` shared them —
      latent while this function only ever appended, but a live corruption of
      the PRIOR task's stored transcript the moment it rewrites a ``content``
      in place, as the coercion above does.

    A message left with NO content by that coercion (``None``, ``""``, ``[]``,
    or the key missing outright — a corrupt stored entry) is dropped rather
    than folded in as an empty block list, which Converse rejects just as
    firmly as the raw string. Dropping one can never orphan a
    ``toolUse``/``toolResult`` pairing, since an empty content carries
    neither.
    """
    bridged: list[dict[str, Any]] = []
    dropped_non_dict = 0
    for msg in messages:
        if not isinstance(msg, dict):
            # RT-006 (debug round 6): DROP, never pass through. Every other
            # helper in this module is guarded against a non-dict message
            # (close_dangling_tool_use, is_user_turn_boundary,
            # append_assistant_turn, bridge_trailing_user — all RT-B-008),
            # and each of those guards makes the entry *fail its predicate*
            # rather than making it safe. This function is the one place whose
            # stated job is to make whatever a TaskStore override hands back
            # safe to fold into a brand-new task, and it was the only one
            # letting the shape through: a non-dict survived here, the head
            # trim below only removes it while it is LEADING, and
            # routes/a2a.py::_create_task_record folds the remainder straight
            # into a fresh record.messages, which bedrock.py passes verbatim to
            # Converse — which rejects a message that is not an object.
            #
            # Dropping is the same call the empty-content branch below already
            # makes, on the same reasoning: a non-dict entry can carry neither
            # a toolUse nor a toolResult, so removing one can never orphan a
            # pairing.
            dropped_non_dict += 1
            continue
        entry = copy.deepcopy(msg)
        content = entry.get("content")
        if not is_content_sequence(content):
            if isinstance(content, bytes):
                content = content.decode("utf-8", "replace")
            if not content:
                continue
            entry["content"] = [{"text": content if isinstance(content, str) else str(content)}]
        elif not content:
            continue
        else:
            # RT-007 (debug round 6): normalise a tuple of content blocks to a
            # list instead of stringifying it. Downstream mutates content in
            # place (close_dangling_tool_use appends, append_assistant_turn
            # extends), so the sequence must be a real list by the time it is
            # folded into record.messages.
            entry["content"] = list(content)
        bridged.append(entry)
    if dropped_non_dict:
        logger.warning(
            "context continuation: dropped %d non-dict message(s) from a "
            "stored transcript — a Converse message must be an object, and a "
            "non-dict entry can carry neither a toolUse nor a toolResult, so "
            "dropping one cannot orphan a tool-call pairing.",
            dropped_non_dict,
        )
    dropped_from_head = 0
    while bridged and not is_user_turn_boundary(bridged[0]):
        bridged.pop(0)
        dropped_from_head += 1
    if dropped_from_head and bridged:
        logger.warning(
            "context continuation: dropped %d leading message(s) with no "
            "genuine turn boundary from a stored transcript (transcript has "
            "%d messages) — resuming from the first turn boundary found "
            "instead of the transcript's original head.",
            dropped_from_head, len(messages),
        )
    elif dropped_from_head:
        logger.warning(
            "context continuation: dropping the entire prior transcript — no "
            "message in %d can legally head a conversation (every leading "
            "message is an assistant turn or a toolResult continuation), and "
            "Bedrock's Converse API rejects both as a head; the new task "
            "starts from its own user turn with no prior context.",
            len(messages),
        )
    # DBG-7: RETRY the close after each drop, don't drop once and move on.
    # ``close_dangling_tool_use`` inspects the tail ONLY. Dropping an
    # unreadable tail therefore does not resolve the transcript — it EXPOSES a
    # new tail that the single pass already walked past and never examined. A
    # stored transcript shaped ``[user(text), assistant(toolUse t1),
    # assistant(malformed toolUse)]`` (two adjacent assistant turns, which
    # nothing on this read path collapses) left t1 dangling and unclosed: the
    # one pop removed the unreadable turn, ``bridge_trailing_user`` saw an
    # assistant tail and did nothing, and ``routes/a2a.py::_create_task_record``
    # folded a transcript still ending on an unmatched ``toolUse`` into the new
    # task's ``record.messages``, which Bedrock's Converse API rejects — the
    # exact outcome this whole function exists to prevent, reached through its
    # own recovery branch.
    #
    # Bounded by the transcript length: every iteration pops exactly one
    # message, so this terminates on an empty list at worst (a legitimate
    # outcome here already — see the DBG-5 paragraph above).
    while True:
        try:
            close_dangling_tool_use(bridged, default_content=[{"text": _STALE_TOOL_RESULT_TEXT}])
            break
        except DanglingToolUseUnreadable:
            logger.warning(
                "bridge_context_messages: dropping an unreadable dangling toolUse "
                "tail from a stored transcript — cannot correlate a toolResult "
                "without a readable toolUseId"
            )
            bridged.pop()
    bridge_trailing_user(bridged)
    return bridged


def append_assistant_turn(messages: list[dict[str, Any]], content: list[dict[str, Any]]) -> None:
    """RT-001 (GH-147 AC3 mirror image): fold a new assistant turn into
    ``messages`` without ever producing two adjacent assistant entries.

    ``bridge_trailing_user`` only guards the trailing-``user`` half of the
    "no two consecutive same-role messages" invariant — it assumes the tail
    is 'user' right before ``run_loop``'s two ``messages.append({"role":
    "assistant", ...})`` sites (the no-tool-call text fold and the toolUse
    fold), which holds for every transcript ``run_loop`` builds itself but
    NOT for one a caller supplies pre-seeded: AG-UI's
    ``routes/ag_ui.py::_fold_history`` only strips a LEADING assistant
    prefix, never a trailing one, so a client that resubmits history already
    ending on 'assistant' (a legitimate regenerate/continue request, or a
    malformed one) reaches ``run_loop`` with an assistant tail already in
    place. Appending onto that tail via the plain ``messages.append(...)``
    this function replaces would land two consecutive assistant messages,
    which Bedrock's Converse API rejects outright on the very next turn's
    ``model.converse()`` call.

    When the tail is already an assistant message, this MERGES the new
    content blocks into it instead — preserving whatever real content that
    tail carried (the prior reply, for the legitimate continue case) rather
    than discarding it or masking the break with a synthetic bridge turn.
    Otherwise behaves exactly like the append it replaces.

    RT-008: a caller-supplied tail's ``content`` is not guaranteed to be a
    list — the same non-list shape ``close_dangling_tool_use`` treats as
    unreadable-and-raise (``DanglingToolUseUnreadable``) can reach here too,
    e.g. a truthy scalar/string value. This function has no raise to fall
    back on (``run_loop`` calls it unconditionally at every turn boundary),
    so a non-list, non-empty tail is instead WRAPPED into a single text
    block and kept ahead of the new content — honouring the "preserving
    whatever real content that tail carried" promise above rather than the
    silent overwrite this replaced. A falsy tail (``None``/``""``/missing)
    has nothing to preserve and is just replaced with ``content`` directly.
    """
    if messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "assistant":
        tail_content = messages[-1].get("content")
        if isinstance(tail_content, list):
            tail_content.extend(content)
        elif is_content_sequence(tail_content):
            # RT-007 (debug round 6): a TUPLE tail is a sequence of content
            # blocks, so it is rebound as a list + the new blocks — not
            # stringified into {"text": "({'text': 'prior'},)"} by the branch
            # below, which contradicted this function's own promise to preserve
            # "whatever real content that tail carried". Rebinding rather than
            # extending in place because a tuple cannot be extended.
            messages[-1]["content"] = [*tail_content, *content]
        elif tail_content:
            preserved = tail_content if isinstance(tail_content, str) else str(tail_content)
            messages[-1]["content"] = [{"text": preserved}, *content]
        else:
            messages[-1]["content"] = content
        return
    messages.append({"role": "assistant", "content": content})


# Fixed human strings keyed by Pydantic error ``type`` code. SI-2: we never
# interpolate ``e['msg']`` or ``e['input']`` because both can embed the raw
# rejected value verbatim — e.g. a custom ``@field_validator`` that raises
# ``ValueError(f"... {v!r}")`` produces a ``value_error``/``assertion_error``
# whose ``msg`` echoes the secret. The model and logs only ever see loc + a
# type-derived phrase built here.
_VALIDATION_TYPE_PHRASES: dict[str, str] = {
    "missing": "required field is missing",
    "int_parsing": "expected an integer",
    "int_type": "expected an integer",
    "float_parsing": "expected a number",
    "float_type": "expected a number",
    "bool_parsing": "expected a boolean",
    "bool_type": "expected a boolean",
    "string_type": "expected a string",
    "string_too_short": "value is too short",
    "string_too_long": "value is too long",
    "string_pattern_mismatch": "value does not match the required pattern",
    "list_type": "expected a list",
    "dict_type": "expected an object",
    "model_type": "expected an object",
    "enum": "value is not one of the allowed choices",
    "literal_error": "value is not one of the allowed choices",
    "greater_than": "value is too small",
    "greater_than_equal": "value is too small",
    "less_than": "value is too large",
    "less_than_equal": "value is too large",
    "value_error": "value failed a validation rule",
    "assertion_error": "value failed a validation rule",
    "json_invalid": "value is not valid JSON",
    "extra_forbidden": "unexpected field",
}


def _unwrap_annotation(ann: Any) -> Any:
    """Strip Optional/Union noise to the first concrete member annotation.

    Used only to walk an error ``loc`` against the declared schema; on any
    Union we descend into the first non-``None`` member, which is sufficient
    to decide field-name vs. dict-key for the loc segment under inspection.
    """
    origin = get_origin(ann)
    if origin is Union:
        members = [a for a in get_args(ann) if a is not type(None)]
        return members[0] if members else ann
    return ann


def _redact_loc(loc: tuple[Any, ...], err_type: str, model: type[BaseModel] | None) -> str:
    """Render a Pydantic error ``loc`` keeping only schema-declared identifiers.

    SI-2: a ``loc`` can carry user-supplied content — for ``extra_forbidden``
    the final segment is the user's extra field NAME, and for any value error
    under a ``dict[str, X]`` field the segment is the user-supplied dict KEY
    (verified: ``loc=('mapping', 'USER_KEY')`` / ``('mapping','USER_KEY','[key]')``).
    Echoing those into the tool-result string would leak a field/key name to the
    model. We walk the declared model alongside ``loc``: declared field names and
    list indices pass through verbatim; any segment that lands on a dict/mapping
    key, or the trailing extra-field name of an ``extra_forbidden`` error, is
    replaced with ``<key>`` so only schema-declared identifiers are ever echoed.
    """
    n = len(loc)
    rendered: list[str] = []
    current: Any = model
    for i, seg in enumerate(loc):
        is_last = i == n - 1
        # extra_forbidden: trailing segment is the user-supplied extra field name.
        if is_last and err_type == "extra_forbidden":
            rendered.append("<extra>")
            continue
        # Structural Pydantic markers (e.g. '[key]') are not user content.
        if isinstance(seg, str) and seg.startswith("[") and seg.endswith("]"):
            rendered.append(seg)
            continue
        # List/tuple/set indices are integers — never user content.
        if isinstance(seg, int):
            rendered.append(str(seg))
            origin = get_origin(_unwrap_annotation(current)) if current is not None else None
            if origin in (list, tuple, set, frozenset):
                args = get_args(_unwrap_annotation(current))
                current = args[0] if args else None
            else:
                current = None
            continue
        ann = _unwrap_annotation(current) if current is not None else None
        origin = get_origin(ann)
        # Walking a Pydantic model: a matching declared field name is safe.
        if isinstance(current, type) and issubclass(current, BaseModel):
            field = current.model_fields.get(str(seg))
            if field is not None:
                rendered.append(str(seg))
                current = field.annotation
                continue
            # Not a declared field → user-supplied (extra / unexpected) key.
            rendered.append("<key>")
            current = None
            continue
        # Walking a dict/mapping: the segment IS a user-supplied key.
        if origin in (dict,) or (isinstance(origin, type) and issubclass(origin, dict)):
            rendered.append("<key>")
            args = get_args(ann)
            current = args[1] if len(args) == 2 else None
            continue
        # Unknown / unresolved structure: be conservative — if it is a plain
        # declared-style root segment on the model we'd have matched above, so
        # treat any remaining string as a potential user key.
        if model is None:
            # No schema to verify against → keep the (likely declared) name.
            rendered.append(str(seg))
        else:
            rendered.append("<key>")
        current = None
    return ".".join(rendered) or "<root>"


def safe_validation_message(
    tool_name: str,
    exc: ValidationError,
    input_model: type[BaseModel] | None = None,
) -> str:
    """Build a tool-input error string from loc + type only (SI-2).

    Never includes ``e['msg']`` or ``e['input']`` — both can leak the raw
    rejected value. ``loc`` is walked against ``input_model`` so that only
    schema-declared field names (and list indices) are echoed; user-supplied
    dict keys and ``extra_forbidden`` field names are redacted (see
    ``_redact_loc``). Unknown type codes fall back to the bare code, which is
    safe-by-construction (a fixed Pydantic identifier, never user input).
    """
    fields = "; ".join(
        f"{_redact_loc(tuple(e['loc']), e['type'], input_model)} — "
        f"{_VALIDATION_TYPE_PHRASES.get(e['type'], e['type'])}"
        for e in exc.errors()
    )
    return f"tool '{tool_name}' input invalid: {fields}"


async def run_loop(
    *,
    model: ModelClient,
    registry: ToolRegistry,
    adapters: dict[type[SourceAdapter], SourceAdapter],
    system: str,
    messages: list[dict[str, Any]],
    skills: SkillsRegistry | None = None,
    policies: LoopPolicies | None = None,
    wait_resume: Callable[[str], Awaitable[Any]] | None = None,
    spent_tokens: int = 0,
    clock: Callable[[], float] = time.monotonic,
    extra_resolved_messages: Sequence[dict[str, Any]] | None = None,
    pending_results: list[dict[str, Any]] | None = None,
    sealed: Callable[[], bool] | None = None,
) -> AsyncIterator[Any]:
    """Run the agentic loop over ``messages`` (Converse format, mutated in
    place so the caller retains history). Yields typed loop events and always
    terminates with a DoneEvent.

    ``extra_resolved_messages`` (RT-A-004) — additional Converse-format
    messages scanned ONLY to seed the initial ``resolved_index`` (GH-148);
    never appended to ``messages`` and never shown to the model. A transport
    whose own request/response shape does not replay tool-result blocks back
    into ``messages`` (AG-UI's client-resent transcript is folded through
    ``routes/ag_ui.py::_fold_history``, which strips them) passes its own
    out-of-band carrier here instead — ``routes/ag_ui.py`` passes
    ``TaskStore.context_reusable_messages(thread_id)`` (RT-001: every
    terminal task in the thread, not just the most recent one — an AG-UI
    ``TaskRecord.messages`` never inherits a prior run's ``messages``, so a
    single-most-recent seed would decay after exactly one intervening,
    unrelated run) — so a value resolved in an earlier request still
    substitutes on this one, without growing the prompt the model actually
    sees.

    ``pending_results`` (RT-B-001) — a caller-owned list that receives this
    turn's ``toolResult`` blocks as each tool call completes, mutated in
    place exactly like ``messages``. It exists because a turn's results are
    committed to ``messages`` only after EVERY call in that turn finishes:
    the assistant ``toolUse`` message is folded in first, so any mid-turn
    exit (a ``DeferredEvent`` handoff, a cancellation, or a raise that
    unwinds this generator's frame) would otherwise destroy the results of
    the calls that DID complete, leaving the out-of-loop repairer
    (``runner.py::repair_dangling_tool_use``) no choice but to synthesise a
    blanket error result for a tool that actually succeeded — and whose real
    result already reached the client as a ``ToolResultEvent``. Passing the
    task's ``record.pending_tool_results`` here makes that state reachable
    from every repair site (the deferred background awaiter, the worker's
    terminal handlers, ``tasks_cancel``) instead of dying with the frame.
    Cleared at the start of every turn and again once the turn commits
    normally, so after a normal turn boundary it is empty and after a
    mid-turn exit it holds exactly the completed calls of the turn that was
    interrupted. Omitting it keeps the previous behaviour (turn-local list).

    ``sealed`` (RT-004, debug round 4) — a predicate the caller supplies that
    answers "has some other owner already committed this task's terminal
    transition?". ``messages`` is the caller's live list, and an out-of-loop
    terminal owner (``routes/a2a.py``'s ``tasks_cancel``, or
    ``runner.py``'s deferred background awaiter) repairs and commits it
    with no await in between — but THIS generator keeps a reference to the
    same list and, if its own ``asyncio.CancelledError`` never lands, goes on
    to append the turn's ``toolResult`` message on top of the synthetic one
    the canceller already appended. That produces a duplicate ``toolUseId``
    plus an orphan ``user``/``toolResult`` with no immediately-preceding
    assistant ``toolUse``, on a CANCELED (terminal, hence replayable) task
    that ``context_messages()`` selects for the next ``contextId``
    continuation — GH-150's exact failure mode, reintroduced. Two escape
    paths make the missing ``CancelledError`` reachable and are named in
    ``run_task_worker``'s own comments: tool code catching ``BaseException``,
    and ``asyncio.wait_for``'s cancel-vs-timeout race on 3.11+ surfacing a
    ``TimeoutError`` instead. ``run_task_worker``'s terminal guard cannot
    close this: it runs in the event CONSUMER above this generator, and these
    appends happen down here before the next event is ever yielded — so the
    state itself is sealed, not the consumer loop. Checked at the top of every
    turn, immediately after ``await model.converse(...)`` returns (RT-006,
    debug round 4 follow-up — the model call is itself an await window a
    concurrent owner can seal during), and immediately before the per-turn
    ``toolResult`` commit; once true, this generator mutates ``messages`` no
    further and terminates. Omitting it keeps the previous behaviour (never
    sealed).
    """
    policies = policies or LoopPolicies()
    is_sealed: Callable[[], bool] = sealed if sealed is not None else (lambda: False)
    deadline = Deadline(policies.deadline_seconds, clock=clock)
    total_tokens = spent_tokens
    result_cache: dict[tuple[str, str], Any] = {}
    # GH-148: "resolved this conversation" index, rebuilt fresh from
    # ``messages`` (plus ``extra_resolved_messages``, RT-A-004) every call,
    # and grown in place below as this call resolves new Reusable values.
    # {kind: [(label, value)]}. A2A's TaskRecord.messages is server-persisted
    # and carries a prior turn's markers directly; AG-UI's client-resent
    # transcript does not (agent/reuse.py module docstring, RT-001), so its
    # route seeds ``extra_resolved_messages`` from a side channel instead.
    scan_source = messages if not extra_resolved_messages else [*extra_resolved_messages, *messages]
    resolved_index = scan_resolved(scan_source)
    # RT-A-008/RT-C-001: per-(tool_name, field_name, raw value) consecutive-
    # rejection count for this run_loop call only — bounds how long a field
    # on every ReuseKind default (strict=True, allow_raw_override=False) can
    # reject the same stuck raw value before resolve_reuse_fields grants a
    # forced passthrough instead of looping the model until max_turns. Keyed
    # on the raw value itself (not just the field) so a sequence of DIFFERENT
    # hallucinated values never shares one budget.
    reuse_reject_counts: dict[tuple[str, str, str], int] = {}

    tool_specs = [
        {
            "name": e.name,
            "description": e.description,
            "input_schema": e.input_schema(include_reuse_hint=True),
        }
        for e in registry.all()
    ]
    if skills is not None and skills.skills:
        tool_specs.append(
            {
                "name": LOAD_SKILL_TOOL,
                "description": "Load the full instructions of a listed skill by name.",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            }
        )

    for turn in range(1, policies.max_turns + 1):
        # RT-004: another owner already committed this task terminal and
        # repaired its transcript — stop before folding another assistant
        # turn onto the list it is now the sole author of. See ``sealed``.
        if is_sealed():
            yield DoneEvent(ok=False, error=_SEALED_TRANSCRIPT_ERROR)
            return
        if deadline.exceeded():
            bridge_trailing_user(messages)
            yield DoneEvent(ok=False, error="task deadline exceeded")
            return
        if total_tokens > policies.token_budget:
            summary_tokens = _summary_max_tokens(policies)
            summary = ""
            async for ev in _final_summary(
                model=model,
                system=system,
                messages=messages,
                tool_specs=tool_specs,
                policies=policies,
                max_tokens=summary_tokens,
                notice=_FINAL_SUMMARY_NOTICE_BUDGET,
                is_sealed=is_sealed,
            ):
                if isinstance(ev, TextEvent):
                    summary = ev.text
                yield ev
            if is_sealed():
                yield DoneEvent(ok=False, error=_SEALED_TRANSCRIPT_ERROR)
                return
            yield DoneEvent(
                ok=False,
                error="task token budget exceeded",
                summary=summary or None,
            )
            return

        yield TurnStartedEvent(turn=turn, max_turns=policies.max_turns)

        try:
            response = await model.converse(
                system=system,
                messages=messages,
                tools=tool_specs,
                max_tokens=policies.max_output_tokens,
            )
        except AgentError as err:
            bridge_trailing_user(messages)
            yield DoneEvent(ok=False, error=err.message)
            return

        # RT-006 (debug round 4 follow-up): ``await model.converse(...)``
        # above is exactly the await window ``sealed``'s docstring warns
        # about — another owner (``tasks_cancel``, the deferred background
        # awaiter) can commit this task's terminal transition and repair
        # ``messages`` while this call is in flight. The seal check at the
        # top of the turn only catches a seal that landed BEFORE this call;
        # re-check here, before either ``append_assistant_turn`` site below
        # (the no-tool-call fold and the toolUse fold) mutates the same list
        # the canceller already finished repairing — otherwise a NEW
        # assistant toolUse lands on a CANCELED (terminal, replayable)
        # transcript with no answering toolResult, GH-150's exact failure
        # shape.
        if is_sealed():
            yield DoneEvent(ok=False, error=_SEALED_TRANSCRIPT_ERROR)
            return

        total_tokens += response.input_tokens + response.output_tokens
        yield UsageEvent(
            input_tokens=response.input_tokens, output_tokens=response.output_tokens
        )

        for segment in response.text_segments:
            if segment.strip():
                yield TextEvent(text=segment)

        text_content: list[dict[str, Any]] = [
            {"text": seg} for seg in response.text_segments if seg.strip()
        ]

        if not response.tool_calls:
            # GH-147: fold the assistant's final plain-text turn so a
            # completed task's record.messages carries what the model
            # actually said — otherwise contextId continuation replay never
            # shows it. RT-001 (AC3): when every segment is empty/whitespace
            # there is nothing to fold, but messages still ends on the prior
            # 'user' turn at this point in every iteration — bridge it so
            # the transcript never ends on 'user' regardless.
            if text_content:
                append_assistant_turn(messages, text_content)
            else:
                bridge_trailing_user(messages)
            yield DoneEvent(ok=True)
            return

        # fold the assistant turn
        assistant_content = text_content + [
            {
                "toolUse": {
                    "toolUseId": tc.tool_call_id,
                    "name": tc.name,
                    "input": tc.arguments,
                }
            }
            for tc in response.tool_calls
        ]
        append_assistant_turn(messages, assistant_content)

        # RT-B-001: alias the caller's list when one was supplied so the
        # blocks survive a mid-turn exit (see ``pending_results`` above).
        # Cleared here, at the turn boundary, so it never carries a
        # previous turn's already-committed results.
        result_blocks: list[dict[str, Any]] = (
            [] if pending_results is None else pending_results
        )
        result_blocks.clear()
        ok: bool
        result: Any
        error: str | None
        for tc in response.tool_calls:
            yield ToolCallEvent(
                tool_call_id=tc.tool_call_id, tool_name=tc.name, arguments=tc.arguments
            )

            if tc.name == LOAD_SKILL_TOOL and skills is not None:
                requested_name = str(tc.arguments.get("name", ""))
                body = skills.load(requested_name)
                ok = body is not None
                if ok:
                    result = body
                else:
                    result = f"unknown skill {sanitize_text(requested_name)!r}"
                yield ToolResultEvent(
                    tool_call_id=tc.tool_call_id, tool_name=tc.name, ok=ok,
                    result=None, error=None if ok else result,
                )
                result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tc.tool_call_id,
                            "content": [{"text": result}],
                            "status": "success" if ok else "error",
                        }
                    }
                )
                continue

            entry = registry.get(tc.name)
            if entry is None:
                error = f"unknown tool {sanitize_text(tc.name)!r}"
                yield ToolResultEvent(
                    tool_call_id=tc.tool_call_id, tool_name=tc.name, ok=False, error=error
                )
                result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tc.tool_call_id,
                            "content": [{"text": error}],
                            "status": "error",
                        }
                    }
                )
                continue

            # GH-148: substitute $ref:<kind>/$ref:<kind>:<label> tokens and
            # reject a raw value that contradicts an already-resolved value
            # of that kind — before cache_key/invocation so a mismatched
            # call is never cached and never reaches the tool body. Empty
            # entry.decl.reuse_fields (the common case) is a no-op: byte-
            # identical behavior to before this feature existed.
            effective_arguments = tc.arguments
            if entry.decl.reuse_fields:
                effective_arguments, substitutions, reuse_error = resolve_reuse_fields(
                    tc.name, tc.arguments, entry.decl.reuse_fields, resolved_index,
                    strict_fields=entry.decl.reuse_strict,
                    raw_override_fields=entry.decl.reuse_raw_override,
                    reject_counts=reuse_reject_counts,
                    field_types=entry.decl.reuse_field_types,
                    max_consecutive_rejections=policies.reuse_forced_passthrough_limit,
                )
                if reuse_error is not None:
                    yield ToolResultEvent(
                        tool_call_id=tc.tool_call_id, tool_name=tc.name, ok=False,
                        error=reuse_error,
                    )
                    result_blocks.append(
                        {
                            "toolResult": {
                                "toolUseId": tc.tool_call_id,
                                "content": [{"text": reuse_error}],
                                "status": "error",
                            }
                        }
                    )
                    continue
                # (a): auditable, not silent — never the resolved value or
                # label itself (SI-2), only which field/kind was substituted.
                # AuditEvent, NOT NoteEvent (RT-009): this is internal
                # plumbing, not a user-facing caveat — routes must never fold
                # it into agent chat text.
                for sub in substitutions:
                    if sub.via_forced_passthrough:
                        # RT-A-008: MAX_CONSECUTIVE_REUSE_REJECTIONS straight
                        # mismatches on this (tool, field) already happened —
                        # an automatic liveness fallback, not an
                        # operator-authorized bypass, so it warrants more
                        # visibility than the two branches below.
                        logger.warning(
                            "tool %r field %r: forced passthrough after repeated "
                            "reuse rejections for kind %r (RT-A-008 bounded "
                            "recovery)",
                            tc.name, sub.field_name, sub.kind,
                        )
                    elif sub.via_raw_override:
                        logger.info(
                            "tool %r field %r: $raw override bypassed reuse "
                            "validation for kind %r",
                            tc.name, sub.field_name, sub.kind,
                        )
                    else:
                        logger.info(
                            "tool %r field %r: substituted $ref:%s",
                            tc.name, sub.field_name, sub.kind,
                        )
                    yield AuditEvent(
                        code=(
                            "reuse_forced_passthrough" if sub.via_forced_passthrough
                            else "reuse_raw_override" if sub.via_raw_override
                            else "reuse_substitution"
                        ),
                        detail={
                            "tool_name": tc.name,
                            "field_name": sub.field_name,
                            "kind": sub.kind,
                        },
                    )

            cache_key = (
                tc.name, json.dumps(effective_arguments, sort_keys=True, default=str)
            )
            # GH-87: resolve effective timeout — per-tool override wins over
            # per-tier default. See resolve_tool_timeout() for priority order.
            timeout = resolve_tool_timeout(tc.name, entry, policies)

            ok, result, error = True, None, None
            deferred: DeferredResult | None = None  # GH-87
            # RT-002 (regression against LRN-120/LRN-122): kind/label captured
            # when the tool returns Reusable(value=DeferredResult(...)) — the
            # ORIGINAL wrapper's kind/label, threaded onto DeferredEvent so
            # the runner can fold the __resolved__ marker once the handle
            # resolves (this call hands off and exits before the ordinary
            # Reusable unwrap further below ever runs).
            deferred_reuse_kind: str | None = None
            deferred_reuse_label: str | None = None
            interrupted: ToolInterrupt | None = None
            if cache_key in result_cache:
                result = result_cache[cache_key]
            elif entry.decl.is_generator:
                # GH-88: async-generator tool — drain under a single timeout
                # budget; forward interim ToolProgressEvent items downstream.
                try:
                    async with asyncio.timeout(timeout):
                        async for gen_item in entry.invoke_gen(effective_arguments, adapters):
                            if isinstance(gen_item, ToolTerminalResult):
                                result = gen_item.value
                            elif isinstance(gen_item, ToolProgressEvent):
                                yield gen_item  # forward interim event downstream
                            elif isinstance(gen_item, LoopEvent):
                                # Contract: only ToolProgressEvent is forwarded from
                                # gen-tool drains; all other LoopEvent subclasses
                                # (TextEvent, NoteEvent, ProgressEvent, …) are silently
                                # dropped.  Warn so gen-tool authors can catch routing
                                # mistakes early rather than debugging missing events.
                                logger.warning(
                                    "gen-tool %r yielded %s which is not forwarded "
                                    "downstream; only ToolProgressEvent is routed from "
                                    "async-generator tools — yielded event dropped",
                                    tc.name,
                                    type(gen_item).__name__,
                                )
                    # RT-002/RT-010: a Reusable wrapping a still-pending
                    # DeferredResult (the unhandled nesting ORDER — GH-148's
                    # Reusable unwrap normally happens later, at line ~770,
                    # which is AFTER this check) must be unwrapped here too,
                    # or the DeferredResult check below never fires and the
                    # raw handle leaks into messages/ToolResultEvent. The
                    # wrapper's kind/label describe the value the handle will
                    # EVENTUALLY resolve to — captured here and threaded onto
                    # DeferredEvent (below) so the runner's background awaiter
                    # can still fold the __resolved__ marker once resolved.
                    if isinstance(result, Reusable) and isinstance(result.value, DeferredResult):
                        deferred_reuse_kind, deferred_reuse_label = result.kind, result.label
                        result = result.value
                    # RT-001: detect DeferredResult on the generator's terminal
                    # value too — hand off to runner for background awaiting;
                    # skip cache and normal result path. Mirrors the coroutine
                    # branch below so a deferred handoff is transport-identical
                    # regardless of whether the tool is a coroutine or an
                    # async-generator (the MCP surface already routes both
                    # through resolve_deferred_result via invoke_any).
                    if isinstance(result, DeferredResult):
                        deferred = result
                        result = None  # runner owns resolution
                    else:
                        result_cache[cache_key] = result
                except ToolInterrupt as intr:
                    interrupted = intr
                except asyncio.TimeoutError:
                    ok, error = False, f"tool '{tc.name}' timed out after {timeout:g}s"
                except AgentError as err:
                    ok, error = False, err.message
                except ToolInputValidationError as exc:
                    # RT-004: raised ONLY by ToolEntry.invoke_gen's narrow
                    # model_validate try — never by the tool body — so this
                    # IS actually an input-shape defect, unlike a bare
                    # ValidationError (falls to the generic branch below).
                    ok, error = False, safe_validation_message(
                        exc.tool_name, exc.validation_error, entry.decl.input_model
                    )
                except Exception as exc:
                    # RT-001 (amended LRN-044 Check): the class name is an
                    # operator-facing diagnostic — log it, never interpolate
                    # it into the WIRE-facing error. ToolResultEvent.error
                    # reaches the untrusted A2A/AG-UI caller verbatim and is
                    # replayed into the transcript on every later contextId
                    # continuation (matches bedrock.py's RT-006 / runner.py's
                    # RT-002 precedent). SI-2: never str(exc), which can carry
                    # credentials or user payloads.
                    logger.error(
                        "tool call failed tool=%s error_type=%s frames=%s",
                        tc.name, type(exc).__name__, frame_locations(exc),
                    )
                    ok, error = False, f"tool '{tc.name}' failed"
            else:
                try:
                    result = await asyncio.wait_for(
                        entry.invoke(effective_arguments, adapters), timeout=timeout
                    )
                    # RT-002/RT-010: unwrap a Reusable wrapping a still-pending
                    # DeferredResult BEFORE the deferred check below — see the
                    # matching comment in the async-generator branch above for
                    # why this order matters; kind/label are captured, not
                    # discarded, and threaded onto DeferredEvent below.
                    if isinstance(result, Reusable) and isinstance(result.value, DeferredResult):
                        deferred_reuse_kind, deferred_reuse_label = result.kind, result.label
                        result = result.value
                    # GH-87: detect DeferredResult — hand off to runner for
                    # background awaiting; skip cache and normal result path.
                    if isinstance(result, DeferredResult):
                        deferred = result
                        result = None  # runner owns resolution
                    else:
                        result_cache[cache_key] = result
                except ToolInterrupt as intr:
                    interrupted = intr
                except asyncio.TimeoutError:
                    ok, error = False, f"tool '{tc.name}' timed out after {timeout:g}s"
                except AgentError as err:
                    ok, error = False, err.message
                except ToolInputValidationError as exc:
                    # RT-004: raised ONLY by ToolEntry.invoke's narrow
                    # model_validate try — never by the tool body — so this
                    # IS actually an input-shape defect, unlike a bare
                    # ValidationError (falls to the generic branch below).
                    # loc + type only — e['msg']/e['input'] can leak input
                    # (SI-2). loc walked against input_model so user dict
                    # keys / extra field names are redacted, not echoed.
                    ok, error = False, safe_validation_message(
                        exc.tool_name, exc.validation_error, entry.decl.input_model
                    )
                except Exception as exc:
                    # RT-001 (amended LRN-044 Check): the class name is an
                    # operator-facing diagnostic — log it, never interpolate
                    # it into the WIRE-facing error. ToolResultEvent.error
                    # reaches the untrusted A2A/AG-UI caller verbatim and is
                    # replayed into the transcript on every later contextId
                    # continuation (matches bedrock.py's RT-006 / runner.py's
                    # RT-002 precedent). SI-2: never str(exc), which can carry
                    # credentials or user payloads.
                    logger.error(
                        "tool call failed tool=%s error_type=%s frames=%s",
                        tc.name, type(exc).__name__, frame_locations(exc),
                    )
                    ok, error = False, f"tool '{tc.name}' failed"

            # GH-87: deferred tool — emit DeferredEvent, do NOT emit DoneEvent
            # or ToolResultEvent here; the runner's background awaiter takes over.
            if deferred is not None:
                yield DeferredEvent(
                    deferred=deferred,
                    tool_name=tc.name,
                    tool_call_id=tc.tool_call_id,
                    emits=entry.decl.emits,
                    timeout_seconds=timeout,
                    reuse_kind=deferred_reuse_kind,
                    reuse_label=deferred_reuse_label,
                )
                return  # loop exits; runner drives the task to completion

            if interrupted is not None:
                interrupt_id = uuid.uuid4().hex
                yield InterruptEvent(
                    interrupt_id=interrupt_id,
                    reason=interrupted.reason,
                    message=interrupted.message,
                    response_schema=interrupted.response_schema or {},
                    tool_call_id=tc.tool_call_id,
                )
                if wait_resume is None:
                    ok, error = False, "interrupt raised but no resume channel available"
                else:
                    deadline.suspend()
                    try:
                        resume_value = await wait_resume(interrupt_id)
                    finally:
                        deadline.resume()
                    if interrupted.resume_handler is not None:
                        try:
                            result = await asyncio.wait_for(
                                interrupted.resume_handler(resume_value), timeout=timeout
                            )
                        except AgentError as err:
                            ok, error = False, err.message
                        except asyncio.TimeoutError:
                            ok, error = False, f"tool '{tc.name}' timed out after resume"
                        except Exception as exc:
                            # RT-004: resume_handler never goes through
                            # ToolEntry.invoke's model_validate, so a
                            # ValidationError here can only be a body-level
                            # defect — it belongs in the generic branch, not
                            # mislabeled against entry.decl.input_model (which
                            # describes the tool's ORIGINAL arguments, not
                            # resume_value).
                            # RT-001 (amended LRN-044 Check): the class name
                            # is an operator-facing diagnostic — log it, never
                            # interpolate it into the WIRE-facing error (SI-2,
                            # matches bedrock.py's RT-006 / runner.py's RT-002
                            # precedent). Never str(exc) either, which can
                            # carry credentials or user payloads.
                            logger.error(
                                "tool call failed after resume tool=%s error_type=%s frames=%s",
                                tc.name, type(exc).__name__, frame_locations(exc),
                            )
                            ok, error = False, f"tool '{tc.name}' failed after resume"
                    else:
                        result = {"interrupt": interrupted.reason, "user_response": resume_value}

            # GH-148: unwrap a Reusable return value before the model sees
            # it (it receives .value, exactly like a plain return) and grow
            # the resolved index in place so a downstream tool call LATER
            # in this same run_loop call can already reference it.
            resolved_marker: dict[str, Any] | None = None
            if ok and isinstance(result, Reusable):
                # RT-005: normalize BEFORE folding into resolved_index/the
                # marker — a raw BaseModel here would plant a live pydantic
                # object inside messages and crash json.dumps on the next
                # model call. `result` (below) stays the unwrapped raw
                # value: the model/emits/ArtifactEvent path needs the real
                # object, only the messages-bound marker needs it JSON-safe.
                jsonable_value = jsonable_reuse_value(result.value)
                marker_entries = resolved_index.setdefault(result.kind, [])
                # RT-007: type-aware identity (see index_entry_key's
                # docstring) — plain tuple `==` on (label, value) conflates
                # 1/True/1.0 across a type boundary, silently collapsing two
                # distinct resolutions into one index entry.
                marker_key = index_entry_key(result.label, jsonable_value)
                same_label_keys = {
                    index_entry_key(lbl, val)
                    for lbl, val in marker_entries
                    if lbl == result.label
                }
                if same_label_keys != {marker_key}:
                    # RT-A-02: last resolution wins for a re-resolved
                    # (kind, label) pair. The old dedup only skipped a
                    # byte-identical (label, value) repeat and otherwise
                    # APPENDED — so re-resolving a label to a genuinely new
                    # value (a refreshed identifier) left two entries
                    # sharing one label, permanently dead-locking
                    # `$ref:<kind>:<label>` for that label: the multi-match
                    # branch below rejects as ambiguous, and a raw value
                    # matching the freshest entry hits the ambiguity branch
                    # too — both reject with the exact disambiguation move
                    # the caller already made. Dropping every prior entry
                    # for this label before appending keeps at most one
                    # entry per label at all times (and self-heals a
                    # same-label duplicate inherited from scan_resolved's
                    # rebuild of persisted messages, RT-007), while the
                    # `!= {marker_key}` guard still skips the mutation
                    # entirely on a genuine byte-identical repeat so
                    # ordering is undisturbed in the common case.
                    marker_entries[:] = [
                        (lbl, val) for lbl, val in marker_entries if lbl != result.label
                    ]
                    marker_entries.append((result.label, jsonable_value))
                resolved_marker = {
                    "kind": result.kind, "label": result.label, "value": jsonable_value,
                }
                result = result.value

            if ok:
                emits = entry.decl.emits
                if emits is not None and isinstance(result, emits):
                    yield ArtifactEvent(
                        data_type=getattr(emits, "data_type", entry.name),
                        tool_name=tc.name,
                        model=result,
                    )
                yield ToolResultEvent(
                    tool_call_id=tc.tool_call_id, tool_name=tc.name, ok=True, result=result
                )
                content_blocks: list[dict[str, Any]] = [fold_result_content(result)]
                if resolved_marker is not None:
                    # Same tool-result content array already folded into
                    # messages today — no new TaskRecord field. Visible to
                    # the model too: this is how it learns a value it just
                    # got is citable later via $ref:<kind>.
                    content_blocks.append({"json": {RESOLVED_MARKER_KEY: resolved_marker}})
                result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tc.tool_call_id,
                            "content": content_blocks,
                            "status": "success",
                        }
                    }
                )
            else:
                yield ToolResultEvent(
                    tool_call_id=tc.tool_call_id, tool_name=tc.name, ok=False, error=error
                )
                result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tc.tool_call_id,
                            "content": [{"text": error or "tool failed"}],
                            "status": "error",
                        }
                    }
                )

        # RT-004: the one commit that survives a swallowed cancellation. By
        # here every tool call in the turn has returned, so a concurrent
        # tasks_cancel has had its chance to repair and commit — if it did,
        # this append would land a DUPLICATE toolUseId and an orphan
        # user/toolResult on top of its synthetic one. Drop the turn instead;
        # the canceller's repaired transcript is the authoritative one, and
        # the pending blocks it did not use are discarded with it (they are
        # runtime-only turn state, never serialised).
        if is_sealed():
            result_blocks.clear()
            yield DoneEvent(ok=False, error=_SEALED_TRANSCRIPT_ERROR)
            return
        # RT-B-001: commit a COPY — ``result_blocks`` may be the caller's
        # ``pending_results`` list, which is cleared below (and at the next
        # turn boundary); appending it by reference would empty the message
        # we just folded. The turn is now fully recorded in ``messages``, so
        # nothing is left pending for a repairer to re-apply.
        messages.append({"role": "user", "content": list(result_blocks)})
        result_blocks.clear()

    if deadline.exceeded():
        bridge_trailing_user(messages)
        yield DoneEvent(ok=False, error="task deadline exceeded")
        return
    turns_summary_tokens = _summary_max_tokens(policies)
    summary = ""
    async for ev in _final_summary(
        model=model,
        system=system,
        messages=messages,
        tool_specs=tool_specs,
        policies=policies,
        max_tokens=turns_summary_tokens,
        notice=_FINAL_SUMMARY_NOTICE_TURNS,
        is_sealed=is_sealed,
    ):
        if isinstance(ev, TextEvent):
            summary = ev.text
        yield ev
    if is_sealed():
        yield DoneEvent(ok=False, error=_SEALED_TRANSCRIPT_ERROR)
        return
    yield DoneEvent(
        ok=False,
        error=f"max turns ({policies.max_turns}) exceeded",
        summary=summary or None,
    )
