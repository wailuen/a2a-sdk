"""RT-002 (w034/RT-002): a FAILED task must never retain a never-delivered
artifact.

Finding: both ``runner._run_deferred_background``'s success path and
``run_task_worker``'s ``ArtifactEvent`` branch mutated
``record.task.artifacts``/``task.artifacts`` to APPEND the artifact BEFORE
``TaskArtifactUpdateEvent(...).wire()`` serialised the frame. If ``.wire()``
(or the subsequent publish) raised, the task transitioned to FAILED via the
surrounding except handler, but the just-appended artifact remained on the
now-FAILED task record — an artifact that was never actually emitted on any
stream. Fixed by serialising the wire frame BEFORE mutating
``task.artifacts`` in both call sites, so a serialisation failure can no
longer strand a half-delivered artifact on a FAILED task.

Forces ``.wire()`` to raise via ``monkeypatch`` (a real attribute swap, not a
Mock object) on an otherwise successful artifact build, then asserts the
FAILED task's ``artifacts`` list is empty. No unittest.mock/MagicMock — real
run_task_worker + InMemoryTaskStore, mirroring
test_rt001_deferred_artifact_build_failure.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import StreamItem, new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskArtifactUpdateEvent, TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _GoodResult(BaseModel):
    data_type: str = "rt002_result"
    value: str = "ok"


def _raise_on_wire(self: TaskArtifactUpdateEvent) -> dict[str, Any]:
    raise RuntimeError("simulated wire() failure — must not raise before this point")


async def _wait_for_state(
    store: InMemoryTaskStore,
    task_id: str,
    states: tuple[str, ...] = (TaskState.COMPLETED, TaskState.FAILED),
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
            raise AssertionError(f"task stuck in state {state!r} after {timeout}s")
        await asyncio.sleep(0.02)


# ── deferred (async-generator/coroutine long-running) path ──

_deferred_tools = ToolSet()


async def _rt002_job() -> _GoodResult:
    await asyncio.sleep(0)
    return _GoodResult()


@_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt002_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle resolves cleanly — the FAILURE is injected
    at TaskArtifactUpdateEvent.wire(), not at artifact-build time."""
    return DeferredResult(handle=_rt002_job())


_DEFERRED_REGISTRY = ToolRegistry([_deferred_tools], {})


async def test_deferred_background_wire_failure_does_not_strand_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TaskArtifactUpdateEvent, "wire", _raise_on_wire)

    store = InMemoryTaskStore()
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})

    model = FakeModelClient().script(tool_call("rt002_deferred_tool", {}))

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

    final_state = await _wait_for_state(store, task.id)
    assert final_state == TaskState.FAILED, (
        f"expected FAILED when TaskArtifactUpdateEvent.wire() raises, got {final_state!r}"
    )

    rec = store.get(task.id)
    assert rec is not None
    assert not (rec.task.artifacts or []), (
        "RT-002: a FAILED deferred task must not retain an artifact that was "
        f"never delivered on any stream, got {rec.task.artifacts!r}"
    )


# ── synchronous (non-deferred) ArtifactEvent path in run_task_worker ──

_sync_tools = ToolSet()


@_sync_tools.tool(tier=1, emits=_GoodResult)
async def rt002_sync_tool() -> _GoodResult:
    return _GoodResult()


_SYNC_REGISTRY = ToolRegistry([_sync_tools], {})


async def test_sync_worker_wire_failure_does_not_strand_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TaskArtifactUpdateEvent, "wire", _raise_on_wire)

    store = InMemoryTaskStore()
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})

    model = FakeModelClient().script(tool_call("rt002_sync_tool", {}))

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

    final_state = await _wait_for_state(store, task.id)
    assert final_state == TaskState.FAILED, (
        f"expected FAILED when TaskArtifactUpdateEvent.wire() raises, got {final_state!r}"
    )

    rec = store.get(task.id)
    assert rec is not None
    assert not (rec.task.artifacts or []), (
        "RT-002: a FAILED synchronous task must not retain an artifact that "
        f"was never delivered on any stream, got {rec.task.artifacts!r}"
    )


# ── publish()-raises sub-case (round-4 RT-002 gap) ──
#
# The wave's original reorder serialized the wire frame BEFORE the append, so
# a .wire() failure could no longer strand an artifact (tests above). But it
# left the append BEFORE publish(), so a publish() failure — a persistent
# TaskStore whose durable write fails — still flipped the task to FAILED (sync
# path) / propagated out of the background task (deferred path) with a
# never-delivered artifact retained. The fix appends only AFTER publish()
# succeeds. These two tests pin that sub-case for both call sites.


class _ArtifactFramePublishExplodesOnce(InMemoryTaskStore):
    """Raises exactly once, on the StreamItem that carries the ArtifactEvent
    frame — the artifact-delivery publish() — simulating a durable-store write
    failure. Later frames (the terminal DoneEvent) publish normally, so the
    task can still reach a terminal FAILED state and close its streams."""

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


async def test_sync_worker_publish_failure_does_not_strand_artifact() -> None:
    store = _ArtifactFramePublishExplodesOnce()
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})

    model = FakeModelClient().script(tool_call("rt002_sync_tool", {}), reply("done"))

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

    final_state = await _wait_for_state(store, task.id)
    assert final_state == TaskState.FAILED, (
        f"expected FAILED when the ArtifactEvent publish() raises, got {final_state!r}"
    )

    rec = store.get(task.id)
    assert rec is not None
    assert not (rec.task.artifacts or []), (
        "RT-002: a FAILED synchronous task must not retain an artifact whose "
        f"delivery publish() raised, got {rec.task.artifacts!r}"
    )


async def test_deferred_background_publish_failure_does_not_strand_artifact() -> None:
    store = _ArtifactFramePublishExplodesOnce()
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})

    model = FakeModelClient().script(tool_call("rt002_deferred_tool", {}))

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

    # RT-001 (round 6): the artifact-frame publish() raises inside the
    # fire-and-forget background task, but the awaiter now CATCHES it and
    # transitions the task to FAILED (mirroring run_task_worker's
    # `except Exception → _fail`), so awaiting bg_task returns normally rather
    # than propagating the RuntimeError. The append runs only AFTER a
    # successful publish(), so no undelivered artifact is stranded on the
    # record either way.
    assert record.bg_task is not None
    await record.bg_task  # handled internally → no propagation

    final_state = await _wait_for_state(store, task.id)
    assert final_state == TaskState.FAILED, (
        "RT-001: a deferred task whose artifact-frame publish() raised must "
        f"reach FAILED, not strand in WORKING — got {final_state!r}"
    )

    rec = store.get(task.id)
    assert rec is not None
    assert not (rec.task.artifacts or []), (
        "RT-002: a deferred task whose artifact-frame publish() raised must "
        f"not retain the never-delivered artifact, got {rec.task.artifacts!r}"
    )
