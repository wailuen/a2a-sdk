"""RT-001 (synchronous path): a non-serializable resolved tool result must
fail the task deterministically, not just on the deferred background path.

``build_artifact``'s plain-scalar branch (SC-A2:
``DataPart(data={"value": payload})``) embeds the raw resolved value with NO
``model_dump(mode="json")`` coercion. The existing regression coverage
(test_rt001_deferred_artifact_build_failure.py) only drives this branch via
``_run_deferred_background``, whose ``ArtifactEvent`` construction has no
``isinstance(result, emits)`` guard. But the SAME branch is also reachable
from ``run_task_worker``'s SYNCHRONOUS ``ArtifactEvent`` handling
(``agent/loop.py``'s ``isinstance(result, emits)`` check): ``ToolEntry``'s
``emits`` type-annotation is only ever checked against ``BaseModel`` lazily,
inside ``mcp_output_schema()`` (``registry.py``, returns ``None`` for a
non-BaseModel ``emits`` rather than rejecting it at decoration time) — a tool
can legally declare ``emits=SomeNonPydanticClass`` and return a plain
instance of it directly, which the loop then wraps in an ``ArtifactEvent``
and ``run_task_worker`` builds synchronously (no deferred background task
involved at all).

Drives a real tier-1 (non-``long_running``) tool through ``run_task_worker``
whose declared ``emits`` is a plain (non-BaseModel) class and whose returned
instance is not JSON-serializable, and asserts the task reaches FAILED with
-32006 ("invalid agent response") and the subscriber stream closes — not a
false COMPLETED with a poisoned frame that would only crash later at the
unguarded ``sse_data()`` json.dumps (routes/a2a.py). No mock/patch — real
run_task_worker + InMemoryTaskStore, mirroring
test_rt001_deferred_artifact_build_failure.py's non-serializable case.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.common.sse import sse_data
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _NonSerializablePayload:
    """A plain (non-BaseModel) ``emits`` type. ``str()`` succeeds (so the
    TextPart fallback renders fine) but instances are NOT JSON-serializable —
    the exact renders-fine-but-not-serializable shape build_artifact's
    plain-scalar branch cannot coerce."""

    def __str__(self) -> str:  # noqa: D401
        return "renders fine but is not JSON-serializable"


_sync_tools = ToolSet()


@_sync_tools.tool(tier=1, emits=_NonSerializablePayload)
async def sync_nonserializable_tool() -> _NonSerializablePayload:
    """Tool whose declared emits type is not a BaseModel and whose result
    is not JSON-serializable."""
    return _NonSerializablePayload()


_SYNC_REGISTRY = ToolRegistry([_sync_tools], {})


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


async def _drain_and_serialize(sub: Any, timeout: float = 3.0) -> list[Any]:
    async def _loop() -> list[Any]:
        items: list[Any] = []
        while True:
            item = await sub.get()
            if item is None:  # close sentinel
                return items
            if item.frame is not None:
                # would raise TypeError before the fix (proves no poisoned
                # frame ever reaches the wire)
                json.loads(sse_data(item.frame)[len(b"data: "):].decode())
            items.append(item)

    return await asyncio.wait_for(_loop(), timeout=timeout)


@pytest.mark.asyncio
async def test_sync_artifact_nonserializable_result_transitions_to_failed() -> None:
    store = InMemoryTaskStore()
    record = _make_record(store)
    task_id = record.task.id
    sub = store.subscribe(task_id)

    # A scripted follow-up reply is provided so that, in the ABSENCE of the
    # RT-001 guard, the loop's normal continuation (a second model call after
    # the tool result) does not mask the bug behind an unrelated
    # script-exhaustion error — the guard's absence must surface as a false
    # COMPLETED (with the poisoned artifact retained), not a coincidental
    # FAILED for the wrong reason.
    model = FakeModelClient().script(
        tool_call("sync_nonserializable_tool", {}), reply("done")
    )

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

    rec = store.get(task_id)
    assert rec is not None
    assert rec.task.status.state == TaskState.FAILED, (
        "expected FAILED for a non-serializable synchronous artifact result — "
        f"a COMPLETED here is the false-success + dead-SSE-stream failure class, got {rec.task.status.state!r}"
    )
    error = rec.task.status.error
    assert error is not None, "expected a WireError on the FAILED task"
    assert error.code == -32006, f"expected -32006 invalid agent response, got {error.code}"
    assert error.message == "invalid agent response", error.message
    assert not rec.task.artifacts, "failed task must not retain an undelivered artifact"

    items = await _drain_and_serialize(sub)
    assert items, "subscriber stream never received the close sentinel"
