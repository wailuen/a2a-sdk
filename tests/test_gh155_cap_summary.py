"""GH-155: one tools-disabled summary call at the max-turns / token-budget exits."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.agent.events import DoneEvent, TextEvent, UsageEvent
from agent_sdk.agent.bedrock import BedrockModelClient
from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.model_client import ModelResponse
from agent_sdk.agent.openai_client import OpenAIModelClient
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .test_a2a import send_body, wait_for_state
from .test_ag_ui import run, run_body

REGISTRY = ToolRegistry([ToolSet()], {})


async def _run(model, messages, policies):
    return [
        ev
        async for ev in run_loop(
            model=model, registry=REGISTRY, adapters={}, system="s",
            messages=messages, policies=policies,
        )
    ]


def _roles_ok(messages):
    roles = [m["role"] for m in messages]
    return all(a != b for a, b in zip(roles, roles[1:]))


def _msgs():
    return [{"role": "user", "content": [{"text": "go"}]}]


async def test_max_turns_summary():
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1}), reply("here is what I found")])
    messages = _msgs()
    events = await _run(model, messages, LoopPolicies(max_turns=1))
    texts = [e.text for e in events if isinstance(e, TextEvent)]
    assert texts == ["here is what I found"]
    done = events[-1]
    assert isinstance(done, DoneEvent) and not done.ok
    assert "max turns (1)" in done.error
    assert done.summary == "here is what I found"
    call = model.calls[-1]
    assert call["tool_choice"] == "none"
    assert call["max_tokens"] == 1024
    assert call["messages"][-1]["role"] == "user"
    assert _roles_ok(call["messages"])
    assert messages[-1] == {"role": "assistant", "content": [{"text": "here is what I found"}]}
    assert _roles_ok(messages)
    assert "limit for this task" not in str(messages)
    assert any(isinstance(e, UsageEvent) for e in events)


async def test_budget_summary_and_bounded_tokens():
    model = FakeModelClient(
        [tool_call("unknown_tool", {"x": 1}, input_tokens=600, output_tokens=600), reply("partial")]
    )
    events = await _run(model, _msgs(), LoopPolicies(token_budget=1000, final_summary_max_tokens=3000, max_output_tokens=500))
    done = events[-1]
    assert not done.ok and "token budget" in done.error and done.summary == "partial"
    assert model.calls[-1]["tool_choice"] == "none"
    assert model.calls[-1]["max_tokens"] == 500


async def test_budget_far_past_still_makes_summary_call():
    # GH-155 ruling: the notice is only for a FAILED summary call. How far
    # the crossing turn overshot the budget never skips the call.
    model = FakeModelClient(
        [tool_call("unknown_tool", {"x": 1}, output_tokens=1_000_000), reply("partial")]
    )
    messages = _msgs()
    events = await _run(model, messages, LoopPolicies(token_budget=10))
    assert len(model.calls) == 2
    assert model.calls[-1]["tool_choice"] == "none"
    assert model.calls[-1]["max_tokens"] == 1024
    assert events[-1].summary == "partial" and not events[-1].ok
    assert "token budget" in events[-1].error
    assert messages[-1] == {"role": "assistant", "content": [{"text": "partial"}]}
    assert _roles_ok(messages)


async def test_model_raises_falls_back_to_notice_without_leak():
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1})])  # script exhausted on call 2
    messages = _msgs()
    events = await _run(model, messages, LoopPolicies(max_turns=1))
    texts = [e.text for e in events if isinstance(e, TextEvent)]
    assert len(texts) == 1 and texts[0].startswith("I reached my step limit")
    assert "exhausted" not in texts[0]
    assert events[-1].summary == texts[0] and not events[-1].ok
    assert messages[-1]["role"] == "assistant" and _roles_ok(messages)


async def test_empty_or_tool_only_reply_falls_back_to_notice():
    for second in (
        ModelResponse(text_segments=["  "], stop_reason="end_turn"),
        tool_call("unknown_tool", {"x": 2}),
    ):
        model = FakeModelClient([tool_call("unknown_tool", {"x": 1}), second])
        events = await _run(model, _msgs(), LoopPolicies(max_turns=1))
        texts = [e.text for e in events if isinstance(e, TextEvent)]
        assert len(texts) == 1 and texts[0].startswith("I reached my step limit")


async def test_final_summary_false_restores_old_behavior():
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1}), reply("never")])
    messages = _msgs()
    events = await _run(model, messages, LoopPolicies(max_turns=1, final_summary=False))
    assert len(model.calls) == 1
    assert not any(isinstance(e, TextEvent) for e in events)
    assert events[-1].summary is None and not events[-1].ok
    assert messages[-1]["role"] == "assistant" and _roles_ok(messages)


async def test_deadline_exit_makes_no_extra_call():
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1}), reply("never")])
    n = {"i": 0}

    def clock() -> float:
        n["i"] += 1
        return 0.0 if n["i"] <= 2 else 10_000.0

    events = [
        ev
        async for ev in run_loop(
            model=model, registry=REGISTRY, adapters={}, system="s", messages=_msgs(),
            policies=LoopPolicies(deadline_seconds=1.0), clock=clock,
        )
    ]
    assert len(model.calls) == 1 and "deadline" in events[-1].error


async def test_sealed_during_summary_call_does_not_fold():
    state = {"sealed": False}

    class SealingModel(FakeModelClient):
        async def converse(self, **kw: Any) -> Any:
            r = await super().converse(**kw)
            if kw.get("tool_choice") == "none":
                state["sealed"] = True
            return r

    model = SealingModel([tool_call("unknown_tool", {"x": 1}), reply("late")])
    messages = _msgs()
    events = [
        ev
        async for ev in run_loop(
            model=model, registry=REGISTRY, adapters={}, system="s", messages=messages,
            policies=LoopPolicies(max_turns=1), sealed=lambda: state["sealed"],
        )
    ]
    assert not any(isinstance(e, TextEvent) for e in events)
    assert not events[-1].ok and "terminated" in events[-1].error
    assert messages[-1]["role"] == "user"


# ── end to end ────────────────────────────────────────────────────────────


def _build(tmp_path, **env):
    fm = FakeModelClient()
    s = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "d"), AGENT_NAME="a",
        AGENT_SDK_MAX_TURNS="1", **env,
    )
    return make_agent(s, model_client=fm).build_app(), fm


async def _client(app):
    _, token = app.state.auth.api_keys.mint("t", admin=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_a2a_failed_status_message_carries_summary(tmp_path):
    app, fm = _build(tmp_path)
    fm.script(tool_call("echo", {"text": "hi"}), reply("summary for the user"))
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            r = await c.post("/v1/message:send", json=send_body("go"))
            task = await wait_for_state(c, r.json()["id"])
    assert task["status"]["state"] == "failed"
    text = task["status"]["message"]["parts"][0]["text"]
    assert "summary for the user" in text and "max turns (1)" in text


async def test_ag_ui_text_then_run_error(tmp_path):
    app, fm = _build(tmp_path)
    fm.script(tool_call("echo", {"text": "hi"}), reply("agui summary"))
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            frames = await run(c, run_body())
    types = [f["type"] for f in frames]
    assert types[-1] == "RUN_ERROR"
    deltas = [f["delta"] for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT"]
    assert "agui summary" in "".join(deltas)
    assert types.index("TEXT_MESSAGE_CONTENT") < types.index("RUN_ERROR")


# ── model clients ─────────────────────────────────────────────────────────

_TOOLS = [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]
_TOOL_HISTORY = [
    {"role": "user", "content": [{"text": "go"}]},
    {"role": "assistant", "content": [{"toolUse": {"toolUseId": "1", "name": "t", "input": {}}}]},
    {"role": "user", "content": [{"toolResult": {"toolUseId": "1", "content": [{"text": "x"}]}}]},
]


class _Boto:
    def __init__(self, raw):
        self.raw, self.requests = raw, []

    def converse(self, **req):
        self.requests.append(req)
        return self.raw


def _bedrock(raw):
    client = BedrockModelClient(
        region="us-east-1", model_arn="arn:aws:bedrock:us-east-1::foundation-model/t"
    )
    boto = _Boto(raw)
    client._boto_client = lambda: boto  # type: ignore[method-assign]
    return client, boto


_BEDROCK_RAW = {
    "stopReason": "tool_use",
    "usage": {"inputTokens": 1, "outputTokens": 1},
    "output": {"message": {"content": [
        {"text": "words"},
        {"toolUse": {"toolUseId": "2", "name": "t", "input": {}}},
    ]}},
}


async def test_bedrock_none_keeps_toolconfig_with_tool_history_and_drops_calls():
    client, boto = _bedrock(_BEDROCK_RAW)
    resp = await client.converse(
        system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=50, tool_choice="none"
    )
    assert "toolConfig" in boto.requests[0]
    assert boto.requests[0]["inferenceConfig"]["maxTokens"] == 50
    assert resp.tool_calls == [] and resp.text_segments == ["words"]


async def test_bedrock_none_without_tool_blocks_omits_toolconfig():
    client, boto = _bedrock(_BEDROCK_RAW)
    await client.converse(
        system="s", messages=[{"role": "user", "content": [{"text": "hi"}]}],
        tools=_TOOLS, tool_choice="none",
    )
    assert "toolConfig" not in boto.requests[0]


async def test_bedrock_auto_keeps_tool_calls():
    client, _ = _bedrock(_BEDROCK_RAW)
    resp = await client.converse(system="s", messages=_TOOL_HISTORY, tools=_TOOLS)
    assert len(resp.tool_calls) == 1


class _Completions:
    def __init__(self):
        self.requests = []

    async def create(self, **req):
        self.requests.append(req)
        msg = SimpleNamespace(content="ok", tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )


def _openai(**kw):
    client = OpenAIModelClient(model="m", api_key="k", **kw)
    comp = _Completions()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    return client, comp


async def test_openai_none_cap_is_min_of_max_tokens_and_operator_cap():
    # GH-155 AC: the summary call sends min(max_tokens, max_completion_tokens).
    client, comp = _openai(max_completion_tokens=500)
    await client.converse(
        system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=100, tool_choice="none"
    )
    req = comp.requests[0]
    assert req["tool_choice"] == "none" and req["max_completion_tokens"] == 100
    client, comp = _openai(max_completion_tokens=50)
    await client.converse(
        system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=100, tool_choice="none"
    )
    assert comp.requests[0]["max_completion_tokens"] == 50


async def test_openai_none_cap_fits_non_reasoning_models():
    # RT-002 (w045 round 7): gpt-4o / gpt-4o-mini reject max_completion_tokens
    # above 16,384 with a 400, which would turn every summary into the notice.
    # The default summary request (no operator cap) must stay the small
    # ruling-mandated output cap, with or without a reasoning_effort.
    for kw in ({}, {"reasoning_effort": "medium"}):
        client, comp = _openai(**kw)
        await client.converse(
            system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=1024,
            tool_choice="none",
        )
        cap = comp.requests[0]["max_completion_tokens"]
        assert cap == 1024 and cap <= 16_384
    assert comp.requests[0]["reasoning_effort"] == "medium"


def test_settings_reach_openai_reasoning_knobs(tmp_path, monkeypatch):
    # RT-002: env-configured operators must be able to set the reasoning
    # effort and the hard ceiling the summary cap is bounded by.
    pytest.importorskip("openai")  # _build_model_client probes the import

    s = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path), AGENT_NAME="a", OPENAI_MODEL="gpt-x",
        AGENT_SDK_OPENAI_REASONING_EFFORT="low",
        AGENT_SDK_OPENAI_MAX_COMPLETION_TOKENS="700",
    )
    agent = make_agent(s)
    client = agent._build_model_client(SimpleNamespace(get=lambda *a: None))
    assert isinstance(client, OpenAIModelClient)
    assert client._reasoning_effort == "low"
    assert client._max_completion_tokens == 700


async def test_openai_none_empty_length_logs_fixed_warning(caplog):
    client, comp = _openai()

    async def create(**req):
        comp.requests.append(req)
        msg = SimpleNamespace(content="", tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="length")],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    comp.create = create
    with caplog.at_level("WARNING", logger="agent_sdk.agent.openai_client"):
        resp = await client.converse(
            system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=100, tool_choice="none"
        )
    assert resp.text_segments == []
    assert any("summary call returned no text" in r.getMessage() for r in caplog.records)
    caplog.clear()
    with caplog.at_level("WARNING", logger="agent_sdk.agent.openai_client"):
        await client.converse(system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=100)
    assert not any("summary call" in r.getMessage() for r in caplog.records)


async def test_openai_none_keeps_configured_reasoning_and_never_invents_one():
    client, comp = _openai()
    await client.converse(
        system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=100, tool_choice="none"
    )
    assert "reasoning_effort" not in comp.requests[0]


async def test_openai_none_uses_operator_reasoning():
    client, comp = _openai(reasoning_effort="high")
    await client.converse(
        system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=100, tool_choice="none"
    )
    await client.converse(system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=100)
    assert comp.requests[0]["reasoning_effort"] == "high"
    assert comp.requests[1]["reasoning_effort"] == "high"


async def test_openai_auto_unchanged():
    client, comp = _openai()
    await client.converse(system="s", messages=_TOOL_HISTORY, tools=_TOOLS, max_tokens=100)
    req = comp.requests[0]
    assert req["tool_choice"] == "auto" and "max_completion_tokens" not in req


async def test_budget_exit_default_policies_realistic_turn_produces_summary():
    # RT-001 (w045 round 5): with DEFAULT policies and a realistic crossing
    # turn (199k counted input, far larger than the 1024 output cap), the
    # budget exit must still produce a real summary, not the fixed notice.
    model = FakeModelClient(
        [
            tool_call("unknown_tool", {"x": 1}, input_tokens=199_000, output_tokens=1_001),
            ModelResponse(
                text_segments=["found A and B; C still missing"], stop_reason="end_turn",
                input_tokens=200_500, output_tokens=40,
            ),
        ]
    )
    events = await _run(model, _msgs(), LoopPolicies())
    assert len(model.calls) == 2
    call = model.calls[-1]
    assert call["tool_choice"] == "none"
    assert call["max_tokens"] == LoopPolicies().final_summary_max_tokens
    done = events[-1]
    assert not done.ok and done.error == "task token budget exceeded"
    assert done.summary == "found A and B; C still missing"
    texts = [e.text for e in events if isinstance(e, TextEvent)]
    assert texts == ["found A and B; C still missing"]
    # The summary call's own usage is reported (spend stays visible).
    usage = [e for e in events if isinstance(e, UsageEvent)]
    assert usage[-1].input_tokens == 200_500 and usage[-1].output_tokens == 40


async def test_budget_exit_failed_summary_call_uses_notice():
    # The ONLY notice path on the budget exit: the summary call fails.
    model = FakeModelClient(
        [tool_call("unknown_tool", {"x": 1}, input_tokens=199_000, output_tokens=1_001)]
    )  # script exhausted on the summary call -> raises
    events = await _run(model, _msgs(), LoopPolicies())
    assert events[-1].summary.startswith("I reached my budget limit")
    assert not events[-1].ok and events[-1].error == "task token budget exceeded"


async def test_resumed_task_over_budget_makes_one_summary_call():
    # A task resumed already over budget made no call in this run_loop; it
    # still gets exactly one bounded summary call, never a normal turn.
    big = [{"role": "user", "content": [{"text": "x" * 40_000}]}]
    model = FakeModelClient([reply("partial")])
    events = [
        ev
        async for ev in run_loop(
            model=model, registry=REGISTRY, adapters={}, system="s", messages=big,
            policies=LoopPolicies(token_budget=1_000), spent_tokens=1_001,
        )
    ]
    assert len(model.calls) == 1
    assert model.calls[0]["tool_choice"] == "none" and model.calls[0]["max_tokens"] == 1024
    assert events[-1].summary == "partial" and "token budget" in events[-1].error


async def test_max_turns_with_exceeded_budget_still_summarizes():
    model = FakeModelClient(
        [
            tool_call("unknown_tool", {"x": 1}, input_tokens=125_000, output_tokens=125_000),
            reply("partial"),
        ]
    )
    events = await _run(model, _msgs(), LoopPolicies(max_turns=1, token_budget=200_000))
    assert len(model.calls) == 2 and model.calls[-1]["tool_choice"] == "none"
    assert "max turns" in events[-1].error and events[-1].summary == "partial"


async def test_final_summary_max_tokens_zero_sends_notice_without_call():
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1}), reply("never")])
    events = await _run(model, _msgs(), LoopPolicies(max_turns=1, final_summary_max_tokens=0))
    assert len(model.calls) == 1
    assert events[-1].summary.startswith("I reached my step limit")


async def test_max_turns_with_exceeded_deadline_makes_no_call():
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1}), reply("never")])

    def clock() -> float:
        return 10_000.0 if model.calls else 0.0

    events = [
        ev
        async for ev in run_loop(
            model=model, registry=REGISTRY, adapters={}, system="s", messages=_msgs(),
            policies=LoopPolicies(max_turns=1, deadline_seconds=1.0), clock=clock,
        )
    ]
    assert len(model.calls) == 1
    assert events[-1].error == "task deadline exceeded"


async def test_summary_failure_logs_type_without_text(caplog):
    class Boom(FakeModelClient):
        async def converse(self, **kw):
            if kw.get("tool_choice") == "none":
                raise TypeError("secret-token-123")
            return await super().converse(**kw)

    model = Boom([tool_call("unknown_tool", {"x": 1})])
    with caplog.at_level("WARNING"):
        await _run(model, _msgs(), LoopPolicies(max_turns=1))
    recs = [r for r in caplog.records if "final summary call failed" in r.getMessage()]
    assert recs and "TypeError" in recs[0].getMessage()
    assert "secret-token-123" not in caplog.text


def test_summary_cap_is_output_only():
    from agent_sdk.agent.loop import LoopPolicies, _summary_max_tokens

    # GH-155 ruling: output cap only; spend so far never shrinks or skips it.
    assert _summary_max_tokens(LoopPolicies()) == 1024
    assert _summary_max_tokens(LoopPolicies(max_output_tokens=500)) == 500
    assert _summary_max_tokens(LoopPolicies(final_summary_max_tokens=-5)) == 0


def test_settings_expose_final_summary_max_tokens(monkeypatch):
    from agent_sdk.config import BaseAgentSettings

    assert BaseAgentSettings.model_fields["final_summary_max_tokens"].alias == (
        "AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS"
    )
