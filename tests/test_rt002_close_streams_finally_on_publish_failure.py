"""RT-002 (runner.py:368-386): the deferred SUCCESS path's unguarded
terminal sequence — publish(artifact_frame) -> synthetic ToolResultEvent ->
DoneEvent(final=True) -> store.close_streams() — must guarantee
close_streams() runs even when an EARLIER step in that sequence raises (a
custom/persistent TaskStore whose publish() does a durable write that
fails). Before the fix, an exception from the artifact-frame publish() call
propagated straight out of the fire-and-forget background asyncio.Task
WITHOUT ever reaching store.close_streams() — every subscriber queue was
left un-sentinel-closed until the TTL sweep, not merely un-notified of the
terminal frame.

This is distinct from test_rt002b_deferred_terminal_frame_no_duplicate.py
(which drives a close_streams()-itself-raises store, where close_streams was
already the last statement executed either way) — this test drives a
publish()-raises-on-the-FIRST-post-guard-call store, which is the case the
original unguarded sequence dropped close_streams() entirely for.

Same treatment applies to run_task_worker's `else:` terminal publish, tested
separately below: a publish() failure on the terminal DoneEvent must not
prevent store.close_streams() from running when deferred_launched is False.

No unittest.mock/MagicMock — a real InMemoryTaskStore subclass whose
publish() raises on a specific frame, driven through the real
run_task_worker / _run_deferred_background.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import ArtifactEvent, DoneEvent
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import StreamItem, new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _GoodResult(BaseModel):
    data_type: str = "rt002_finally_result"
    value: str = "ok"


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


async def _drain_events(sub: Any, timeout: float = 3.0) -> list[Any]:
    async def _loop() -> list[Any]:
        items: list[Any] = []
        while True:
            item = await sub.get()
            if item is None:  # close sentinel
                return items
            items.append(item)

    return await asyncio.wait_for(_loop(), timeout=timeout)


# ── deferred background path ──

_deferred_tools = ToolSet()


async def _job() -> _GoodResult:
    await asyncio.sleep(0)
    return _GoodResult()


@_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt002_finally_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle resolves cleanly; the artifact-frame publish
    is what fails."""
    return DeferredResult(handle=_job())


_DEFERRED_REGISTRY = ToolRegistry([_deferred_tools], {})


class _ArtifactPublishExplodesOnce(InMemoryTaskStore):
    """Simulates a persistent-store durable-write failure on the FIRST
    post-guard publish call (the artifact frame) in the deferred success
    path — before close_streams() is ever reached in the old, unguarded
    code."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._raised = False

    def publish(self, task_id: str, event: Any) -> None:
        if (
            not self._raised
            and isinstance(event, StreamItem)
            and isinstance(event.event, ArtifactEvent)
        ):
            self._raised = True
            raise RuntimeError("simulated durable publish failure on artifact frame")
        super().publish(task_id, event)


@pytest.mark.asyncio
async def test_deferred_background_closes_streams_when_artifact_publish_raises() -> None:
    store = _ArtifactPublishExplodesOnce()
    record = _make_record(store)
    task_id = record.task.id
    sub = store.subscribe(task_id)

    model = FakeModelClient().script(tool_call("rt002_finally_deferred_tool", {}))

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

    # RT-001 (round 6): a pre-terminal publish failure must NOT escape the
    # fire-and-forget background task and strand the A2A task in WORKING.
    # Mirroring run_task_worker's `except Exception → _fail`, the background
    # awaiter catches the artifact-frame publish failure and transitions the
    # task to FAILED with the FIRST terminal frame, then closes streams — so
    # awaiting bg_task returns normally rather than propagating the RuntimeError.
    assert record.bg_task is not None
    await record.bg_task  # handled internally → no propagation

    assert record.task.status.state == TaskState.FAILED, (
        "RT-001: a pre-terminal publish failure on the deferred success path "
        "must transition the task to FAILED (mirroring the synchronous worker), "
        f"not strand it in WORKING — got {record.task.status.state!r}"
    )

    items = await _drain_events(sub)
    assert items, (
        "RT-002: store.close_streams() must run even when an earlier publish() "
        "in the deferred success path raises — subscribers must not be left "
        "un-sentinel-closed until the TTL sweep"
    )
    # RT-001: a terminal final:true DoneEvent(ok=False) frame must have been
    # delivered BEFORE the sentinel — the WORKING-strand fix means the stream
    # never sentinel-closes without a terminal frame.
    terminal = [
        it for it in items
        if getattr(it, "final", False) and isinstance(it.event, DoneEvent)
    ]
    assert terminal and terminal[-1].event.ok is False, (
        "RT-001: the deferred pre-terminal publish failure must deliver a "
        f"terminal DoneEvent(ok=False) frame before closing streams; got {items!r}"
    )


# ── synchronous run_task_worker path ──

_sync_tools = ToolSet()


@_sync_tools.tool(tier=1, emits=_GoodResult)
async def rt002_finally_sync_tool() -> _GoodResult:
    return _GoodResult()


_SYNC_REGISTRY = ToolRegistry([_sync_tools], {})


class _DoneEventPublishExplodesOnce(InMemoryTaskStore):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._raised = False

    def publish(self, task_id: str, event: Any) -> None:
        if (
            not self._raised
            and isinstance(event, StreamItem)
            and event.final
            and isinstance(event.event, DoneEvent)
        ):
            self._raised = True
            raise RuntimeError("simulated durable publish failure on terminal frame")
        super().publish(task_id, event)


@pytest.mark.asyncio
async def test_sync_worker_closes_streams_when_terminal_publish_raises() -> None:
    store = _DoneEventPublishExplodesOnce()
    record = _make_record(store)
    task_id = record.task.id
    sub = store.subscribe(task_id)

    model = FakeModelClient().script(tool_call("rt002_finally_sync_tool", {}), reply("done"))

    with pytest.raises(RuntimeError):
        await run_task_worker(
            store=store,
            record=record,
            model=model,
            registry=_SYNC_REGISTRY,
            adapters={},
            skills=None,
            system="test system prompt",
            capabilities=_CAPABILITIES,
            policies=LoopPolicies(),
        )

    closed = await _drain_to_close(sub)
    assert closed, (
        "RT-002: store.close_streams() must run even when the terminal "
        "DoneEvent publish() raises in run_task_worker's else-clause"
    )
