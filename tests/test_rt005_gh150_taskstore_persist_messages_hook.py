"""RT-005 (GH-150 follow-up): repair_dangling_tool_use mutates
record.messages in place with no TaskStore write hook.

InMemoryTaskStore.get() hands back the live TaskRecord by reference, so the
in-place mutation IS the write for it. A durable TaskStore whose get()
deserializes a FRESH copy on every call (the AzureTableTaskStore shape
C-005/TaskStore exists for) never gets that mutation back into storage
unless repair_dangling_tool_use explicitly hands it to a store-owned write
hook. TaskStore.persist_messages(record) is that hook: a no-op default (so
a pre-existing external TaskStore subclass keeps instantiating without an
override, mirroring the interrupt_ttl_remaining precedent), called once,
unconditionally, at the end of repair_dangling_tool_use whenever a caller
passes ``store=``.

Unit-level (agent_sdk.agent.runner + agent_sdk.tasks.store/memory only — no
FastAPI app boot), mirroring test_rt003_repair_dangling_tool_use_bridges_all_exits.py
and test_task_memory_store.py's direct-store-layer style.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from agent_sdk.agent.runner import new_task, repair_dangling_tool_use
from agent_sdk.auth.identity import Identity
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord, TaskStore

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)


def _record(messages: list[dict[str, Any]]) -> TaskRecord:
    from agent_sdk.models.a2a import Task, TaskState, TaskStatus

    task = Task(id="t1", contextId="c1", status=TaskStatus(state=TaskState.CANCELED))
    record = TaskRecord(task=task, identity=("api_key", "test"), created_at=0.0, updated_at=0.0)
    record.messages = messages
    return record


_DANGLING_MESSAGES: list[dict[str, Any]] = [
    {"role": "user", "content": [{"text": "go"}]},
    {
        "role": "assistant",
        "content": [{"toolUse": {"toolUseId": "tu1", "name": "echo", "input": {}}}],
    },
]


def _seed_dangling_tool_use(store: InMemoryTaskStore) -> str:
    """Writes directly into the store's durable record (bypassing any
    ``get()`` override that returns a copy), so a ``_CopyOnGetStore``'s
    seeded state actually lives in ``_records`` rather than on a
    throwaway copy that ``store.get()`` would hand back and discard."""
    task = new_task()
    store.create(task, _IDENTITY)
    durable = store._records[task.id]
    durable.messages = [dict(m) for m in _DANGLING_MESSAGES]
    return task.id


def _ends_on_dangling_tool_use(messages: list[dict[str, Any]]) -> bool:
    if not messages or messages[-1].get("role") != "assistant":
        return False
    return any(
        isinstance(block, dict) and "toolUse" in block
        for block in messages[-1].get("content", [])
    )


class _CopyOnGetStore(InMemoryTaskStore):
    """Stands in for an AzureTableTaskStore-shaped subclass: get()
    deserializes a fresh TaskRecord copy (with its own messages/
    pending_tool_results lists) on every call, instead of
    InMemoryTaskStore's live-object-by-reference get()."""

    def get(self, task_id: str, identity: Identity | None = None) -> TaskRecord | None:
        live = super().get(task_id, identity)
        if live is None:
            return None
        return dataclasses.replace(
            live,
            messages=list(live.messages),
            pending_tool_results=list(live.pending_tool_results),
        )


class _CopyOnGetStoreWithPersistHook(_CopyOnGetStore):
    def persist_messages(self, record: TaskRecord) -> None:
        durable = self._records.get(record.task.id)
        if durable is not None:
            durable.messages = list(record.messages)
            durable.pending_tool_results = list(record.pending_tool_results)


# ── base-class default is a no-op (RT-002 interrupt_ttl_remaining pattern) ──


def test_taskstore_persist_messages_default_is_noop() -> None:
    store = InMemoryTaskStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None
    TaskStore.persist_messages(store, record)  # must not raise


# ── repair_dangling_tool_use calls the hook, with the repaired state ───────


def test_repair_dangling_tool_use_without_store_arg_is_unchanged() -> None:
    """Backward compatible: omitting ``store=`` (every pre-RT-005 direct
    caller/test) must not raise and must behave exactly as before."""
    record = _record([dict(m) for m in _DANGLING_MESSAGES])
    repair_dangling_tool_use(record, default_content=[{"text": "cancelled"}])
    assert not _ends_on_dangling_tool_use(record.messages)


def test_repair_dangling_tool_use_invokes_persist_hook_with_repaired_record() -> None:
    calls: list[list[dict[str, Any]]] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            calls.append([dict(m) for m in record.messages])

    store = _RecordingStore()
    task_id = _seed_dangling_tool_use(store)
    record = store.get(task_id)
    assert record is not None

    repair_dangling_tool_use(record, default_content=[{"text": "cancelled"}], store=store)

    assert len(calls) == 1, "persist_messages must be called exactly once"
    # the hook must observe the ALREADY-repaired transcript, not the
    # pre-mutation dangling one
    assert not _ends_on_dangling_tool_use(calls[0])


# ── the actual RT-005 regression: a durable copy-on-get store ──────────────


def test_repair_without_persist_hook_override_is_silently_lost_on_copy_on_get_store() -> None:
    """Documents the exact gap the finding raised: a durable-shaped store
    that does not override persist_messages (the pre-existing-subclass
    case) keeps working — but silently keeps losing the repair, exactly
    like interrupt_ttl_remaining's unoverridden default silently drops
    expiresAt rather than erroring."""
    store = _CopyOnGetStore()
    task_id = _seed_dangling_tool_use(store)

    record = store.get(task_id)
    assert record is not None
    repair_dangling_tool_use(record, default_content=[{"text": "cancelled"}], store=store)
    assert not _ends_on_dangling_tool_use(record.messages), "caller's own copy is repaired"

    replayed = store.get(task_id)
    assert replayed is not None
    assert _ends_on_dangling_tool_use(replayed.messages), (
        "without an override, the durable copy never saw the repair"
    )


def test_repair_with_persist_hook_override_survives_durable_get() -> None:
    """The fix: a durable TaskStore that overrides persist_messages(record)
    gets the repaired transcript flushed back, so context_messages() on a
    later contextId continuation never replays the dangling toolUse."""
    store = _CopyOnGetStoreWithPersistHook()
    task_id = _seed_dangling_tool_use(store)

    record = store.get(task_id)
    assert record is not None
    repair_dangling_tool_use(record, default_content=[{"text": "cancelled"}], store=store)

    replayed = store.get(task_id)
    assert replayed is not None
    assert not _ends_on_dangling_tool_use(replayed.messages)
    assert replayed.messages[-1]["role"] != "user"
