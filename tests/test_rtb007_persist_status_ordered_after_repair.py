"""RT-B-007: ``tasks_cancel`` must flush the repaired transcript
(``persist_messages``, via ``repair_dangling_tool_use``) BEFORE it flushes
the terminal ``CANCELED`` status (``persist_status``) — never the reverse.

RT-B-003 added the ``persist_status`` flush but ordered it BEFORE the
RT-B-002-guarded ``repair_dangling_tool_use`` call. That makes the degraded
path (a durable ``persist_messages`` failure) fail-UNSAFE: the durable store
is left holding a task whose status is terminal ``CANCELED`` but whose
transcript is still the unrepaired dangling ``toolUse`` tail —
``context_messages()``'s ``TERMINAL_STATES`` filter then selects it as a
continuation candidate and replays a transcript Bedrock's Converse API
rejects. Before ``persist_status`` existed, a ``persist_messages`` failure
simply left the task non-terminal in durable storage, so it was never a
continuation candidate at all — strictly safer.

The fix: run the repair first, and flush the CANCELED status only once the
repair (and its ``persist_messages`` flush) has actually succeeded. A
``persist_status`` failure AFTER a successful ``persist_messages`` is
harmless — the task just stays non-terminal in durable storage.

Direct-call pattern from ``test_rtb002_cancel_repair_failure_still_publishes_final.py``
(bare ``TaskRecord`` + a minimal fake ``Request``/``Response`` shim), using a
faithful copy-on-get store that copies BOTH ``task`` and ``messages`` (unlike
RT-B-003's own test double, which copies only ``task``) — the exact shape the
finding was confirmed against.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.routes.a2a import tasks_cancel
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)


class _CopyOnGetStoreRaisingPersistMessages(InMemoryTaskStore):
    """Stands in for a durable (e.g. Azure Table) TaskStore: ``get()`` hands
    back a FRESH copy of both ``task`` and ``messages`` on every call, and
    ``persist_status`` is faithfully overridden (writes the status back to
    the durable record) while ``persist_messages`` fails on its own write —
    the exact seam RT-B-002's guard exists to absorb."""

    def get(self, task_id: str, identity: Any = None) -> TaskRecord | None:
        live = super().get(task_id, identity)
        if live is None:
            return None
        return dataclasses.replace(
            live,
            task=live.task.model_copy(deep=True),
            messages=list(live.messages),
        )

    def persist_status(self, record: TaskRecord) -> None:
        durable = self._records.get(record.task.id)
        if durable is not None:
            durable.task.status = record.task.status

    def persist_messages(self, record: TaskRecord) -> None:
        raise RuntimeError("simulated durable persist_messages failure")


class _FakeApp:
    def __init__(self, store: InMemoryTaskStore) -> None:
        self.state = SimpleNamespace(task_store=store, cors_origins={"https://claude.ai"})


class _FakeRequest:
    def __init__(self, store: InMemoryTaskStore) -> None:
        self.headers: dict[str, str] = {}
        self.app = _FakeApp(store)


class _FakeResponse:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


def _make_dangling_record(store: InMemoryTaskStore) -> TaskRecord:
    task = new_task()
    record = store.create(task, _IDENTITY)
    # A genuine dangling assistant toolUse tail — the same shape a cancel
    # mid-tool-call (GH-150) leaves — so repair_dangling_tool_use actually
    # has something to repair (and flush via persist_messages) before its
    # failure is injected.
    record.messages.append(
        {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": "c1", "name": "some_tool", "input": {}}}
            ],
        }
    )
    return record


@pytest.mark.asyncio
async def test_persist_messages_failure_never_leaves_durable_status_terminal() -> None:
    """RT-B-007: with persist_messages failing, the durable store must NOT
    observe the task as terminal — otherwise context_messages() would select
    it and replay the still-dangling toolUse tail."""
    store = _CopyOnGetStoreRaisingPersistMessages()
    record = _make_dangling_record(store)
    request = _FakeRequest(store)
    response = _FakeResponse()

    result = await tasks_cancel(record.task.id, request, response, identity=_IDENTITY)

    assert getattr(result, "status_code", 200) == 200

    durable = store._records[record.task.id]
    assert durable.task.status.state != "canceled", (
        "RT-B-007: a persist_messages failure must NOT be preceded (or "
        "followed) by a persist_status flush — the durable status must stay "
        "non-terminal, exactly like the pre-RT-B-003 behaviour"
    )

    assert store.context_messages(record.task.context_id) == [], (
        "RT-B-007: a task whose repaired transcript never reached durable "
        "storage must never be selected as a contextId continuation "
        "candidate — replaying its dangling toolUse tail is the exact "
        "shape Bedrock's Converse API rejects"
    )


@pytest.mark.asyncio
async def test_persist_status_still_flushes_after_successful_repair() -> None:
    """Companion GREEN case: when persist_messages succeeds, persist_status
    still flushes the CANCELED transition (RT-B-003's original guarantee is
    preserved, just reordered)."""

    class _CopyOnGetStore(InMemoryTaskStore):
        def get(self, task_id: str, identity: Any = None) -> TaskRecord | None:
            live = super().get(task_id, identity)
            if live is None:
                return None
            return dataclasses.replace(
                live,
                task=live.task.model_copy(deep=True),
                messages=list(live.messages),
            )

        def persist_status(self, record: TaskRecord) -> None:
            durable = self._records.get(record.task.id)
            if durable is not None:
                durable.task.status = record.task.status

        def persist_messages(self, record: TaskRecord) -> None:
            durable = self._records.get(record.task.id)
            if durable is not None:
                durable.messages = list(record.messages)

    store = _CopyOnGetStore()
    record = _make_dangling_record(store)
    request = _FakeRequest(store)
    response = _FakeResponse()

    result = await tasks_cancel(record.task.id, request, response, identity=_IDENTITY)

    assert getattr(result, "status_code", 200) == 200
    durable = store._records[record.task.id]
    assert durable.task.status.state == "canceled"
    assert store.context_messages(record.task.context_id) != []
