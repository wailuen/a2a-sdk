"""F1 (post-w034 protocol re-audit, independently raised by both a2a-advisor
and a2ui-advisor): store.close_streams() calls inside the FAILURE-HANDLING
paths themselves — ``_run_deferred_background``'s ``_fail()``,
``run_task_worker``'s ``except AgentError``/``except Exception`` handlers,
and ``tasks_cancel``'s terminal publish — were not guarded by try/finally.
A publish() failure INSIDE one of those already-failing paths (not merely a
publish() failure that TRIGGERS entry into the path, which
test_rt002_close_streams_finally_on_publish_failure.py already covers) could
therefore itself skip stream teardown, stranding SSE subscribers un-sentinel-
closed until the TTL sweep — a "double failure" the existing RT-002 tests
never drove because their stores raise on exactly ONE call.

Each test here uses a real InMemoryTaskStore subclass whose publish() raises
on EVERY matching call (not just the first), so the failure-handling code's
OWN publish attempt also fails — the specific scenario the try/finally
guards added for F1 close.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Response
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import DoneEvent
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import StreamItem, new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.routes.a2a import tasks_cancel
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


async def _drain_to_close(sub: Any, timeout: float = 3.0) -> bool:
    async def _loop() -> bool:
        while True:
            item = await sub.get()
            if item is None:  # close sentinel
                return True

    return await asyncio.wait_for(_loop(), timeout=timeout)


# ── run_task_worker's generic `except Exception` handler ──


class _PublishAlwaysExplodes(InMemoryTaskStore):
    """Every StreamItem publish() call raises — unlike the existing RT-002
    stores (which raise exactly once), this drives a SECOND failure inside
    the except-handler's own terminal publish, exercising the try/finally
    guard directly rather than the "raises once, guard never re-entered"
    case those tests cover."""

    def publish(self, task_id: str, event: Any) -> None:
        if isinstance(event, StreamItem):
            raise RuntimeError("simulated persistent durable-write failure")
        super().publish(task_id, event)


@pytest.mark.asyncio
async def test_run_task_worker_except_exception_closes_streams_on_double_failure() -> None:
    store = _PublishAlwaysExplodes()
    record = _make_record(store)
    sub = store.subscribe(record.task.id)

    model = FakeModelClient()  # no script queued: run_loop's first publish already raises

    with pytest.raises(RuntimeError):
        await run_task_worker(
            store=store,
            record=record,
            model=model,
            registry=ToolRegistry([], {}),
            adapters={},
            skills=None,
            system="test system prompt",
            capabilities=_CAPABILITIES,
            policies=LoopPolicies(),
        )

    assert record.task.status.state == TaskState.FAILED
    closed = await _drain_to_close(sub)
    assert closed, (
        "F1: store.close_streams() must run even when the except-handler's "
        "own terminal publish() ALSO raises (double failure), not just when "
        "a single earlier publish() triggers entry into the handler"
    )


# ── _run_deferred_background's CancelledError -> _fail() double failure ──


class _GoodResult(BaseModel):
    data_type: str = "f1_double_failure_result"
    value: str = "ok"


_deferred_tools = ToolSet()


@_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def f1_cancel_deferred_tool() -> DeferredResult:
    async def _job() -> _GoodResult:
        await asyncio.sleep(30)
        return _GoodResult()

    return DeferredResult(handle=asyncio.ensure_future(_job()))


_DEFERRED_REGISTRY = ToolRegistry([_deferred_tools], {})


class _ArmedPublishAlwaysExplodes(InMemoryTaskStore):
    """Raises on every StreamItem publish() call only once armed — letting
    the initial WORKING status publish + DeferredEvent launch succeed
    normally, then simulating the persistent store going down entirely by
    the time the background task's ``_fail()`` runs (both of its publish
    calls fail, not just one)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.armed = False

    def publish(self, task_id: str, event: Any) -> None:
        if self.armed and isinstance(event, StreamItem):
            raise RuntimeError("simulated persistent durable-write failure")
        super().publish(task_id, event)


@pytest.mark.asyncio
async def test_deferred_background_cancel_fail_closes_streams_on_double_failure() -> None:
    store = _ArmedPublishAlwaysExplodes()
    record = _make_record(store)
    sub = store.subscribe(record.task.id)

    model = FakeModelClient().script(tool_call("f1_cancel_deferred_tool", {}))

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
    await asyncio.sleep(0)  # let the background task start awaiting the handle
    store.armed = True
    record.bg_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await record.bg_task

    closed = await _drain_to_close(sub)
    assert closed, (
        "F1: _fail()'s finally must run store.close_streams() even when BOTH "
        "of its own publish() calls raise during CancelledError handling — "
        "the exact 'second failure inside the failure path' scenario the "
        "existing single-raise RT-002 tests don't exercise"
    )


# ── tasks_cancel route: terminal publish failure ──


class _CancelPublishExplodes(InMemoryTaskStore):
    def publish(self, task_id: str, event: Any) -> None:
        raise RuntimeError("simulated durable publish failure on cancel frame")


class _FakeApp:
    def __init__(self, store: InMemoryTaskStore) -> None:
        self.state = SimpleNamespace(task_store=store, cors_origins={"https://claude.ai"})


class _FakeRequest:
    def __init__(self, store: InMemoryTaskStore) -> None:
        self.headers: dict[str, str] = {}
        self.app = _FakeApp(store)


@pytest.mark.asyncio
async def test_tasks_cancel_closes_streams_when_terminal_publish_raises() -> None:
    store = _CancelPublishExplodes()
    record = _make_record(store)
    sub = store.subscribe(record.task.id)
    request = _FakeRequest(store)

    with pytest.raises(RuntimeError):
        await tasks_cancel(record.task.id, request, Response(), identity=_IDENTITY)

    closed = await _drain_to_close(sub)
    assert closed, (
        "F1: tasks_cancel must run store.close_streams() even when its "
        "terminal publish() raises"
    )
