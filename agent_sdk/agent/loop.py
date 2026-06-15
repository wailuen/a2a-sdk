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
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from ..models.errors import AgentError, ErrorCategory
from .events import (
    ArtifactEvent,
    DoneEvent,
    InterruptEvent,
    TextEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnStartedEvent,
    UsageEvent,
)
from .model_client import ModelClient
from .registry import ToolRegistry
from .skills import SkillsRegistry
from ..sources import SourceAdapter

TIER_TIMEOUTS = {1: 130.0, 2: 180.0}
LOAD_SKILL_TOOL = "load_skill"


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
    tool_timeouts: dict[int, float] = field(default_factory=lambda: dict(TIER_TIMEOUTS))


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
                system=system, messages=messages, tools=tool_specs
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
            timeout = policies.tool_timeouts.get(entry.tier, TIER_TIMEOUTS[2])

            ok, result, error = True, None, None
            interrupted: ToolInterrupt | None = None
            if cache_key in result_cache:
                result = result_cache[cache_key]
            else:
                try:
                    result = await asyncio.wait_for(
                        entry.invoke(tc.arguments, adapters), timeout=timeout
                    )
                    result_cache[cache_key] = result
                except ToolInterrupt as intr:
                    interrupted = intr
                except asyncio.TimeoutError:
                    ok, error = False, f"tool '{tc.name}' timed out after {int(timeout)}s"
                except AgentError as err:
                    ok, error = False, err.message
                except Exception:
                    ok, error = False, f"tool '{tc.name}' failed"

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
