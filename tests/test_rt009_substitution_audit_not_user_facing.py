"""RT-009: the GH-148 $ref-substitution audit must never surface as
user-facing agent chat text.

Before this fix, ``agent/loop.py`` recorded a $ref substitution as a
``NoteEvent``, which both transports render straight into the conversation
the end user sees:

- ``runner.py`` maps ``NoteEvent`` to
  ``set_task_status(record, TaskState.WORKING, _agent_message(record, event.note))``
  — an A2A agent ``Message`` in the task status stream.
- ``ag_ui.py`` maps it to a ``CUSTOM`` ``AGENT_NOTE`` frame the console
  renders as a chat line.

So "tool 'get_entity_detail' field 'entity_id': substituted $ref:entity_id"
became visible chat noise on every substituted field of every call. The fix
records the substitution as a dedicated, non-user-facing ``AuditEvent``:
folded into ``TaskStatusUpdateEvent.metadata`` (never ``status.message``) on
A2A, and produces no AG-UI frame at all (falls through the router's default
"no frame" case, same as ``UsageEvent``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.events import AuditEvent, NoteEvent
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, ReuseKind
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.routes.ag_ui import _RunMapper
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

pytestmark = pytest.mark.asyncio

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class ResolveEntityIn(BaseModel):
    name: str


class EntityDetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


_tools = ToolSet()


@_tools.tool(tier=1)
async def resolve_entity(inp: ResolveEntityIn) -> Any:
    """Resolve a company name to its canonical entity id."""
    return Reusable(value="ENT_5831", kind="entity_id", label=inp.name)


@_tools.tool(tier=1)
async def get_entity_detail(inp: EntityDetailIn) -> str:
    """Fetch details for a resolved entity id."""
    return f"detail-for-{inp.entity_id}"


_REGISTRY = ToolRegistry([_tools], {})


async def _drain(sub: Any, timeout: float = 3.0) -> list[Any]:
    async def _loop() -> list[Any]:
        items: list[Any] = []
        while True:
            item = await sub.get()
            if item is None:
                return items
            items.append(item)

    return await asyncio.wait_for(_loop(), timeout=timeout)


async def test_substitution_audit_never_lands_in_status_message(sdk_caplog) -> None:
    store = InMemoryTaskStore()

    # Turn 1: resolve the entity, folding a __resolved__ marker into messages.
    task1 = new_task()
    record1 = store.create(task1, _IDENTITY)
    record1.messages.append(
        {"role": "user", "content": [{"text": "resolve PT IMC Pelita Logistik"}]}
    )
    model1 = FakeModelClient().script(
        tool_call("resolve_entity", {"name": "PT IMC Pelita Logistik"}), reply("resolved")
    )
    await run_task_worker(
        store=store, record=record1, model=model1, registry=_REGISTRY, adapters={},
        skills=None, system="test", capabilities=_CAPABILITIES, policies=LoopPolicies(),
    )

    # Turn 2: separate task, same transcript — a downstream tool consumes
    # $ref:entity_id, triggering the substitution audit path.
    task2 = new_task()
    record2 = store.create(task2, _IDENTITY)
    record2.messages = list(record1.messages)
    record2.messages.append({"role": "user", "content": [{"text": "get details"}]})
    sub = store.subscribe(task2.id)

    model2 = FakeModelClient().script(
        tool_call("get_entity_detail", {"entity_id": "$ref:entity_id"}), reply("done")
    )

    with sdk_caplog("agent_sdk.agent.runner", logging.INFO) as records:
        await run_task_worker(
            store=store, record=record2, model=model2, registry=_REGISTRY, adapters={},
            skills=None, system="test", capabilities=_CAPABILITIES, policies=LoopPolicies(),
        )
        items = await _drain(sub)

    # (a) auditable: an AuditEvent was actually emitted, and it never carries
    # the resolved value or the label (SI-2).
    audit_events = [it.event for it in items if isinstance(it.event, AuditEvent)]
    assert audit_events, "substitution must still be recorded as an auditable event"
    audit = audit_events[0]
    assert audit.code == "reuse_substitution"
    assert "ENT_5831" not in repr(audit.detail)
    assert "PT IMC Pelita Logistik" not in repr(audit.detail)
    assert audit.detail.get("tool_name") == "get_entity_detail"
    assert audit.detail.get("field_name") == "entity_id"
    assert audit.detail.get("kind") == "entity_id"

    # (b) never a NoteEvent for this — that channel is user-facing chat text.
    assert not any(isinstance(it.event, NoteEvent) for it in items)

    # (c) never surfaced through status.message text on any published frame.
    for it in items:
        if it.frame is None:
            continue
        message = it.frame.get("status", {}).get("message")
        if message is None:
            continue
        for part in message.get("parts", []):
            text = part.get("text", "")
            assert "substituted" not in text, f"audit text leaked into status.message: {text!r}"
            assert "entity_id" not in text or "get_entity_detail" not in text, (
                f"substitution audit text leaked into status.message: {text!r}"
            )

    # (d) the final record's status.message is untouched by the audit event.
    rec = store.get(task2.id)
    assert rec is not None
    final_message = rec.task.status.message
    if final_message is not None:
        for part in final_message.parts:
            assert "substituted" not in getattr(part, "text", ""), (
                "audit note leaked into final task status message"
            )

    # (e) the audit frame carries the record in metadata, not message text —
    # inspectable structured state, per the AC.
    audit_frames = [
        it.frame for it in items
        if it.frame is not None and (it.frame.get("metadata") or {}).get("audit")
    ]
    assert audit_frames, "expected the audit record to be inspectable via frame metadata"
    assert audit_frames[0]["metadata"]["audit"]["code"] == "reuse_substitution"

    # (f) also logged server-side (stored-state inspectability independent
    # of which transport the client used).
    assert any("reuse_substitution" in r.getMessage() for r in records), (
        "expected the substitution to be logged server-side"
    )


async def test_audit_frame_status_message_is_none_even_after_preceding_text() -> None:
    """RT-A-003: a text segment right before the substituting tool call must
    not leak into the AuditEvent's own status-update frame. ``_status_frame``
    re-serializes ``record.task.status`` as-is, and the TextEvent handler sets
    ``status.message`` to the agent's chat sentence before the AuditEvent is
    ever reached — if the AuditEvent branch reuses that same status verbatim,
    its frame carries the *previous* chat sentence a second time."""
    store = InMemoryTaskStore()

    task1 = new_task()
    record1 = store.create(task1, _IDENTITY)
    record1.messages.append(
        {"role": "user", "content": [{"text": "resolve PT IMC Pelita Logistik"}]}
    )
    model1 = FakeModelClient().script(
        tool_call("resolve_entity", {"name": "PT IMC Pelita Logistik"}), reply("resolved")
    )
    await run_task_worker(
        store=store, record=record1, model=model1, registry=_REGISTRY, adapters={},
        skills=None, system="test", capabilities=_CAPABILITIES, policies=LoopPolicies(),
    )

    task2 = new_task()
    record2 = store.create(task2, _IDENTITY)
    record2.messages = list(record1.messages)
    record2.messages.append({"role": "user", "content": [{"text": "get details"}]})
    sub = store.subscribe(task2.id)

    # The same model turn carries BOTH a chat sentence and the substituting
    # tool call — this is what actually happens when a model narrates before
    # acting; it is what makes the TextEvent precede the AuditEvent.
    model2 = FakeModelClient().script(
        tool_call(
            "get_entity_detail", {"entity_id": "$ref:entity_id"}, text="Let me look that up."
        ),
        reply("done"),
    )

    await run_task_worker(
        store=store, record=record2, model=model2, registry=_REGISTRY, adapters={},
        skills=None, system="test", capabilities=_CAPABILITIES, policies=LoopPolicies(),
    )
    items = await _drain(sub)

    text_frames = [
        it.frame for it in items
        if it.frame is not None and it.event is not None
        and it.frame.get("status", {}).get("message") is not None
        and (it.frame.get("metadata") or {}).get("audit") is None
    ]
    assert text_frames, "expected the preceding text segment to publish its own status frame"
    assert any(
        part.get("text") == "Let me look that up."
        for frame in text_frames
        for part in frame["status"]["message"].get("parts", [])
    )

    audit_frames = [
        it.frame for it in items
        if it.frame is not None and (it.frame.get("metadata") or {}).get("audit")
    ]
    assert audit_frames, "expected the audit record to be inspectable via frame metadata"
    assert audit_frames[0]["status"].get("message") is None, (
        "audit frame must not re-emit the preceding chat sentence as status.message: "
        f"{audit_frames[0]['status'].get('message')!r}"
    )


async def test_ag_ui_translator_emits_no_frame_for_audit_event() -> None:
    """AuditEvent must fall through AG-UI's default no-frame case — the
    console must never render it as a chat line (contrast the old NoteEvent
    -> CUSTOM AGENT_NOTE mapping this replaces for the substitution audit)."""
    mapper = _RunMapper(thread_id="t1", run_id="r1", capabilities=_CAPABILITIES)
    frames = mapper.map(
        AuditEvent(
            code="reuse_substitution",
            detail={"tool_name": "get_entity_detail", "field_name": "entity_id", "kind": "entity_id"},
        )
    )
    assert frames == []
