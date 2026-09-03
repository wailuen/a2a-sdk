"""RT-B-003 (GH-150/RT-005 follow-up): tasks_cancel mutates
record.task.status in place with no durable write hook.

RT-005 added TaskStore.persist_messages(record) so an out-of-loop repair of
record.messages/pending_tool_results reaches a durable, copy-on-get()
TaskStore. But tasks_cancel (agent_sdk/routes/a2a.py) also mutates
record.task.status directly in the SAME request handler, right before it
calls repair_dangling_tool_use(store=store) — and there was no matching
write hook for that field. A durable store never learned the task went
CANCELED: context_messages() filters candidates on
``r.task.status.state in TERMINAL_STATES``, so the repaired transcript
persist_messages just flushed was never a continuation candidate and was
never replayed.

TaskStore.persist_status(record) closes this the same way persist_messages
closed the messages gap: a no-op default (mirrors the
interrupt_ttl_remaining/persist_messages precedent), called by tasks_cancel
right after it mutates record.task.status.

Full-ASGI-app style, mirroring test_gh150_cancel_dangling_tooluse.py and
test_rt005_gh150_taskstore_persist_messages_hook.py's copy-on-get() shape.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord, TaskStore
from agent_sdk.testing import tool_call


# ── a tool that blocks until the test releases it (so cancel lands mid-turn,
#    exactly like GH-150's own regression shape) ────────────────────────────


class _Signals:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()


signals = _Signals()

rtb003_tools = ToolSet()


class SlowInput(BaseModel):
    pass


@rtb003_tools.tool(tier=1)
async def slow_blocking_tool_rtb003(inp: SlowInput) -> dict[str, Any]:
    signals.started.set()
    await signals.release.wait()
    return {"done": True}


@pytest.fixture
def reset_signals() -> _Signals:
    signals.started = asyncio.Event()
    signals.release = asyncio.Event()
    return signals


def send_body(text: str) -> dict[str, Any]:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


# ── stands in for an AzureTableTaskStore-shaped subclass: get() hands back a
#    FRESH TaskRecord (with its own fresh Task, messages and
#    pending_tool_results) on every call, instead of InMemoryTaskStore's
#    live-object-by-reference get() — mirrors
#    test_rt005_gh150_taskstore_persist_messages_hook.py's _CopyOnGetStore
#    shape (RT-B-010: a get() that leaves messages/pending_tool_results as
#    the SAME list object as the durable record's lets an in-place repair
#    reach durable storage "for free", independent of whether persist_hooks
#    are overridden — a copy-on-get store must break that aliasing on every
#    field a durable subclasser is expected to flush explicitly) ──────────


class _CopyOnGetStore(InMemoryTaskStore):
    def get(self, task_id: str, identity: Any = None) -> TaskRecord | None:
        live = super().get(task_id, identity)
        if live is None:
            return None
        return dataclasses.replace(
            live,
            task=live.task.model_copy(deep=True),
            messages=copy.deepcopy(live.messages),
            pending_tool_results=list(live.pending_tool_results),
        )


def _ends_on_dangling_tool_use(messages: Any) -> bool:
    if not messages or messages[-1].get("role") != "assistant":
        return False
    return any(
        isinstance(block, dict) and "toolUse" in block
        for block in messages[-1].get("content", [])
    )


class _CopyOnGetStoreWithPersistStatusHook(_CopyOnGetStore):
    def persist_status(self, record: TaskRecord) -> None:
        durable = self._records.get(record.task.id)
        if durable is not None:
            durable.task.status = record.task.status


class _CopyOnGetStoreWithBothPersistHooks(_CopyOnGetStoreWithPersistStatusHook):
    def persist_messages(self, record: TaskRecord) -> None:
        durable = self._records.get(record.task.id)
        if durable is not None:
            durable.messages = list(record.messages)
            durable.pending_tool_results = list(record.pending_tool_results)


class _CopyOnGetStorePersistMessagesRaises(_CopyOnGetStoreWithPersistStatusHook):
    """persist_status is a faithful durable write (as above); persist_messages
    simulates a durable store's OWN write failing on its own. tasks_cancel
    flushes the repaired transcript and the CANCELED status via two SEPARATE
    calls, so one can fail independently of the other succeeding — the
    RT-B-007 ordering hazard this store shape exercises."""

    def persist_messages(self, record: TaskRecord) -> None:
        raise RuntimeError("simulated durable persist_messages failure")


@asynccontextmanager
async def _cancel_mid_tool_call(
    store: InMemoryTaskStore, settings, fake_model, reset_signals
) -> AsyncIterator[tuple[str, str]]:
    """Sends a message that blocks inside a tool call, cancels the task
    while it is in flight, and yields (task_id, context_id) — still inside
    the app's lifespan, so the store's records (in particular, whatever
    ``close_all()`` would otherwise evict on shutdown) are still live for
    the caller's own ``store.get()``/``context_messages()`` assertions."""
    agent = make_agent(settings, model_client=fake_model, task_store=store)
    agent.toolsets = agent.toolsets + [rtb003_tools]
    app = agent.build_app()
    fake_model.script(tool_call("slow_blocking_tool_rtb003", {}))
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as client:
            r = await client.post("/v1/message:send", json=send_body("go slow"))
            assert r.status_code == 200, r.text
            task_id = r.json()["id"]
            context_id = r.json()["contextId"]

            await asyncio.wait_for(reset_signals.started.wait(), timeout=2.0)

            r = await client.post(f"/v1/tasks/{task_id}:cancel")
            assert r.status_code == 200, r.text
            assert r.json()["status"]["state"] == "canceled"

            yield task_id, context_id
    app.state.credential_store.close()


# ── base-class default is a no-op (persist_messages/interrupt_ttl_remaining
#    pattern) ────────────────────────────────────────────────────────────


def test_taskstore_persist_status_default_is_noop() -> None:
    from agent_sdk.agent.runner import new_task
    from agent_sdk.auth.identity import Identity

    store = InMemoryTaskStore()
    identity = Identity(kind="api_key", subject="test-runner", admin=True)
    task = new_task()
    record = store.create(task, identity)
    TaskStore.persist_status(store, record)  # must not raise


# ── the actual RT-B-003 regression: a durable copy-on-get store ────────────


async def test_cancel_without_persist_status_override_loses_canceled_status(
    settings, fake_model, reset_signals
) -> None:
    """Documents the exact gap the finding raised: a durable-shaped store
    that does not override persist_status (the pre-existing-subclass case)
    keeps working — but the CANCELED transition never reaches the record
    context_messages() actually reads, so the cancelled task is never a
    continuation candidate."""
    store = _CopyOnGetStore()
    async with _cancel_mid_tool_call(store, settings, fake_model, reset_signals) as (
        task_id,
        context_id,
    ):
        replayed = store.get(task_id)
        assert replayed is not None
        assert replayed.task.status.state != "canceled", (
            "without the hook, a fresh get() never observes the CANCELED transition"
        )

        assert store.context_messages(context_id) == [], (
            "the cancelled task's status never went terminal in durable storage, "
            "so it is never a contextId continuation candidate"
        )


async def test_cancel_with_persist_status_override_survives_durable_get(
    settings, fake_model, reset_signals
) -> None:
    """The fix: a durable TaskStore that overrides persist_status(record)
    gets the CANCELED transition flushed back, so the cancelled task's
    repaired transcript is a contextId continuation candidate again."""
    store = _CopyOnGetStoreWithPersistStatusHook()
    async with _cancel_mid_tool_call(store, settings, fake_model, reset_signals) as (
        task_id,
        context_id,
    ):
        replayed = store.get(task_id)
        assert replayed is not None
        assert replayed.task.status.state == "canceled"

        assert store.context_messages(context_id) != [], (
            "with the hook, the cancelled task is a contextId continuation candidate"
        )


# ── RT-B-010: persist_status alone is not proof persist_messages was ever
#    exercised — a store overriding BOTH must actually flush a REPAIRED
#    (non-dangling) transcript, not merely a non-empty one ─────────────────


async def test_cancel_with_both_persist_hooks_survives_durable_get_without_dangling_tool_use(
    settings, fake_model, reset_signals
) -> None:
    """A durable TaskStore overriding BOTH persist_status and
    persist_messages gets the CANCELED transition AND the repaired
    transcript flushed back: the contextId continuation candidate's
    messages must not still end on the dangling toolUse tail
    repair_dangling_tool_use closed out locally."""
    store = _CopyOnGetStoreWithBothPersistHooks()
    async with _cancel_mid_tool_call(store, settings, fake_model, reset_signals) as (
        task_id,
        context_id,
    ):
        replayed = store.get(task_id)
        assert replayed is not None
        assert replayed.task.status.state == "canceled"
        assert not _ends_on_dangling_tool_use(replayed.messages), (
            "with both hooks overridden, the durable copy must observe the "
            "repaired transcript, not the pre-repair dangling toolUse tail"
        )

        replayed_context = store.context_messages(context_id)
        assert replayed_context != []
        assert not _ends_on_dangling_tool_use(list(replayed_context)), (
            "a contextId continuation must never replay a dangling toolUse tail"
        )


# ── RT-B-007: persist_status and persist_messages are flushed via two
#    SEPARATE calls inside tasks_cancel — one can succeed while the other
#    raises. A durable store whose persist_messages write fails on its own
#    must not leave a terminal (contextId-continuable) record whose
#    transcript still ends on the pre-repair dangling toolUse tail ─────────


async def test_cancel_persist_messages_failure_never_leaks_dangling_transcript(
    settings, fake_model, reset_signals
) -> None:
    """RT-B-007 guard: persist_messages and persist_status are two SEPARATE
    durable calls inside tasks_cancel, so a persist_messages write failure
    (a durable store's own transcript flush erroring) must not still let the
    task become a terminal, contextId-continuable candidate whose transcript
    is the pre-repair dangling toolUse tail — tasks_cancel's own try/except
    degrades the failure to a missing repair rather than an uncaught 500
    (RT-B-002), and must gate the CANCELED status flush on that repair
    having actually landed, not attempt it unconditionally."""
    store = _CopyOnGetStorePersistMessagesRaises()
    async with _cancel_mid_tool_call(store, settings, fake_model, reset_signals) as (
        task_id,
        context_id,
    ):
        replayed_context = store.context_messages(context_id)
        assert not _ends_on_dangling_tool_use(list(replayed_context)), (
            "a persist_messages failure must not leave a dangling-toolUse "
            "transcript reachable via contextId continuation, regardless of "
            "whether persist_status's independent write would otherwise succeed"
        )
