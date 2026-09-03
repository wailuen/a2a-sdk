"""RT-001 (GH-148 cross-surface parity, follow-up to RT-004/GH-150): a
deferred (GH-87) tool whose handle resolves to a ``Reusable`` must be
unwrapped by ``_run_deferred_background`` (runner.py) exactly like the
synchronous ``run_loop`` branch (loop.py:730) and ``ToolEntry.invoke_any``
(registry.py:634) — never leaking the raw dataclass into ``record.messages``
or the terminal artifact, and folding the same ``__resolved__`` marker so a
later contextId continuation's ``scan_resolved`` can still rebuild the
resolved index from this deferred call.

No unittest.mock.patch / MagicMock. Uses FakeModelClient and the real
run_task_worker + InMemoryTaskStore, exactly like
tests/test_rt004_deferred_transcript_parity.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, scan_resolved
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

pytestmark = pytest.mark.asyncio

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


async def _reusable_job() -> Reusable:
    await asyncio.sleep(0)
    return Reusable(value="ENT_42", kind="entity_id", label="Acme Corp")


reusable_tools = ToolSet()


@reusable_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def deferred_reusable_tool() -> DeferredResult:
    """Deferred tool whose handle resolves to a Reusable value."""
    return DeferredResult(handle=_reusable_job())


REUSABLE_REGISTRY = ToolRegistry([reusable_tools], {})


async def test_deferred_reusable_unwraps_before_transcript_fold_and_artifact_build() -> None:
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("deferred_reusable_tool", {}))

    await _run_worker(store, record, model, REUSABLE_REGISTRY)

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.COMPLETED

    rec = store.get(task_id)
    assert rec is not None

    # The raw Reusable dataclass repr must never reach the transcript.
    assert "Reusable(" not in repr(rec.messages)

    tool_result_msgs = [
        block["toolResult"]
        for msg in rec.messages
        if msg.get("role") == "user"
        for block in msg.get("content") or []
        if isinstance(block, dict) and "toolResult" in block
    ]
    assert len(tool_result_msgs) == 1, f"expected exactly one toolResult message, got {rec.messages}"
    result_block = tool_result_msgs[0]
    assert result_block["status"] == "success"
    content = result_block["content"]
    assert content[0] == {"text": "ENT_42"}

    marker_blocks = [b for b in content if isinstance(b.get("json"), dict) and "__resolved__" in b["json"]]
    assert len(marker_blocks) == 1, f"expected exactly one __resolved__ marker, got {content}"
    marker = marker_blocks[0]["json"]["__resolved__"]
    assert marker == {"kind": "entity_id", "label": "Acme Corp", "value": "ENT_42"}

    # A later contextId continuation must be able to rebuild the resolved
    # index from this deferred call's folded marker (module contract,
    # agent_sdk/agent/reuse.py).
    index = scan_resolved(rec.messages)
    assert index == {"entity_id": [("Acme Corp", "ENT_42")]}

    # The terminal artifact must carry the unwrapped value too — never the
    # wrapper (or its repr) on the wire.
    assert rec.task.artifacts, "expected a terminal artifact"
    artifact_wire = rec.task.artifacts[-1].wire()
    assert "Reusable(" not in repr(artifact_wire)
