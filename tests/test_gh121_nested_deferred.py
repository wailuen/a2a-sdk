"""GH-121 / RT-001: a deferred tool's handle resolving to ANOTHER
``DeferredResult`` (nested deferral) must never leak the nested object as a
terminal value, and the bounded-resolution contract must be IDENTICAL to
``ToolEntry.invoke_any`` (MCP ``tools/call``, admin try-tool).

History: GH-121 originally found that ``_run_deferred_background`` awaited
``event.deferred.handle`` once into ``raw_result`` and never rechecked
whether the awaited value was itself a ``DeferredResult`` — the nested value
flowed into ``ArtifactEvent(model=raw_result)`` and the task falsely
transitioned to COMPLETED. The original fix made ANY nesting fatal on this
surface, which then diverged from ``invoke_any`` (GH-120), which tolerates
one level of nesting and only fails on a second (RT-001 finding).

RT-001 unifies the two: both surfaces now route through the shared
``agent_sdk.agent.registry.resolve_deferred_result`` helper, so:
  - single-level nesting (handle resolves to one more ``DeferredResult``,
    whose own handle resolves to a plain value) is fully resolved →
    COMPLETED, matching ``invoke_any``'s ``isError: false``.
  - double-level nesting raises ``AgentError`` internally → FAILED,
    matching ``invoke_any``'s ``isError: true``.

No unittest.mock.patch / MagicMock / AsyncMock. Uses FakeModelClient and the
real run_task_worker + InMemoryTaskStore.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import run_task_worker, new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call


_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


def _make_store() -> InMemoryTaskStore:
    return InMemoryTaskStore()


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


async def _run_worker(
    store: InMemoryTaskStore,
    record: Any,
    model: FakeModelClient,
    registry: ToolRegistry,
) -> None:
    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=registry,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )


async def _wait_for_state(
    store: InMemoryTaskStore,
    task_id: str,
    states: tuple[str, ...] = ("completed", "failed"),
    timeout: float = 5.0,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        record = store.get(task_id)
        assert record is not None, "task record evicted during wait"
        state = record.task.status.state
        if state in states:
            return state
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"task stuck in state {state!r} after {timeout}s; expected one of {states}"
            )
        await asyncio.sleep(0.02)


# ── single-level nesting: must fully resolve to COMPLETED ──

single_nested_tools = ToolSet()


async def _single_inner_job() -> str:
    await asyncio.sleep(0)
    return "single-nested-resolved"


async def _single_outer_job() -> DeferredResult:
    """Handle resolves to ANOTHER DeferredResult instead of a plain value."""
    await asyncio.sleep(0)
    return DeferredResult(handle=_single_inner_job())


@single_nested_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def single_nested_deferred_tool() -> DeferredResult:
    """Tool whose handle resolves to exactly one nested DeferredResult."""
    return DeferredResult(handle=_single_outer_job())


SINGLE_NESTED_REGISTRY = ToolRegistry([single_nested_tools], {})


@pytest.mark.asyncio
async def test_single_nested_deferred_result_resolves_to_completed() -> None:
    """RT-001: one level of nesting must fully resolve, mirroring invoke_any's
    ``test_invoke_any_resolves_single_nested_deferred_result`` — the SAME tool
    contract must not be transport-dependent."""
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(
        tool_call("single_nested_deferred_tool", {}),
    )

    await _run_worker(store, record, model, SINGLE_NESTED_REGISTRY)

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.COMPLETED, (
        f"expected COMPLETED for single-level nested DeferredResult "
        f"(matches invoke_any's tolerance), got {final_state!r}"
    )

    rec = store.get(task_id)
    assert rec is not None
    assert rec.task.artifacts, "expected an artifact carrying the resolved value"
    part = rec.task.artifacts[-1].parts[0]
    text = getattr(getattr(part, "root", part), "text", None)
    assert text is not None and "single-nested-resolved" in text, (
        f"expected the fully-resolved innermost value in the artifact text, got {text!r}"
    )


# ── double-level nesting: must FAIL cleanly ──

double_nested_tools = ToolSet()


async def _double_inner_job() -> str:
    await asyncio.sleep(0)
    return "should-never-surface"


async def _double_middle_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_double_inner_job())


async def _double_outer_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_double_middle_job())


@double_nested_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def double_nested_deferred_tool() -> DeferredResult:
    """Tool whose handle resolves through TWO nested DeferredResults."""
    return DeferredResult(handle=_double_outer_job())


DOUBLE_NESTED_REGISTRY = ToolRegistry([double_nested_tools], {})


@pytest.mark.asyncio
async def test_double_nested_deferred_result_transitions_to_failed() -> None:
    """A handle resolving through two nested DeferredResults must FAIL, not
    COMPLETE — mirroring invoke_any's
    ``test_invoke_any_raises_on_doubly_nested_deferred_result``."""
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(
        tool_call("double_nested_deferred_tool", {}),
    )

    await _run_worker(store, record, model, DOUBLE_NESTED_REGISTRY)

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.FAILED, (
        f"expected FAILED for double-nested DeferredResult, got {final_state!r}"
    )

    rec = store.get(task_id)
    assert rec is not None
    error = rec.task.status.error
    assert error is not None, "expected WireError on FAILED task"

    # SI-2: no raw object repr / internal exception text leaked.
    assert "DeferredResult" not in error.message, (
        f"error message must not leak the DeferredResult repr: {error.message!r}"
    )

    # Core regression assertion: no artifact carrying the raw nested
    # DeferredResult (or its str()) may ever have been appended.
    for artifact in rec.task.artifacts or []:
        for part in artifact.parts:
            part_obj = getattr(part, "root", part)
            text = getattr(part_obj, "text", None)
            if text is not None:
                assert "DeferredResult" not in text, (
                    f"raw DeferredResult repr leaked into TextPart: {text!r}"
                )
                assert "should-never-surface" not in text, (
                    f"innermost value must never surface past the nesting bound: {text!r}"
                )
            data = getattr(part_obj, "data", None)
            if data is not None:
                # Must be JSON-serializable (i.e. no raw DeferredResult object
                # ever reached the DataPart / sse_data()).
                json.dumps(data)
