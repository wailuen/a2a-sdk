"""RT-B-008: TaskStore.persist_status had exactly ONE call site
(routes/a2a.py's tasks_cancel) while record.task.status is mutated in place
by agent/runner.py's set_task_status at every WORKING/COMPLETED/FAILED/
AUTH_REQUIRED/INPUT_REQUIRED transition. A durable TaskStore that correctly
overrides persist_status still never observed any of those transitions —
including the dominant, non-cancelled COMPLETED path — because set_task_status
never called the hook at all.

Fix: set_task_status now takes an optional store= keyword and is the single
choke point that calls TaskStore.persist_status(record) after mutating
record.task.status, mirroring how repair_dangling_tool_use (C-018)
centralises the persist_messages flush (C-005) rather than requiring each
call site to remember its own follow-up call. Every call site inside
agent/runner.py now passes its own store.

Unit-level tests mirror test_rt005_gh150_taskstore_persist_messages_hook.py's
direct-store-layer style; the ASGI-level test proves the choke point fires
for a NORMAL (non-cancelled) completion, the gap
test_rtb003_taskstore_persist_status_hook.py's cancel-only coverage missed.

RT-007 narrowed the choke point: set_task_status still mutates status on every
transition, but by default flushes persist_status only for TERMINAL_STATES
and INTERRUPT_STATES, not for WORKING — see
test_rt007_persist_status_working_gate.py for that gating and its
persist_every_status opt-in.
"""

from __future__ import annotations

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


# ── unit: set_task_status is the choke point ───────────────────────────────────


def test_set_status_without_store_arg_is_unchanged() -> None:
    """Backward compatible: omitting store= (every pre-RT-B-008 call site
    outside this module, if any existed) must not raise and must set the
    status exactly as before."""
    store = InMemoryTaskStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.WORKING)

    assert record.task.status.state == TaskState.WORKING


def test_set_status_invokes_persist_status_hook_with_mutated_record() -> None:
    calls: list[TaskState] = []

    class _RecordingStore(InMemoryTaskStore):
        def persist_status(self, record: TaskRecord) -> None:
            calls.append(record.task.status.state)

    store = _RecordingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.COMPLETED, store=store)

    assert calls == [TaskState.COMPLETED], "persist_status must be called exactly once"
    assert record.task.status.state == TaskState.COMPLETED


def test_set_status_persist_status_failure_does_not_raise() -> None:
    """Guarded like tasks_cancel's own call (RT-B-003): a failing durable
    write degrades to an unpersisted status rather than raising out of a
    hot status-transition path."""

    class _FailingStore(InMemoryTaskStore):
        def persist_status(self, record: TaskRecord) -> None:
            raise RuntimeError("durable write failed")

    store = _FailingStore()
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id)
    assert record is not None

    set_task_status(record, TaskState.FAILED, store=store)  # must not raise

    assert record.task.status.state == TaskState.FAILED


# ── ASGI-level: the DOMINANT (non-cancelled) COMPLETED path now invokes
#    persist_status too, not only tasks_cancel's CANCELED transition ──────


async def test_normal_completion_invokes_persist_status_hook(settings, fake_model) -> None:
    """RT-B-008: before this fix, run_task_worker's DoneEvent(ok=True) branch
    (runner.py:1009) called neither persist_status nor persist_messages —
    ``TaskStore.persist_status`` had exactly one call site in the whole SDK
    (``tasks_cancel``). A durable ``TaskStore``'s ``persist_status`` override
    therefore never observed the dominant, non-cancelled COMPLETED
    transition at all, so a task that completes normally could never become
    a contextId continuation candidate on such a store."""
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

    assert TaskState.COMPLETED in calls, (
        "persist_status must be invoked on the normal COMPLETED transition "
        "(runner.py:1009), not only from tasks_cancel"
    )
    # RT-007 (superseding this test's original assertion here): set_task_status
    # remains the choke point for every transition, but no longer flushes
    # persist_status for WORKING by default — see
    # test_rt007_persist_status_working_gate.py for the gating + opt-in
    # coverage this narrowed.
    assert TaskState.WORKING not in calls, (
        "persist_status must NOT be invoked on the WORKING transition that "
        "opens the task unless the store opts in via persist_every_status "
        "(RT-007) — a durable subclass would otherwise take a synchronous "
        "network write on every streamed chunk of every turn"
    )
