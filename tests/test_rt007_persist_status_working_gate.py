"""RT-007: ``set_task_status`` (agent/runner.py) called the synchronous
``TaskStore.persist_status`` hook on EVERY status transition, including the
WORKING transition re-applied for each streamed ``TextEvent``/
``ProgressEvent``/``NoteEvent``/``ToolProgressEvent`` within a single model
turn. The ABC hook is a plain ``def``, so a durable subclass doing a network
write blocks the event loop several times per turn on the SSE hot path, with
no cheap way to opt out.

Fix: ``set_task_status`` now flushes ``persist_status`` by default only for
transitions that matter for durability — ``TERMINAL_STATES`` and
``INTERRUPT_STATES`` (AUTH_REQUIRED/INPUT_REQUIRED, needed so a resumable
task survives a restart) — never for the repeated WORKING transitions inside
a turn. A store that wants the old every-transition behaviour opts in via
the ``TaskStore.persist_every_status`` class attribute.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from agent_sdk.agent.runner import set_task_status, new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import Message, TaskState, TextPart
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


def _working_message(text: str) -> Message:
    return Message(
        role="agent",
        parts=[TextPart(text=text)],
        messageId=uuid.uuid4().hex,
        taskId="t",
        contextId="c",
    )


# ── unit: default gating skips WORKING, keeps terminal + interrupt states ──


def test_set_status_skips_persist_status_for_working_by_default() -> None:
    calls: list[TaskState] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_status(self, record: TaskRecord) -> None:
            calls.append(record.task.status.state)

    store = _RecordingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.WORKING, store=store)
    set_task_status(record, TaskState.WORKING, _working_message("chunk one"), store=store)
    set_task_status(record, TaskState.WORKING, _working_message("chunk two"), store=store)
    set_task_status(record, TaskState.COMPLETED, store=store)

    assert calls == [TaskState.COMPLETED], (
        "by default persist_status must be flushed only for the terminal "
        "transition, never for the repeated WORKING transitions inside a turn"
    )


def test_set_status_flushes_persist_status_for_interrupt_states_by_default() -> None:
    """AUTH_REQUIRED/INPUT_REQUIRED are not in TERMINAL_STATES, but a durable
    store still needs them: an interrupted task that never reaches durable
    storage cannot survive a restart to be resumed."""
    calls: list[TaskState] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_status(self, record: TaskRecord) -> None:
            calls.append(record.task.status.state)

    store = _RecordingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.WORKING, store=store)
    set_task_status(record, TaskState.INPUT_REQUIRED, store=store)

    assert calls == [TaskState.INPUT_REQUIRED]


def test_set_status_flushes_persist_messages_for_interrupt_states_too() -> None:
    """RT-B-104: persist_status's own docstring justifies flushing on an
    INTERRUPT_STATES transition as durability for resume-after-restart — but
    the transcript a resume actually replays (context_messages()) is
    record.messages, not the status alone. persist_messages must be flushed
    on that same transition, under the same fail-closed ordering
    (messages first, status only if that landed) TERMINAL_STATES already
    gets, or a durable store ends up holding a resumable-looking status over
    a transcript that cannot back it."""
    message_calls: list[TaskState] = []
    status_calls: list[TaskState] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            message_calls.append(record.task.status.state)

        def persist_status(self, record: TaskRecord) -> None:
            status_calls.append(record.task.status.state)

    store = _RecordingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None
    record.messages.append({"role": "user", "content": [{"text": "go"}]})

    set_task_status(record, TaskState.WORKING, store=store)
    set_task_status(record, TaskState.INPUT_REQUIRED, store=store)

    assert message_calls == [TaskState.INPUT_REQUIRED], (
        "persist_messages must be flushed on the INTERRUPT_STATES transition "
        "too, not only WORKING-skipped/TERMINAL_STATES — the resumed turn's "
        "transcript must reach durable storage alongside the status that "
        "claims it is resumable"
    )
    assert status_calls == [TaskState.INPUT_REQUIRED]


def test_set_status_skips_persist_status_when_persist_messages_fails_on_interrupt() -> None:
    """RT-B-104: the same fail-closed ordering TERMINAL_STATES gets — status
    flushed only if the messages flush actually landed — must also hold for
    an INTERRUPT_STATES transition."""
    persist_status_called = False

    class _RaisesOnPersistMessages(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            raise RuntimeError("simulated durable persist_messages failure")

        def persist_status(self, record: TaskRecord) -> None:
            nonlocal persist_status_called
            persist_status_called = True

    store = _RaisesOnPersistMessages()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    # Must not raise — a durable write failure degrades to an unpersisted
    # status rather than propagating out of a hot status-transition path.
    set_task_status(record, TaskState.INPUT_REQUIRED, store=store)
    assert record.task.status.state == TaskState.INPUT_REQUIRED
    assert not persist_status_called, (
        "persist_status must be skipped when persist_messages failed on an "
        "INTERRUPT_STATES transition too, mirroring the TERMINAL_STATES "
        "fail-closed ordering — a failure must leave the durable record "
        "correctly non-resumable rather than durably interrupted over a "
        "transcript that never arrived"
    )


def test_set_status_persist_every_status_opt_in_restores_working_flushes() -> None:
    calls: list[TaskState] = []

    class _OptedInStore(InMemoryTaskStore):
        persist_every_status = True

        def persist_status(self, record: TaskRecord) -> None:
            calls.append(record.task.status.state)

    store = _OptedInStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.WORKING, store=store)
    set_task_status(record, TaskState.COMPLETED, store=store)

    assert calls == [TaskState.WORKING, TaskState.COMPLETED]


# ── ASGI-level: a normal streamed turn (TextEvent then DoneEvent) hits the
#    exact hot-path call sites the finding names, with a plain (non-opted-in)
#    durable-style store ─────────────────────────────────────────────────


async def test_streamed_turn_does_not_flush_persist_status_for_text_event(
    settings, fake_model
) -> None:
    calls: list[TaskState] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_status(self, record: TaskRecord) -> None:
            calls.append(record.task.status.state)

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

    assert calls == [TaskState.COMPLETED], (
        "the TextEvent-driven WORKING re-transition (runner.py's TextEvent "
        "branch) must not flush persist_status by default — only the "
        "terminal COMPLETED transition should"
    )
