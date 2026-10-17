"""GH-194: one tools-off retry when the model returns a blank reply after a tool result."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from agent_sdk.agent.events import ArtifactEvent, DoneEvent, TextEvent, UsageEvent
from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.model_client import ModelResponse
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.models.content_types import KpiCard, MetricItem
from agent_sdk.testing import FakeModelClient, reply, tool_call

NOTICE = (
    "I ran the requested steps but could not write a reply. "
    "Please try again or rephrase your request."
)

tools = ToolSet()


class Empty(BaseModel):
    pass


@tools.tool(tier=1, read_only=True)
async def ping(inp: Empty) -> str:
    """Return pong."""
    return "pong"


@tools.tool(tier=1, emits=KpiCard, read_only=True)
async def card(inp: Empty) -> KpiCard:
    """Emit a card."""
    return KpiCard(metrics=[MetricItem(label="A", value=1)])


REGISTRY = ToolRegistry([tools], {})


def blank() -> ModelResponse:
    return reply("  ")


async def _run(model, policies=None, messages=None, **kw):
    messages = messages if messages is not None else [{"role": "user", "content": [{"text": "go"}]}]
    events = [
        ev
        async for ev in run_loop(
            model=model, registry=REGISTRY, adapters={}, system="s",
            messages=messages, policies=policies or LoopPolicies(), **kw,
        )
    ]
    return events, messages


def _roles_ok(messages):
    roles = [m["role"] for m in messages]
    return all(a != b for a, b in zip(roles, roles[1:]))


async def test_empty_then_text():
    model = FakeModelClient([tool_call("ping"), blank(), reply("all done")])
    events, messages = await _run(model)
    assert [e.text for e in events if isinstance(e, TextEvent)] == ["all done"]
    assert isinstance(events[-1], DoneEvent) and events[-1].ok
    assert len(model.calls) == 3
    assert model.calls[-1]["tool_choice"] == "none"
    assert model.calls[0]["tool_choice"] == "auto"
    assert messages[-1] == {"role": "assistant", "content": [{"text": "all done"}]}
    assert _roles_ok(messages)


async def test_retry_does_not_use_a_turn_and_counts_tokens():
    model = FakeModelClient([tool_call("ping"), blank(), reply("ok", input_tokens=7, output_tokens=5)])
    events, _ = await _run(model, LoopPolicies(max_turns=2))
    done = events[-1]
    assert isinstance(done, DoneEvent) and done.ok
    usage = [e for e in events if isinstance(e, UsageEvent)]
    assert len(usage) == 3
    assert (usage[-1].input_tokens, usage[-1].output_tokens) == (7, 5)


async def test_empty_then_empty_yields_notice():
    model = FakeModelClient([tool_call("ping"), blank(), blank()])
    events, messages = await _run(model)
    assert [e.text for e in events if isinstance(e, TextEvent)] == [NOTICE]
    assert isinstance(events[-1], DoneEvent) and events[-1].ok
    assert len(model.calls) == 3
    assert _roles_ok(messages) and messages[-1]["role"] == "assistant"


async def test_empty_then_raise_yields_notice_without_provider_text():
    model = FakeModelClient([tool_call("ping"), blank()])  # script exhausted -> raises
    events, messages = await _run(model)
    texts = [e.text for e in events if isinstance(e, TextEvent)]
    assert texts == [NOTICE]
    assert isinstance(events[-1], DoneEvent) and events[-1].ok
    assert "exhausted" not in str(events)
    assert _roles_ok(messages)


async def test_card_then_empty_adds_no_notice():
    model = FakeModelClient([tool_call("card"), blank(), blank()])
    events, messages = await _run(model)
    assert any(isinstance(e, ArtifactEvent) for e in events)
    assert not [e for e in events if isinstance(e, TextEvent)]
    assert isinstance(events[-1], DoneEvent) and events[-1].ok
    assert _roles_ok(messages)


async def test_flag_off_restores_old_behaviour():
    model = FakeModelClient([tool_call("ping"), blank()])
    events, messages = await _run(model, LoopPolicies(empty_reply_retry=False))
    assert not [e for e in events if isinstance(e, TextEvent)]
    assert isinstance(events[-1], DoneEvent) and events[-1].ok
    assert len(model.calls) == 2
    assert _roles_ok(messages)


async def test_no_retry_without_tool_result():
    model = FakeModelClient([blank()])
    events, _ = await _run(model)
    assert len(model.calls) == 1
    assert isinstance(events[-1], DoneEvent) and events[-1].ok
    assert not [e for e in events if isinstance(e, TextEvent)]


async def test_no_retry_when_out_of_budget():
    empty = ModelResponse(text_segments=[""], stop_reason="end_turn", input_tokens=200, output_tokens=0)
    model = FakeModelClient([tool_call("ping"), empty])
    events, _ = await _run(model, LoopPolicies(token_budget=100))
    assert len(model.calls) == 2
    assert not [e for e in events if isinstance(e, TextEvent)]
    assert isinstance(events[-1], DoneEvent) and events[-1].ok


async def test_no_retry_when_sealed_during_retry():
    state = {"sealed": False}

    class Sealing(FakeModelClient):
        async def converse(self, **kw):
            if kw.get("tool_choice") == "none":
                state["sealed"] = True
            return await super().converse(**kw)

    model = Sealing([tool_call("ping"), blank(), reply("late")])
    events, messages = await _run(model, sealed=lambda: state["sealed"])
    assert not [e for e in events if isinstance(e, TextEvent)]
    assert isinstance(events[-1], DoneEvent) and not events[-1].ok
    assert messages[-1]["role"] == "user"


def test_retry_prompt_does_not_claim_a_limit():
    model = FakeModelClient([tool_call("ping", {}), blank(), reply("done")])
    asyncio.run(_run(model))
    last = model.calls[-1] if hasattr(model, "calls") else None
    assert last is not None
    text = str(last["messages"][-1] if isinstance(last, dict) else last)
    assert "wrote no reply" in text
    assert "reached the limit" not in text
