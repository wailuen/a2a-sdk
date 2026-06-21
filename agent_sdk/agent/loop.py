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
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Union, get_args, get_origin

logger = logging.getLogger(__name__)

from pydantic import BaseModel, ValidationError

from ..models.errors import AgentError, ErrorCategory
from .deferred import DeferredEvent, DeferredResult
from .events import (
    ArtifactEvent,
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
from .registry import ToolRegistry, _ToolTerminalResult
from .skills import SkillsRegistry
from ..sources import SourceAdapter

TIER_TIMEOUTS = {1: 130.0, 2: 180.0}
LOAD_SKILL_TOOL = "load_skill"
DEFAULT_MAX_OUTPUT_TOKENS = 8192


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


def _fold_result_content(result: Any) -> dict[str, Any]:
    """toolResult content block for the Converse API."""
    from pydantic import BaseModel

    if isinstance(result, BaseModel):
        dump = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        return {"json": dump}
    if isinstance(result, (dict, list)):
        return {"json": {"result": result} if isinstance(result, list) else result}
    return {"text": "" if result is None else str(result)}


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


def _safe_validation_message(
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
) -> AsyncIterator[Any]:
    """Run the agentic loop over ``messages`` (Converse format, mutated in
    place so the caller retains history). Yields typed loop events and always
    terminates with a DoneEvent."""
    policies = policies or LoopPolicies()
    deadline = Deadline(policies.deadline_seconds, clock=clock)
    total_tokens = spent_tokens
    result_cache: dict[tuple[str, str], Any] = {}

    tool_specs = [
        {"name": e.name, "description": e.description, "input_schema": e.input_schema()}
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
        if deadline.exceeded():
            yield DoneEvent(ok=False, error="task deadline exceeded")
            return
        if total_tokens > policies.token_budget:
            yield DoneEvent(ok=False, error="task token budget exceeded")
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
            yield DoneEvent(ok=False, error=err.message)
            return

        total_tokens += response.input_tokens + response.output_tokens
        yield UsageEvent(
            input_tokens=response.input_tokens, output_tokens=response.output_tokens
        )

        for segment in response.text_segments:
            if segment.strip():
                yield TextEvent(text=segment)

        if not response.tool_calls:
            yield DoneEvent(ok=True)
            return

        # fold the assistant turn
        assistant_content: list[dict[str, Any]] = [
            {"text": seg} for seg in response.text_segments if seg.strip()
        ]
        assistant_content += [
            {
                "toolUse": {
                    "toolUseId": tc.tool_call_id,
                    "name": tc.name,
                    "input": tc.arguments,
                }
            }
            for tc in response.tool_calls
        ]
        messages.append({"role": "assistant", "content": assistant_content})

        result_blocks: list[dict[str, Any]] = []
        ok: bool
        result: Any
        error: str | None
        for tc in response.tool_calls:
            yield ToolCallEvent(
                tool_call_id=tc.tool_call_id, tool_name=tc.name, arguments=tc.arguments
            )

            if tc.name == LOAD_SKILL_TOOL and skills is not None:
                body = skills.load(str(tc.arguments.get("name", "")))
                ok = body is not None
                result = body if ok else f"unknown skill {tc.arguments.get('name')!r}"
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
                # Sanitize the model-supplied name before logging (SI-2: model
                # output is untrusted; prevent log injection via newlines etc.)
                _safe = tc.name[:64].translate(dict.fromkeys(range(0x20), " "))
                error = f"unknown tool {_safe!r}"
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

            cache_key = (tc.name, json.dumps(tc.arguments, sort_keys=True, default=str))
            # GH-87: resolve effective timeout — per-tool override wins over
            # per-tier default.  Sources (priority order):
            #   1. policies.per_tool_timeouts[tc.name] (explicit caller override)
            #   2. entry.decl.tool_timeout_override (@tool decorator kwarg)
            #   3. policies.tool_timeouts[tier] (tier default)
            #   4. TIER_TIMEOUTS[2] (hard fallback)
            if tc.name in policies.per_tool_timeouts:
                timeout = policies.per_tool_timeouts[tc.name]
            elif entry.decl.tool_timeout_override is not None:
                timeout = entry.decl.tool_timeout_override
            else:
                timeout = policies.tool_timeouts.get(entry.tier, TIER_TIMEOUTS[2])

            ok, result, error = True, None, None
            deferred: DeferredResult | None = None  # GH-87
            interrupted: ToolInterrupt | None = None
            if cache_key in result_cache:
                result = result_cache[cache_key]
            elif entry.decl.is_generator:
                # GH-88: async-generator tool — drain under a single timeout
                # budget; forward interim ToolProgressEvent items downstream.
                try:
                    async with asyncio.timeout(timeout):
                        async for gen_item in entry.invoke_gen(tc.arguments, adapters):
                            if isinstance(gen_item, _ToolTerminalResult):
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
                    result_cache[cache_key] = result
                except ToolInterrupt as intr:
                    interrupted = intr
                except asyncio.TimeoutError:
                    ok, error = False, f"tool '{tc.name}' timed out after {int(timeout)}s"
                except AgentError as err:
                    ok, error = False, err.message
                except ValidationError as exc:
                    ok, error = False, _safe_validation_message(
                        tc.name, exc, entry.decl.input_model
                    )
                except Exception:
                    ok, error = False, f"tool '{tc.name}' failed"
            else:
                try:
                    result = await asyncio.wait_for(
                        entry.invoke(tc.arguments, adapters), timeout=timeout
                    )
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
                    ok, error = False, f"tool '{tc.name}' timed out after {int(timeout)}s"
                except AgentError as err:
                    ok, error = False, err.message
                except ValidationError as exc:
                    # loc + type only — e['msg']/e['input'] can leak input (SI-2).
                    # loc walked against input_model so user dict keys / extra
                    # field names are redacted, not echoed.
                    ok, error = False, _safe_validation_message(
                        tc.name, exc, entry.decl.input_model
                    )
                except Exception:
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
                        except ValidationError as exc:
                            # loc + type only — e['msg']/e['input'] leak input (SI-2).
                            # loc walked against input_model so user dict keys /
                            # extra field names are redacted, not echoed.
                            ok, error = False, _safe_validation_message(
                                tc.name, exc, entry.decl.input_model
                            )
                        except Exception:
                            ok, error = False, f"tool '{tc.name}' failed after resume"
                    else:
                        result = {"interrupt": interrupted.reason, "user_response": resume_value}

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
                result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tc.tool_call_id,
                            "content": [_fold_result_content(result)],
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

        messages.append({"role": "user", "content": result_blocks})

    yield DoneEvent(ok=False, error=f"max turns ({policies.max_turns}) exceeded")
