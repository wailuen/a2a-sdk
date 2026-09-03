"""RT-B-001 (round 2): the C-005 durable-store contract was unsatisfiable as
documented. ``persist_messages`` had exactly ONE call site in the whole SDK —
``repair_dangling_tool_use`` — which never runs on a normal completion (there
is no dangling ``toolUse`` tail to repair). RT-B-008 wired ``set_task_status`` up
to flush ``persist_status`` on every transition, including the dominant
non-cancelled COMPLETED/FAILED path, but nothing flushed ``persist_messages``
alongside it there. Net effect: a durable store observed a task going
terminal without ever having received its transcript, so
``context_messages()``'s ``TERMINAL_STATES`` filter selected it and replayed
a stale (often empty) history on the next ``contextId`` continuation.

Fix: ``set_task_status`` (agent/runner.py) now also flushes
``TaskStore.persist_messages(record)`` on every ``TERMINAL_STATES``
transition, BEFORE ``persist_status`` — mirroring ``tasks_cancel``'s own
RT-B-007 ordering/gating: ``persist_status`` runs only once the messages
flush has actually succeeded, so a failure leaves the durable record
correctly non-terminal rather than terminal over a transcript that never
arrived.

Unit-level tests mirror test_rtb008_set_status_persist_status_choke_point.py's
direct-``set_task_status``-call style; the durable-store test mirrors
test_rt005_gh150_taskstore_persist_messages_hook.py's copy-on-get double; the
ASGI-level test proves the choke point fires for a NORMAL (non-cancelled,
non-repaired) completion — the exact gap test_rtb008's own ASGI test did not
cover, since it only asserted on ``persist_status``.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import httpx

from agent_sdk.agent.runner import set_task_status, new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord
from agent_sdk.testing import reply

from .conftest import wait_for_state

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)


def send_body(text: str) -> dict[str, Any]:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


# ── unit: set_task_status flushes persist_messages on terminal transitions ─────


def test_set_status_flushes_persist_messages_on_completed() -> None:
    calls: list[list[dict[str, Any]]] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            calls.append([dict(m) for m in record.messages])

    store = _RecordingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None
    record.messages = [{"role": "user", "content": [{"text": "hi"}]}]

    set_task_status(record, TaskState.COMPLETED, store=store)

    assert len(calls) == 1, "persist_messages must be called exactly once"
    assert calls[0] == record.messages


def test_set_status_flushes_persist_messages_on_failed() -> None:
    calls: list[TaskState] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            calls.append(record.task.status.state)

    store = _RecordingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.FAILED, store=store)

    # the flush must observe the ALREADY-updated status (matching the
    # already-updated record.messages guarantee documented on the hook)
    assert calls == [TaskState.FAILED]


def test_set_status_does_not_flush_persist_messages_on_non_terminal_transition() -> None:
    """WORKING/AUTH_REQUIRED/INPUT_REQUIRED are not terminal — flushing the
    transcript on every one of those (there can be many per task, one per
    ToolProgressEvent) would be a durable-write amplification with no
    correctness payoff, since context_messages() only ever looks at
    TERMINAL_STATES records."""
    calls: list[TaskState] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            calls.append(record.task.status.state)

    store = _RecordingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.WORKING, store=store)

    assert calls == []


def test_set_status_flushes_messages_before_status() -> None:
    order: list[str] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            order.append("messages")

        def persist_status(self, record: TaskRecord) -> None:
            order.append("status")

    store = _RecordingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.COMPLETED, store=store)

    assert order == ["messages", "status"], (
        "RT-B-007 ordering: persist_messages must land before persist_status "
        "on a terminal transition, never the reverse"
    )


def test_set_status_skips_persist_status_when_persist_messages_fails() -> None:
    """Mirrors tasks_cancel's own RT-B-007 gate: a persist_messages failure
    on a terminal transition must NOT be followed by a persist_status flush
    — otherwise the durable store is left holding a terminal status over a
    transcript that never arrived, and context_messages() would select and
    replay it."""
    status_calls: list[TaskState] = []

    class _FailingMessagesStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            raise RuntimeError("simulated durable persist_messages failure")

        def persist_status(self, record: TaskRecord) -> None:
            status_calls.append(record.task.status.state)

    store = _FailingMessagesStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.COMPLETED, store=store)  # must not raise

    assert status_calls == [], (
        "persist_status must be skipped when persist_messages failed on a "
        "terminal transition"
    )
    # the in-memory record itself still reflects the transition — only the
    # durable flush is skipped, matching tasks_cancel's degrade-gracefully
    # contract (RT-B-002/RT-B-003).
    assert record.task.status.state == TaskState.COMPLETED


def test_set_status_without_store_arg_still_unchanged() -> None:
    store = InMemoryTaskStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.COMPLETED)  # no store= — must not raise

    assert record.task.status.state == TaskState.COMPLETED


# ── durable copy-on-get store: the actual RT-B-001 regression ──────────────


class _CopyOnGetStore(InMemoryTaskStore):
    """Stands in for an AzureTableTaskStore-shaped subclass: get() hands
    back a FRESH copy of both task and messages on every call, and both
    write hooks are faithfully overridden."""

    def get(self, task_id: str, identity: Any = None) -> TaskRecord | None:
        live = super().get(task_id, identity)
        if live is None:
            return None
        return dataclasses.replace(
            live, task=live.task.model_copy(deep=True), messages=list(live.messages)
        )

    def persist_messages(self, record: TaskRecord) -> None:
        durable = self._records.get(record.task.id)
        if durable is not None:
            durable.messages = list(record.messages)

    def persist_status(self, record: TaskRecord) -> None:
        durable = self._records.get(record.task.id)
        if durable is not None:
            durable.task.status = record.task.status


def test_completed_transcript_survives_durable_copy_on_get_store() -> None:
    """Before the fix: a durable copy-on-get store's persist_status override
    (already wired by RT-B-008) alone made context_messages() SELECT the
    task as a continuation candidate, but its messages were never flushed —
    so context_messages() returned []. context_messages() must return the
    actual transcript, not a stale/empty one."""
    store = _CopyOnGetStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None
    record.messages.append({"role": "user", "content": [{"text": "hi"}]})
    record.messages.append(
        {"role": "assistant", "content": [{"text": "hello back"}]}
    )

    set_task_status(record, TaskState.COMPLETED, store=store)

    replayed = store.context_messages(record.task.context_id)
    assert replayed != [], (
        "RT-B-001: a durable store observed the COMPLETED transition but "
        "never the transcript behind it — context_messages() replayed a "
        "stale/empty history instead of the real one"
    )
    assert replayed == record.messages


# ── ASGI-level: the DOMINANT (non-cancelled, non-repaired) completion path ──


async def test_normal_completion_flushes_persist_messages_hook(settings, fake_model) -> None:
    calls: list[list[dict[str, Any]]] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            calls.append([dict(m) for m in record.messages])

    store = _RecordingStore()
    agent = make_agent(settings, model_client=fake_model, task_store=store)
    app = agent.build_app()
    fake_model.script(reply("final answer"))
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as client:
            r = await client.post("/v1/message:send", json=send_body("hi"))
            assert r.status_code == 200, r.text
            task_id = r.json()["id"]
            task = await wait_for_state(client, task_id)
            assert task["status"]["state"] == "completed"
    app.state.credential_store.close()

    assert len(calls) >= 1, (
        "persist_messages must be invoked on the normal COMPLETED transition "
        "(runner.py's DoneEvent branch), not only from repair_dangling_tool_use"
    )
    final_transcript = calls[-1]
    assert final_transcript, "the flushed transcript must not be empty"
    assert final_transcript[-1]["role"] == "assistant", (
        "the flush must observe the transcript AFTER run_loop folded the "
        "final assistant turn, not a snapshot taken before it"
    )


async def test_normal_completion_context_messages_survives_durable_store(
    settings, fake_model
) -> None:
    """End-to-end reproduction of the finding: run a full task to completion
    against a durable copy-on-get store, then confirm a contextId
    continuation actually sees the transcript rather than an empty one."""
    store = _CopyOnGetStore()
    agent = make_agent(settings, model_client=fake_model, task_store=store)
    app = agent.build_app()
    fake_model.script(reply("final answer"))
    context_id = uuid.uuid4().hex
    async with app.router.lifespan_context(app):
        key_id, token = app.state.auth.api_keys.mint("test-admin", admin=True)
        caller_identity = Identity(kind="api_key", subject=key_id, admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as client:
            body = send_body("hi")
            body["message"]["contextId"] = context_id
            r = await client.post("/v1/message:send", json=body)
            assert r.status_code == 200, r.text
            task_id = r.json()["id"]
            task = await wait_for_state(client, task_id)
            assert task["status"]["state"] == "completed"

        # asserted BEFORE the lifespan exits: close_all() (shutdown) evicts
        # every record, which would make this check vacuously pass for the
        # wrong reason. Must be the SAME identity that created the task
        # (RT-004: context_messages() is identity-scoped, no admin
        # cross-identity bypass) — a bare admin identity of a different
        # subject would see nothing, for reasons unrelated to this test's
        # own RT-B-001 durability question.
        replayed = store.context_messages(context_id, caller_identity)
        assert replayed != [], (
            "RT-B-001: a normally-completed task's transcript never reached "
            "durable storage, so the next contextId continuation on this store "
            "would replay an empty history"
        )
    app.state.credential_store.close()
