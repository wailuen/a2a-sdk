"""RT-001: the deferred SUCCESS path must degrade like the synchronous worker.

The background awaiter (``runner._run_deferred_background``) resolves the
deferred handle and then builds + publishes a terminal artifact. That
build/serialise/publish block used to run OUTSIDE any try/except: a raise from
``build_artifact`` (``translate`` / ``_validate_a2ui_wire`` / a domain card's
``wire()``) or ``TaskArtifactUpdateEvent.wire()`` escaped the fire-and-forget
``asyncio.Task`` that nobody awaits. The A2A task was then stranded in WORKING
forever and every SSE subscriber queue was left un-sentinel-closed until the
TTL sweep — a graceful-degradation gap the guarded synchronous worker does not
share.

These tests drive a real ``long_running`` tool whose resolved value makes
``build_artifact`` raise, and assert the task deterministically reaches FAILED
and the subscriber stream is closed (receives the ``None`` close sentinel),
mirroring test_gh87_deferred_task.py. No mock/patch — real run_task_worker +
InMemoryTaskStore.

SI-2: the surfaced error message is a fixed string; no exception/handle text is
echoed (asserted below).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _BadResult:
    """A resolved deferred value that makes build_artifact raise.

    It is neither a ContentModel nor a BaseModel, so build_artifact takes the
    plain-scalar branch and calls ``str(payload)`` to build the TextPart
    fallback — which raises here, before any frame is published.
    """

    def __str__(self) -> str:  # noqa: D401
        raise RuntimeError("unrenderable deferred result")


async def _bad_job() -> _BadResult:
    await asyncio.sleep(0)
    return _BadResult()


_bad_tools = ToolSet()


@_bad_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def unrenderable_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle resolves to a value build_artifact cannot render."""
    return DeferredResult(handle=_bad_job())


class _NonSerializableResult:
    """A resolved deferred value that renders fine but is NOT JSON-serializable.

    Unlike _BadResult, its ``__str__`` succeeds, so build_artifact's plain-scalar
    branch produces a valid TextPart AND a ``DataPart(data={"value": self})``.
    Because _Wire.wire() dumps in PYTHON mode (model_dump WITHOUT mode="json"),
    both build_artifact() and TaskArtifactUpdateEvent.wire() SUCCEED with the raw
    object still embedded — the RT-001 gap the earlier _BadResult test could not
    reach. Without the build-time serializability check the task would go
    COMPLETED (false success) and the crash would only surface later at the
    UNGUARDED sse_data() json.dumps, killing the SSE stream after the terminal
    state. With the fix, build_artifact raises ValueError → the task fails
    deterministically with -32006 BEFORE any false COMPLETED or dead stream.
    """

    def __str__(self) -> str:  # noqa: D401
        return "renders fine but is not JSON-serializable"


async def _nonserializable_job() -> _NonSerializableResult:
    await asyncio.sleep(0)
    return _NonSerializableResult()


@_bad_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def nonserializable_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle resolves to a renderable-but-non-serializable value."""
    return DeferredResult(handle=_nonserializable_job())


_BAD_REGISTRY = ToolRegistry([_bad_tools], {})


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


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
                f"task stuck in state {state!r} after {timeout}s — RT-001: the "
                "deferred artifact-build failure escaped the background task and "
                "stranded the A2A task in WORKING"
            )
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_deferred_artifact_build_failure_transitions_to_failed() -> None:
    """A raise inside build_artifact on the deferred success path must fail the
    task (not strand it in WORKING) with the generic internal-error code."""
    store = InMemoryTaskStore()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("unrenderable_deferred_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_BAD_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.FAILED, (
        f"expected FAILED after deferred artifact-build error, got {final_state!r}"
    )

    rec = store.get(task_id)
    assert rec is not None
    error = rec.task.status.error
    assert error is not None, "expected a WireError on the FAILED task"
    # RuntimeError → generic internal error (-32603), mirroring run_task_worker.
    assert error.code == -32603, f"expected -32603 internal error, got {error.code}"
    # SI-2: fixed message only — no raw exception text on the wire.
    assert error.message == "internal error", error.message
    assert "unrenderable" not in error.message
    assert "RuntimeError" not in error.message


@pytest.mark.asyncio
async def test_deferred_artifact_build_failure_closes_streams() -> None:
    """RT-001: a subscriber attached before the failure must receive the close
    sentinel — the stream must not hang open until the TTL sweep."""
    store = InMemoryTaskStore()
    record = _make_record(store)
    task_id = record.task.id

    sub = store.subscribe(task_id)

    model = FakeModelClient().script(tool_call("unrenderable_deferred_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_BAD_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    await _wait_for_state(store, task_id)

    # Drain the subscription; a closed stream yields items then a None sentinel.
    # If close_streams never ran, this get() blocks and the wait_for times out.
    async def _drain_to_close() -> bool:
        while True:
            item = await sub.get()
            if item is None:  # close sentinel
                return True

    closed = await asyncio.wait_for(_drain_to_close(), timeout=3.0)
    assert closed, "subscriber stream never received the close sentinel"


@pytest.mark.asyncio
async def test_deferred_nonserializable_result_transitions_to_failed() -> None:
    """RT-001 (root): a deferred handle resolving to a renderable-but-NON-JSON-
    serializable value must fail the task with -32006 BEFORE a false COMPLETED.

    This is the case build_artifact()/.wire() do NOT raise on (unlike _BadResult):
    _Wire.wire() dumps in Python mode, so the raw object survives to the wire and
    would only explode at the unguarded sse_data() json.dumps. Every frame this
    task delivers must be JSON-serializable; the terminal state must be FAILED.
    """
    store = InMemoryTaskStore()
    record = _make_record(store)
    task_id = record.task.id

    sub = store.subscribe(task_id)

    model = FakeModelClient().script(tool_call("nonserializable_deferred_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_BAD_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.FAILED, (
        "expected FAILED for a non-serializable deferred result — a COMPLETED "
        "here is the false-success + dead-SSE-stream RT-001 failure class"
    )

    rec = store.get(task_id)
    assert rec is not None
    # Non-serializable resolved value → "invalid agent response" (-32006),
    # mirroring _validate_a2ui_wire's malformed-domain-card mapping.
    error = rec.task.status.error
    assert error is not None, "expected a WireError on the FAILED task"
    assert error.code == -32006, f"expected -32006 invalid agent response, got {error.code}"
    assert error.message == "invalid agent response", error.message
    # A non-serializable artifact must NOT be retained on the (failed) task.
    assert not rec.task.artifacts, "failed task must not retain an undelivered artifact"

    # Every frame delivered to the subscriber must survive sse_data()'s json.dumps.
    import json as _json

    from agent_sdk.common.sse import sse_data

    async def _drain_and_serialize() -> bool:
        while True:
            item = await sub.get()
            if item is None:  # close sentinel
                return True
            if item.frame is not None:
                # would raise TypeError before the fix (proves no poisoned frame
                # ever reaches the wire)
                _json.loads(sse_data(item.frame)[len(b"data: "):].decode())

    closed = await asyncio.wait_for(_drain_and_serialize(), timeout=3.0)
    assert closed, "subscriber stream never received the close sentinel"
