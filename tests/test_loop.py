"""Loop policy enforcement (DESIGN.md §8) — direct run_loop tests."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import DoneEvent, ToolResultEvent
from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.registry import ToolSet, ToolRegistry
from agent_sdk.models.errors import AgentError, ErrorCategory
from agent_sdk.testing import FakeModelClient, reply, tool_call

tools = ToolSet()
CALLS = {"count": 0, "boom": 0}


class EchoIn(BaseModel):
    text: str


@tools.tool(tier=1)
async def counted(inp: EchoIn) -> dict[str, Any]:
    """Counts invocations (cache test)."""
    CALLS["count"] += 1
    return {"echo": inp.text, "n": CALLS["count"]}


@tools.tool(tier=1)
async def boom(inp: EchoIn) -> dict[str, Any]:
    """Raises AgentError."""
    CALLS["boom"] += 1
    raise AgentError(ErrorCategory.UPSTREAM, "upstream said no", source="demo")


REGISTRY = ToolRegistry([tools], {})


async def collect(model, **kwargs) -> list[Any]:
    events = []
    async for ev in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="test",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
        **kwargs,
    ):
        events.append(ev)
    return events


async def test_max_turns_exhaustion():
    model = FakeModelClient(
        [tool_call("counted", {"text": f"t{i}"}) for i in range(10)]
    )
    events = await collect(model, policies=LoopPolicies(max_turns=3))
    done = events[-1]
    assert isinstance(done, DoneEvent) and not done.ok
    assert "max turns (3)" in done.error


async def test_token_budget_exceeded():
    model = FakeModelClient(
        [
            tool_call("counted", {"text": "a"}, input_tokens=600, output_tokens=600),
            reply("never reached"),
        ]
    )
    events = await collect(model, policies=LoopPolicies(token_budget=1000))
    done = events[-1]
    assert not done.ok and "token budget" in done.error


async def test_result_cache_identical_call():
    CALLS["count"] = 0
    model = FakeModelClient(
        [
            tool_call("counted", {"text": "same"}),
            tool_call("counted", {"text": "same"}),
            reply("done"),
        ]
    )
    events = await collect(model)
    assert events[-1].ok
    assert CALLS["count"] == 1  # second identical call served from cache
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert all(r.ok for r in results) and len(results) == 2


async def test_agent_error_becomes_tool_result():
    model = FakeModelClient([tool_call("boom", {"text": "x"}), reply("recovered")])
    events = await collect(model)
    assert events[-1].ok  # the loop survived
    failed = [e for e in events if isinstance(e, ToolResultEvent) and not e.ok]
    assert failed and failed[0].error == "upstream said no"


async def test_unknown_tool_is_tool_error_not_crash():
    model = FakeModelClient([tool_call("does_not_exist"), reply("ok")])
    events = await collect(model)
    assert events[-1].ok
    failed = [e for e in events if isinstance(e, ToolResultEvent) and not e.ok]
    assert "unknown tool" in failed[0].error


async def test_deadline_suspended_clock():
    from agent_sdk.agent.loop import Deadline

    t = {"now": 0.0}
    d = Deadline(10.0, clock=lambda: t["now"])
    t["now"] = 5.0
    d.suspend()
    t["now"] = 100.0  # long interrupt wait
    d.resume()
    t["now"] = 104.0
    assert not d.exceeded()  # 5 + 4 consumed < 10
    t["now"] = 102.0 + 10.0
    assert d.exceeded()
