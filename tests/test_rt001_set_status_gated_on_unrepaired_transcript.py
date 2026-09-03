"""RT-001 (agent/runner.py review): set_task_status must not durably flush a
terminal/interrupt status when a preceding repair_dangling_tool_use_safe call
reported the transcript as unrepaired.

Every one of set_task_status's five out-of-loop callers calls
repair_dangling_tool_use_safe first and then set_task_status(..., store=store)
unconditionally. Nothing about a broken transcript makes a store's
persist_messages write raise, so an unguarded set_task_status would happily
persist it and then durably commit the terminal status over it — the exact
GH-150 shape context_messages() replays into Bedrock's Converse API.

Fix: set_task_status takes a `repaired` flag (default True, so every
transition that never went through a repair keeps its existing behavior) and
skips its own persist_messages/persist_status flush entirely when the caller
passes `repaired=False`. record.task.status is still committed in-memory
unconditionally — the wire response has already committed to it.
"""

from __future__ import annotations

from typing import Any

from agent_sdk.agent.runner import repair_dangling_tool_use_safe, set_task_status
from agent_sdk.models.a2a import Task, TaskState, TaskStatus
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord


def _record(messages: list[dict[str, Any]]) -> TaskRecord:
    task = Task(id="t1", contextId="c1", status=TaskStatus(state=TaskState.WORKING))
    record = TaskRecord(task=task, identity=("api_key", "test"), created_at=0.0, updated_at=0.0)
    record.messages = messages
    return record


def _recording_store() -> tuple[type[InMemoryTaskStore], list[Any], list[TaskState]]:
    messages_calls: list[Any] = []
    status_calls: list[TaskState] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            messages_calls.append(list(record.messages))

        def persist_status(self, record: TaskRecord) -> None:
            status_calls.append(record.task.status.state)

    return _RecordingStore, messages_calls, status_calls


def test_set_status_skips_durable_flush_when_repaired_is_false() -> None:
    """The direct unit contract: repaired=False must skip both flushes even
    though the store would otherwise happily accept the write."""
    store_cls, messages_calls, status_calls = _recording_store()
    store = store_cls()
    record = _record([{"role": "user", "content": [{"text": "go"}]}])

    set_task_status(record, TaskState.FAILED, store=store, repaired=False)

    assert record.task.status.state == TaskState.FAILED, (
        "the in-memory terminal transition must still commit — the wire "
        "response has already reported it"
    )
    assert messages_calls == [], (
        "set_task_status must never flush a transcript reported as unrepaired"
    )
    assert status_calls == [], (
        "the terminal status must never be durably persisted over an "
        "unrepaired transcript — a future contextId continuation would "
        "replay it straight into Bedrock's Converse API"
    )


def test_set_status_still_flushes_when_repaired_is_true() -> None:
    """Companion GREEN case: repaired=True (the default) keeps flushing
    exactly as before."""
    store_cls, messages_calls, status_calls = _recording_store()
    store = store_cls()
    record = _record([{"role": "user", "content": [{"text": "go"}]}])

    set_task_status(record, TaskState.FAILED, store=store, repaired=True)

    assert record.task.status.state == TaskState.FAILED
    assert len(messages_calls) == 1
    assert status_calls == [TaskState.FAILED]


def test_set_status_repaired_defaults_true_for_non_repair_callers() -> None:
    """Every set_task_status call site that never goes through a repair
    (WORKING transitions, DoneEvent, InterruptEvent, ...) omits `repaired`
    entirely and must keep flushing exactly as before."""
    store_cls, _messages_calls, status_calls = _recording_store()
    store = store_cls()
    record = _record([{"role": "user", "content": [{"text": "hi"}]}])

    set_task_status(record, TaskState.COMPLETED, store=store)

    assert status_calls == [TaskState.COMPLETED]


def test_integration_flush_failure_gates_status_without_faking_an_unrepaired_repair() -> None:
    """End-to-end, RT-001 (debug round 4): a durable persist_messages failure
    must be caught by set_task_status's OWN `flushed` gate — not smuggled back
    through `repaired`.

    The repair succeeds in memory, so `repaired` is True (the transcript IS
    safe to persist). set_task_status then attempts persist_messages, that
    attempt raises, and its own gate suppresses persist_status. Same
    fail-closed outcome as before, but reached by the path designed for it:
    the store failure never disguises itself as an unrepaired transcript, so a
    transient blip can no longer permanently gate the terminal status out of
    durable storage on the retry that follows."""
    status_calls: list[TaskState] = []
    messages_attempts: list[int] = []

    class _RaisesOnPersistMessages(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            messages_attempts.append(1)
            raise RuntimeError("simulated durable persist_messages failure")

        def persist_status(self, record: TaskRecord) -> None:
            status_calls.append(record.task.status.state)

    store = _RaisesOnPersistMessages()
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "c1", "name": "t", "input": {}}}],
            },
        ]
    )

    repaired = repair_dangling_tool_use_safe(record, default_content=[{"text": "failed"}])
    assert repaired is True, (
        "the in-memory repair landed, so the transcript IS safe to persist — a "
        "store write failure must never be reported through this flag"
    )
    assert record.messages[-2]["content"][0]["toolResult"]["toolUseId"] == "c1"

    set_task_status(record, TaskState.FAILED, store=store, repaired=repaired)

    assert record.task.status.state == TaskState.FAILED
    assert status_calls == [], (
        "persist_status must be suppressed when set_task_status's own "
        "persist_messages attempt failed — the durable record stays "
        "non-terminal rather than terminal over a transcript that never landed"
    )
    assert messages_attempts == [1], (
        "RT-007: exactly ONE persist_messages write per terminal transition — "
        "the repair must not have issued a second one of its own"
    )


def test_repair_path_issues_exactly_one_durable_write_per_terminal_transition() -> None:
    """RT-007 (debug round 4) green case: the happy repair+terminal path
    writes the transcript once, not twice. persist_messages/persist_status are
    plain synchronous hooks whose durable writes block the event loop — the
    same cost that motivated gating WORKING flushes away."""
    store_cls, messages_calls, status_calls = _recording_store()
    store = store_cls()
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "c1", "name": "t", "input": {}}}],
            },
        ]
    )

    repaired = repair_dangling_tool_use_safe(record, default_content=[{"text": "cancelled"}])
    set_task_status(record, TaskState.CANCELED, store=store, repaired=repaired)

    assert len(messages_calls) == 1, (
        f"expected exactly one persist_messages write, got {len(messages_calls)}"
    )
    assert status_calls == [TaskState.CANCELED]
    # and the single write carried the REPAIRED transcript, not the pre-repair one
    assert messages_calls[0][-2]["content"][0]["toolResult"]["toolUseId"] == "c1"
