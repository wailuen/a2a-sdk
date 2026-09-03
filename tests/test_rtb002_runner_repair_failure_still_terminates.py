"""RT-B-002: repair_dangling_tool_use(store=...) was unguarded at 3 of its 5
call sites inside agent/runner.py — _run_deferred_background's ``_fail``
closure, and run_task_worker's ``except AgentError``/``except Exception``
terminal handlers — all three sitting BEFORE the try/finally that guarantees
the terminal FAILED transition, the terminal publish, and close_streams.

A durable TaskStore whose persist_messages override raises on its own write
failure (the exact RT-005 flush repair_dangling_tool_use performs) escaped
out of each of these three sites, through the fire-and-forget background
asyncio.Task or straight out of run_task_worker: the task never reached
FAILED, close_streams never ran, and any SSE subscriber hung until the TTL
sweep.

Mirrors tests/test_rtb002_cancel_repair_failure_still_publishes_final.py's
persist_messages-raises store, but drives agent/runner.py's own three sites
directly through run_task_worker/_run_deferred_background (matching
test_rt003_deferred_exception_enrichment.py's and
test_rt_a002_terminal_handler_dangling_tooluse.py's low-level style) rather
than routes/a2a.py's tasks_cancel.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import DoneEvent
from agent_sdk.agent.loop import LoopPolicies, ToolInterrupt
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _RaisesOnPersistMessages(InMemoryTaskStore):
    """Simulates a durable store's override of the RT-005 write hook
    (TaskStore.persist_messages) failing on its own write — the exact
    failure repair_dangling_tool_use's trailing flush can hit."""

    def persist_messages(self, record: TaskRecord) -> None:
        raise RuntimeError("simulated durable persist_messages failure")


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


def _has_dangling_tool_use(messages: list[dict[str, Any]]) -> bool:
    if not messages or messages[-1].get("role") != "assistant":
        return False
    return any(
        isinstance(block, dict) and "toolUse" in block
        for block in messages[-1].get("content", [])
    )


async def _drain_to_close(sub: Any, timeout: float = 3.0) -> bool:
    async def _loop() -> bool:
        while True:
            item = await sub.get()
            if item is None:  # close sentinel
                return True

    return await asyncio.wait_for(_loop(), timeout=timeout)


# ── site 1: _run_deferred_background's `_fail` closure ─────────────────────

_deferred_tools = ToolSet()


async def _exploding_job() -> None:
    await asyncio.sleep(0)
    raise ValueError("simulated deferred handle failure")


@_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rtb002_exploding_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle raises — routes through the
    ``except Exception as exc: _fail(...)`` branch of
    ``_run_deferred_background``."""
    return DeferredResult(handle=_exploding_job())


_DEFERRED_REGISTRY = ToolRegistry([_deferred_tools], {})


@pytest.mark.asyncio
async def test_deferred_fail_survives_persist_messages_failure() -> None:
    store = _RaisesOnPersistMessages()
    record = _make_record(store)
    sub = store.subscribe(record.task.id)

    model = FakeModelClient().script(tool_call("rtb002_exploding_deferred_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_DEFERRED_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    assert record.bg_task is not None
    await record.bg_task  # RT-B-002: the persist_messages failure must not propagate

    assert record.task.status.state == TaskState.FAILED, (
        "RT-B-002: a persist_messages failure inside _fail's repair call must "
        f"still reach FAILED, not strand the task in WORKING — got "
        f"{record.task.status.state!r}"
    )
    assert not _has_dangling_tool_use(record.messages), (
        "the in-memory repair (append + bridge) happens BEFORE the store "
        "flush inside repair_dangling_tool_use, so it must have landed even "
        "though the trailing persist_messages call failed"
    )

    closed = await _drain_to_close(sub)
    assert closed, (
        "RT-B-002: _fail's finally must still close_streams when its own "
        "repair_dangling_tool_use call raises from persist_messages"
    )


# ── site 2: run_task_worker's `except AgentError` handler ──────────────────

_interrupt_tools = ToolSet()


class _EmptyInput(BaseModel):
    pass


@_interrupt_tools.tool(tier=2, title="Interrupt Tool")
async def rtb002_interrupt_tool(inp: _EmptyInput) -> dict[str, Any]:
    """Always interrupts — used to reach store.mark_interrupted mid-turn,
    which raises AgentError when max_interrupted=0."""
    raise ToolInterrupt(reason="confirmation", message="confirm?")


_INTERRUPT_REGISTRY = ToolRegistry([_interrupt_tools], {})


class _RaisesOnPersistMessagesCapped(_RaisesOnPersistMessages):
    def __init__(self) -> None:
        super().__init__(max_interrupted=0)


@pytest.mark.asyncio
async def test_agent_error_handler_survives_persist_messages_failure() -> None:
    store = _RaisesOnPersistMessagesCapped()
    record = _make_record(store)
    sub = store.subscribe(record.task.id)

    model = FakeModelClient().script(tool_call("rtb002_interrupt_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_INTERRUPT_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    assert record.task.status.state == TaskState.FAILED, (
        "RT-B-002: a persist_messages failure inside the except-AgentError "
        f"handler's repair call must still reach FAILED — got "
        f"{record.task.status.state!r}"
    )
    assert not _has_dangling_tool_use(record.messages), (
        "the in-memory repair must have landed despite the durable flush failing"
    )

    closed = await _drain_to_close(sub)
    assert closed, (
        "RT-B-002: the except-AgentError handler must still close_streams "
        "when its own repair_dangling_tool_use call raises from "
        "persist_messages"
    )


# ── site 3: run_task_worker's `except Exception` handler ───────────────────

_nonserializable_tools = ToolSet()


class _NonSerializablePayload:
    """Renders fine via str() but is not JSON-serializable — makes
    build_artifact raise ValueError mid-turn, reaching run_task_worker's
    generic ``except Exception`` handler."""

    def __str__(self) -> str:  # noqa: D401
        return "renders fine but is not JSON-serializable"


@_nonserializable_tools.tool(tier=1, emits=_NonSerializablePayload)
async def rtb002_nonserializable_tool() -> _NonSerializablePayload:
    return _NonSerializablePayload()


_NONSERIALIZABLE_REGISTRY = ToolRegistry([_nonserializable_tools], {})


@pytest.mark.asyncio
async def test_generic_exception_handler_survives_persist_messages_failure() -> None:
    store = _RaisesOnPersistMessages()
    record = _make_record(store)
    sub = store.subscribe(record.task.id)

    model = FakeModelClient().script(tool_call("rtb002_nonserializable_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_NONSERIALIZABLE_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    assert record.task.status.state == TaskState.FAILED, (
        "RT-B-002: a persist_messages failure inside the except-Exception "
        f"handler's repair call must still reach FAILED — got "
        f"{record.task.status.state!r}"
    )
    error = record.task.status.error
    assert error is not None and error.code == -32006

    closed = await _drain_to_close(sub)
    assert closed, (
        "RT-B-002: the except-Exception handler must still close_streams "
        "when its own repair_dangling_tool_use call raises from "
        "persist_messages"
    )
