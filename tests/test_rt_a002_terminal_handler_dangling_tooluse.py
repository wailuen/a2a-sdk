"""RT-A-002: run_task_worker's ``except AgentError`` terminal handler must
repair a dangling assistant ``toolUse`` tail in ``record.messages`` before
flipping the task to FAILED — exactly like GH-150's cancel path, RT-002's
deferred-background path, and RT-005's ``except Exception`` /
``build_artifact`` sibling (test_rt005_midturn_build_artifact_failure_
dangling_tool_use.py).

Root cause: ``store.mark_interrupted`` raises ``AgentError`` when the
store's ``max_interrupted`` cap is hit (§5.2) — reachable mid-turn via an
interrupting tool call, from INSIDE ``run_task_worker``'s own for-loop
(``InterruptEvent`` branch), which is not itself try/excepted. The
``AgentError`` therefore propagates straight to the outer
``except AgentError`` handler while ``record.messages`` still ends on the
assistant ``toolUse`` fold for that call. FAILED is terminal, so
``context_messages()`` would replay that dangling-toolUse transcript
verbatim into the next ``contextId`` continuation turn, which a
Converse-API-shaped backend (Bedrock) rejects outright.

Drives ``run_task_worker`` directly (bypassing ``Agent.build_app()`` /
FastAPI entirely — matching test_rt005's own low-level pattern) with a real
``InMemoryTaskStore``, a real ``ToolRegistry``, and ``FakeModelClient``: a
tool that raises ``ToolInterrupt`` against a store constructed with
``max_interrupted=0``, so ``mark_interrupted`` raises unconditionally.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.loop import LoopPolicies, ToolInterrupt
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _EmptyInput(BaseModel):
    pass


_rt_a002_tools = ToolSet()


@_rt_a002_tools.tool(tier=2, title="Interrupt Tool")
async def rt_a002_interrupt_tool(inp: _EmptyInput) -> dict[str, Any]:
    """Always interrupts — used to reach store.mark_interrupted mid-turn."""
    raise ToolInterrupt(reason="confirmation", message="confirm?")


_RT_A002_REGISTRY = ToolRegistry([_rt_a002_tools], {})


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


def _tool_use_ids(message: dict[str, Any]) -> set[str]:
    return {
        block["toolUse"]["toolUseId"]
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolUse" in block
    }


def _tool_result_ids(message: dict[str, Any]) -> set[str]:
    return {
        block["toolResult"]["toolUseId"]
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolResult" in block
    }


def assert_no_dangling_tool_use(messages: list[dict[str, Any]]) -> None:
    """Every assistant toolUse turn must be immediately followed by a
    message carrying a matching toolResult for every toolUseId — the
    Converse-API-shaped invariant contextId continuation replay depends on."""
    for i, message in enumerate(messages):
        ids = _tool_use_ids(message)
        if not ids:
            continue
        assert i + 1 < len(messages), (
            f"assistant toolUse turn at index {i} has no following message "
            f"(dangling toolUseId(s): {ids!r})"
        )
        result_ids = _tool_result_ids(messages[i + 1])
        missing = ids - result_ids
        assert not missing, (
            f"toolUseId(s) {missing!r} at index {i} have no matching "
            f"toolResult in the immediately-following message"
        )


def assert_alternates(messages: list[dict[str, Any]]) -> None:
    """No two consecutive entries in ``messages`` may share a ``role`` — the
    exact shape Bedrock's Converse API rejects outright."""
    for prev, cur in zip(messages, messages[1:]):
        assert prev.get("role") != cur.get("role"), (
            f"two consecutive {cur.get('role')!r} messages: {prev!r} then {cur!r}"
        )


@pytest.mark.asyncio
async def test_agent_error_mid_tool_call_repairs_dangling_tool_use() -> None:
    store = InMemoryTaskStore(max_interrupted=0)
    record = _make_record(store)
    task_id = record.task.id

    # A scripted follow-up reply proves the fix actually fired rather than
    # the loop coincidentally never reaching a second model turn.
    model = FakeModelClient().script(
        tool_call("rt_a002_interrupt_tool", {}), reply("unreachable")
    )

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_RT_A002_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    rec = store.get(task_id)
    assert rec is not None
    assert rec.task.status.state == TaskState.FAILED, (
        f"expected FAILED once the max_interrupted cap raises AgentError, "
        f"got {rec.task.status.state!r}"
    )
    error = rec.task.status.error
    assert error is not None

    messages = rec.messages
    assert messages, "expected the folded assistant toolUse turn to survive"
    assert messages[-1].get("role") != "user", (
        "record.messages must never be left ending on 'user' (GH-147 AC3) — "
        f"got {messages[-1]!r}"
    )
    assert_no_dangling_tool_use(messages)
    assert_alternates(messages)


@pytest.mark.asyncio
async def test_agent_error_repair_content_is_fixed_not_err_message() -> None:
    """SI-2: the synthetic toolResult text must be a fixed SDK-authored
    string, never AgentError.message verbatim — the AgentError instance
    raised by mark_interrupted is a generic rate-limit message today, but the
    repair content must not be coupled to whatever a future AgentError raise
    site happens to say."""
    store = InMemoryTaskStore(max_interrupted=0)
    record = _make_record(store)
    task_id = record.task.id
    model = FakeModelClient().script(tool_call("rt_a002_interrupt_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_RT_A002_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    rec = store.get(task_id)
    assert rec is not None
    tool_result_msg = rec.messages[-2]
    assert tool_result_msg["role"] == "user"
    result_blocks = [b["toolResult"] for b in tool_result_msg["content"] if "toolResult" in b]
    assert result_blocks
    for b in result_blocks:
        text = b["content"][0].get("text", "")
        assert "too many tasks awaiting input" not in text, (
            f"repair content must be a fixed constant, not err.message verbatim: {text!r}"
        )
