"""RT-B-002: a repair_dangling_tool_use failure inside tasks_cancel must not
skip the CANCELED task's terminal publish / close_streams.

``repair_dangling_tool_use``'s RT-005 flush calls
``store.persist_messages(record)`` once the repair/bridge have both run — the
exact override CHANGELOG 0.5.45 / the C-005 registry entry instruct a durable
``TaskStore`` subclasser to add. Before this fix that call sat between the
already-committed CANCELED transition and the terminal-frame publish with no
protection: a persist_messages failure there propagated straight out of
``tasks_cancel`` as an uncaught 500 — never publishing the A2A §5.1-required
final ``Task``, and never calling ``close_streams``, stranding any SSE
subscriber un-sentinel-closed until the TTL sweep.

Uses the direct-call pattern from ``test_f1_close_streams_double_failure.py``
(a bare ``TaskRecord`` + a minimal fake ``Request``/``Response.app`` shim) so
the failure is injected at the exact ``TaskStore`` seam, not via HTTP.

RT-001 (supersedes this module's original RT-B-004 rationale): a prior fix
here rolled the live record's status back to its pre-cancel value whenever
the durable ``persist_messages``/``persist_status`` flush failed, so that
``context_messages()`` would not select a still-terminal record whose
transcript never durably landed. That rollback was itself the bug RT-001
fixed: this endpoint had already returned HTTP 200 with ``state="canceled"``
and published a ``final:true`` canceled frame BEFORE the rollback ran, so the
client's view (canceled, terminal, streams closed) and the live record's view
(silently reverted to non-terminal) diverged permanently — defeating every
``state in TERMINAL_STATES`` guard elsewhere in ``agent/runner.py`` (a
concurrent deferred-background awaiter could flip the "cancelled" task back
to WORKING/FAILED and publish a second terminal frame onto streams this
handler already closed) and letting a second ``:cancel`` call succeed again
instead of failing closed with -32002 ``TaskNotCancelable`` (§5.1).

The in-memory CANCELED transition is now committed unconditionally,
regardless of whether the durable flush succeeds — a flush failure only
skips the durable ``persist_status``/``persist_messages`` write, mirroring
every other terminal transition's ``set_task_status`` gating
(``agent/runner.py``). ``InMemoryTaskStore.get()`` returns the live record by
reference, so the repaired (in-memory, always-lands) transcript IS what
``context_messages()`` returns on the next contextId turn — never the
stale, unrepaired dangling toolUse tail, because the repair's append/bridge
mutation itself cannot fail (only the trailing durable flush can); only a
durable subclass whose own ``get()`` deserializes a fresh copy per call ever
observes the flush failure as a missing transcript.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Response

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.routes.a2a import tasks_cancel
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)


class _RaisesOnPersistMessages(InMemoryTaskStore):
    """Simulates a durable store's override of the RT-005 write hook
    (``TaskStore.persist_messages``) failing on its own write."""

    def persist_messages(self, record: TaskRecord) -> None:
        raise RuntimeError("simulated durable persist_messages failure")


class _FakeApp:
    def __init__(self, store: InMemoryTaskStore) -> None:
        self.state = SimpleNamespace(task_store=store, cors_origins={"https://claude.ai"})


class _FakeRequest:
    def __init__(self, store: InMemoryTaskStore) -> None:
        self.headers: dict[str, str] = {}
        self.app = _FakeApp(store)


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    # A genuine dangling assistant toolUse tail — the same shape a cancel
    # mid-tool-call (GH-150) leaves — so repair_dangling_tool_use actually
    # has something to repair before its persist_messages flush.
    record.messages.append(
        {
            "role": "assistant",
            "content": [
                {"toolUse": {"toolUseId": "call-1", "name": "some_tool", "input": {}}}
            ],
        }
    )
    return record


async def _drain_to_close(sub: Any, timeout: float = 3.0) -> bool:
    async def _loop() -> bool:
        while True:
            item = await sub.get()
            if item is None:  # close sentinel
                return True

    return await asyncio.wait_for(_loop(), timeout=timeout)


@pytest.mark.asyncio
async def test_tasks_cancel_survives_persist_messages_failure() -> None:
    store = _RaisesOnPersistMessages()
    record = _make_record(store)
    sub = store.subscribe(record.task.id)
    request = _FakeRequest(store)

    response = await tasks_cancel(
        record.task.id, request, Response(), identity=_IDENTITY
    )

    assert getattr(response, "status_code", 200) == 200, (
        "RT-B-002: a persist_messages failure must degrade to a missing "
        "repair, not an uncaught 500 (A2A §5.1 requires HTTP 200 + the full "
        "canceled Task from tasks/cancel)"
    )
    body = json.loads(response.body)
    assert body["status"]["state"] == "canceled"

    item = await asyncio.wait_for(sub.get(), timeout=2.0)
    assert item is not None and item.final is True, (
        "the terminal final:true frame must still be published despite the "
        "repair failure"
    )

    closed = await _drain_to_close(sub)
    assert closed, (
        "RT-B-002: tasks_cancel must still close_streams even when "
        "repair_dangling_tool_use's persist_messages flush raises"
    )

    # RT-001: this call's own response claims "canceled" (A2A §5.1), and the
    # live record's status must match it exactly — never rolled back to
    # compensate for the persist_messages failure. A durable-store flush
    # failure is quarantined to a missing durable write, not undone in-memory.
    after = store.get(record.task.id, _IDENTITY)
    assert after is not None
    assert after.task.status.state == "canceled", (
        "RT-001: the response committed to canceled, so the live record "
        f"must too — got {after.task.status.state!r}"
    )

    # RT-001: the task is now genuinely terminal, so a repeat cancel is
    # rejected per A2A §5.1 (-32002 TaskNotCancelable) rather than silently
    # succeeding a second time.
    response2 = await tasks_cancel(
        record.task.id, request, Response(), identity=_IDENTITY
    )
    assert response2.status_code == 409
    body2 = json.loads(response2.body)
    assert body2["error"]["code"] == -32002
    after2 = store.get(record.task.id, _IDENTITY)
    assert after2 is not None
    assert after2.task.status.state == "canceled"


@pytest.mark.asyncio
async def test_tasks_cancel_repair_failure_not_a_continuation_candidate() -> None:
    """RT-001: a durable persist_messages failure must NOT lose the
    already-landed in-memory repair — ``InMemoryTaskStore``'s live-reference
    ``get()`` means context_messages() selects this now-terminal record on
    the next contextId turn, and it must see the REPAIRED transcript (no
    dangling toolUse tail, never ending on 'user'), not the pre-repair
    shape, even though the durable flush of that same repair failed."""
    store = _RaisesOnPersistMessages()
    record = _make_record(store)
    context_id = record.task.context_id
    request = _FakeRequest(store)

    response = await tasks_cancel(
        record.task.id, request, Response(), identity=_IDENTITY
    )
    assert getattr(response, "status_code", 200) == 200
    body = json.loads(response.body)
    assert body["status"]["state"] == "canceled", (
        "the response for THIS cancel call must still report canceled per "
        "A2A §5.1, regardless of the repair outcome"
    )

    assert store.context_messages(context_id, _IDENTITY) == [], (
        "GH-187: a canceled task is never a continuation candidate"
    )
    live = store.get(record.task.id)
    assert live is not None
    messages = live.messages
    assert messages != [], (
        "RT-001: the in-memory repair lands regardless of the durable "
        f"flush's own failure — got {messages!r}"
    )
    assert messages[-1].get("role") != "user", (
        "RT-001 (GH-147 AC3): the repaired transcript must never end on "
        f"'user' — got {messages[-1]!r}"
    )
    last_assistant_turn = messages[0]
    tool_use_ids = {
        block["toolUse"]["toolUseId"]
        for block in last_assistant_turn.get("content", [])
        if isinstance(block, dict) and "toolUse" in block
    }
    resolved_ids = {
        block["toolResult"]["toolUseId"]
        for msg in messages
        for block in msg.get("content", [])
        if isinstance(block, dict) and "toolResult" in block
    }
    assert tool_use_ids <= resolved_ids, (
        "RT-001: every dangling toolUse must have a matching synthetic "
        f"toolResult in the repaired transcript — got {messages!r}"
    )
