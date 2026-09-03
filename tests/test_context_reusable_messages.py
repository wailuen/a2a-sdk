"""Store-level tests for InMemoryTaskStore.context_reusable_messages and
context_messages (RT-001 / RT-004 / RT-009 / RT-010).

RT-001: routes/ag_ui.py seeded run_loop's cross-run resolved_index from
``TaskStore.context_messages(thread_id, identity)`` — the single MOST
RECENT terminal task's ``messages`` only. Every AG-UI ``TaskRecord.messages``
is scoped to that one run's own folded transcript (never the prior task's,
unlike A2A), so a ``__resolved__`` marker folded in run N is visible only
while run N is the newest terminal task in the context. One intervening
unrelated run makes it the newest instead, and run N's marker is gone —
the exact one-hop decay this method exists to fix by scanning EVERY terminal
task in the context, not just the latest.

RT-009: the reuse-index seed (``context_reusable_messages``) has never
bypassed per-identity filtering for an admin api_key identity — it is a
covert side channel with no user-visible frame, so it applies the identity
filter even to an admin caller.

RT-004: ``context_messages`` (A2A's carrier) USED to bypass the identity
filter for an admin api_key identity (framed as "operator task inspection")
and, in a follow-up, stripped only the ``__resolved__`` marker half of what
that bypass returned while still returning the surrounding transcript to a
cross-identity admin caller — a wave's own redteam then documented that
remaining transcript leak as intended SDK policy without ever putting it to
the user. Both the bypass and the marker-stripping mitigation are gone:
``context_messages`` now applies the identity filter exactly like
``context_reusable_messages`` always has, admin or not. Genuine operator
inspection of another identity's task remains available, safely, as a read
that never seeds a new task's model context — ``GET /v1/tasks/{id}``,
covered elsewhere (not by this file).

RT-010: ``context_reusable_messages`` scans EVERY terminal task in a
context with no bound on task count or transcript size. It now caps the
number of terminal tasks scanned (newest first) and returns only the
``__resolved__`` marker content items ``scan_resolved`` reads, not full
transcripts.
"""

from __future__ import annotations

from agent_sdk.agent.reuse import RESOLVED_MARKER_KEY
from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState, TaskStatus
from agent_sdk.tasks.memory import MAX_REUSABLE_TASKS, InMemoryTaskStore

_OWNER = Identity(kind="api_key", subject="owner", admin=False)
_OTHER = Identity(kind="api_key", subject="other", admin=False)
_ADMIN = Identity(kind="api_key", subject="admin", admin=True)


def _complete(store: InMemoryTaskStore, context_id: str, identity: Identity, text: str):
    task = new_task(context_id)
    record = store.create(task, identity)
    record.messages.append({"role": "user", "content": [{"text": text}]})
    record.task.status = TaskStatus(state=TaskState.COMPLETED)
    return record


def _resolved_marker_block(kind: str, label: str, value: str) -> dict:
    return {
        "toolResult": {
            "toolUseId": "call-1",
            "content": [{"json": {RESOLVED_MARKER_KEY: {"kind": kind, "label": label, "value": value}}}],
        }
    }


def _complete_with_marker(
    store: InMemoryTaskStore, context_id: str, identity: Identity, *, kind: str, value: str
):
    task = new_task(context_id)
    record = store.create(task, identity)
    record.messages.append(
        {"role": "user", "content": [_resolved_marker_block(kind, "label", value)]}
    )
    record.task.status = TaskStatus(state=TaskState.COMPLETED)
    return record


def _marker_values(combined: list[dict]) -> list[str]:
    """RT-010: context_reusable_messages() now returns only marker content
    (extract_resolved_markers), never full transcript text — so tests that
    care about which/how-many tasks were scanned assert on marker VALUES,
    not on the plain "text" shape the pre-RT-010 contract returned."""
    return [
        item["json"][RESOLVED_MARKER_KEY]["value"]
        for message in combined
        for block in message.get("content", [])
        if isinstance(block.get("toolResult"), dict)
        for item in block["toolResult"].get("content", [])
    ]


def test_scans_every_terminal_task_not_only_the_latest() -> None:
    store = InMemoryTaskStore()
    ctx = "thread-1"
    _complete_with_marker(store, ctx, _OWNER, kind="entity_id", value="run-1")
    _complete_with_marker(store, ctx, _OWNER, kind="entity_id", value="run-2")
    _complete_with_marker(store, ctx, _OWNER, kind="entity_id", value="run-3")

    combined = store.context_reusable_messages(ctx, _OWNER)
    assert _marker_values(combined) == ["run-1", "run-2", "run-3"], (
        "must concatenate every terminal task's markers, oldest first, "
        "not only the single most recent one"
    )


def test_empty_when_no_terminal_task_exists() -> None:
    store = InMemoryTaskStore()
    assert store.context_reusable_messages("no-such-thread", _OWNER) == []


def test_non_terminal_task_excluded() -> None:
    store = InMemoryTaskStore()
    ctx = "thread-2"
    task = new_task(ctx)
    record = store.create(task, _OWNER)
    record.messages.append({"role": "user", "content": [{"text": "still-working"}]})
    # deliberately left in the default SUBMITTED (non-terminal) state

    assert store.context_reusable_messages(ctx, _OWNER) == []


def test_other_identity_excluded_for_non_admin_caller() -> None:
    store = InMemoryTaskStore()
    ctx = "thread-3"
    _complete(store, ctx, _OTHER, "belongs-to-other")

    assert store.context_reusable_messages(ctx, _OWNER) == []


def test_admin_identity_does_not_bypass_the_identity_filter() -> None:
    """RT-009: unlike context_messages(), an admin api_key caller must not
    see another identity's messages through this method."""
    store = InMemoryTaskStore()
    ctx = "thread-4"
    _complete(store, ctx, _OTHER, "belongs-to-other")

    assert store.context_reusable_messages(ctx, _ADMIN) == [], (
        "admin override must not leak another identity's task transcript "
        "into the reuse-index seed"
    )


def test_context_messages_admin_no_longer_bypasses_the_identity_filter() -> None:
    """RT-004: context_messages()'s admin bypass (previously framed as
    "operator task inspection") is removed — it fed a foreign identity's
    transcript straight into the admin's OWN new task and the model's
    context, not a read-only view, so it is now identity-scoped exactly
    like context_reusable_messages() has always been. The A2A counterpart
    to test_admin_identity_does_not_bypass_the_identity_filter above."""
    store = InMemoryTaskStore()
    ctx = "thread-5"
    _complete(store, ctx, _OTHER, "belongs-to-other")

    assert store.context_messages(ctx, _ADMIN) == [], (
        "admin override must not leak another identity's task transcript "
        "into a fresh continuation on their contextId"
    )


def test_context_messages_admin_no_longer_inherits_resolved_marker_from_other_identity() -> None:
    """RT-004: an admin api_key caller who supplies another identity's
    contextId must not have that identity's resolved values — or any of
    their transcript — enter their own new task's messages."""
    store = InMemoryTaskStore()
    ctx = "thread-7"
    _complete_with_marker(store, ctx, _OTHER, kind="entity_id", value="ENT_5831")

    assert store.context_messages(ctx, _ADMIN) == [], (
        "a cross-identity task's transcript, markers included, must never "
        "reach an admin caller through context_messages()"
    )


def test_context_messages_same_identity_marker_survives_unstripped() -> None:
    """Contrast case: the identity filter only excludes a DIFFERENT
    identity's task — a caller continuing their OWN prior task keeps
    seeing their own __resolved__ marker verbatim."""
    store = InMemoryTaskStore()
    ctx = "thread-8"
    _complete_with_marker(store, ctx, _OWNER, kind="entity_id", value="ENT_5831")

    replayed = store.context_messages(ctx, _OWNER)
    found = any(
        RESOLVED_MARKER_KEY in item.get("json", {})
        for message in replayed
        for block in message.get("content", [])
        if isinstance(block.get("toolResult"), dict)
        for item in block["toolResult"].get("content", [])
        if isinstance(item, dict)
    )
    assert found, "own-identity continuation must keep its own resolved marker"


def test_context_messages_admin_own_task_marker_survives_unstripped() -> None:
    """An admin continuing THEIR OWN prior task (no identity mismatch in
    play) also keeps its marker — the identity filter excludes a
    DIFFERENT identity's task, not an admin's own, admin status aside."""
    store = InMemoryTaskStore()
    ctx = "thread-9"
    _complete_with_marker(store, ctx, _ADMIN, kind="entity_id", value="ENT_5831")

    replayed = store.context_messages(ctx, _ADMIN)
    found = any(
        RESOLVED_MARKER_KEY in item.get("json", {})
        for message in replayed
        for block in message.get("content", [])
        if isinstance(block.get("toolResult"), dict)
        for item in block["toolResult"].get("content", [])
        if isinstance(item, dict)
    )
    assert found, "an admin's own task must keep its own resolved marker"


def test_no_identity_filter_when_identity_is_none() -> None:
    store = InMemoryTaskStore()
    ctx = "thread-6"
    _complete_with_marker(store, ctx, _OWNER, kind="entity_id", value="owner-run")
    _complete_with_marker(store, ctx, _OTHER, kind="entity_id", value="other-run")

    combined = store.context_reusable_messages(ctx, None)
    assert _marker_values(combined) == ["owner-run", "other-run"]


# ── RT-010: bounded scan ─────────────────────────────────────────────────


def test_returns_only_marker_content_not_full_transcript() -> None:
    """RT-010: scan_resolved only ever reads a __resolved__ marker's json
    block, so context_reusable_messages() must not return whole
    transcripts — plain text and non-marker tool content must be dropped,
    only the marker-bearing content items kept."""
    store = InMemoryTaskStore()
    ctx = "thread-10"
    task = new_task(ctx)
    record = store.create(task, _OWNER)
    record.messages.extend(
        [
            {"role": "user", "content": [{"text": "a lot of unrelated conversation text"}]},
            {"role": "assistant", "content": [{"toolUse": {"toolUseId": "call-1", "name": "resolve_entity", "input": {}}}]},
            {"role": "user", "content": [_resolved_marker_block("entity_id", "label", "ENT_5831")]},
        ]
    )
    record.task.status = TaskStatus(state=TaskState.COMPLETED)

    combined = store.context_reusable_messages(ctx, _OWNER)
    assert combined, "the marker itself must still be returned"
    for message in combined:
        assert message.get("role") == "user"
        for block in message.get("content", []):
            tool_result = block.get("toolResult")
            assert isinstance(tool_result, dict), "only marker-bearing toolResult blocks survive"
            for item in tool_result.get("content", []):
                payload = item.get("json")
                assert isinstance(payload, dict) and RESOLVED_MARKER_KEY in payload, (
                    "every surviving content item must be a __resolved__ marker, "
                    f"not {item!r}"
                )
    assert not any(
        "unrelated conversation text" in str(message) for message in combined
    ), "plain text must never be carried into the reuse-index seed"


def test_terminal_task_scan_is_capped_newest_first() -> None:
    """RT-010: with more terminal tasks in a context than the cap, only the
    newest MAX_REUSABLE_TASKS are scanned — unbounded growth over a
    long-lived thread's full history must not happen on every request."""
    store = InMemoryTaskStore()
    ctx = "thread-11"
    total = MAX_REUSABLE_TASKS + 5
    for i in range(total):
        _complete_with_marker(store, ctx, _OWNER, kind="entity_id", value=f"ENT_{i}")

    combined = store.context_reusable_messages(ctx, _OWNER)
    values = _marker_values(combined)
    assert len(values) == MAX_REUSABLE_TASKS, (
        f"expected exactly {MAX_REUSABLE_TASKS} markers (the cap), got {len(values)}"
    )
    # newest-first selection, then restored to oldest-first output order:
    # the OLDEST 5 tasks (ENT_0..ENT_4) must be the ones dropped.
    assert values[0] == "ENT_5", values
    assert values[-1] == f"ENT_{total - 1}", values


def test_max_reusable_tasks_is_a_class_attribute() -> None:
    """RT-006: the base-class docstring for context_reusable_messages()
    points implementers at ``InMemoryTaskStore.MAX_REUSABLE_TASKS`` as the
    in-memory store's cap. That pointer must resolve — a class attribute of
    that exact name must exist, not just the module-level constant it
    defaults to."""
    assert hasattr(InMemoryTaskStore, "MAX_REUSABLE_TASKS")
    assert InMemoryTaskStore.MAX_REUSABLE_TASKS == MAX_REUSABLE_TASKS


def test_subclass_can_override_max_reusable_tasks_cap() -> None:
    """RT-006: the cap must be genuinely overridable per subclass, not just
    documented as a class attribute while the method still closes over the
    module constant directly — otherwise a subclass setting the class
    attribute silently has no effect on scan behaviour."""

    class NarrowCapStore(InMemoryTaskStore):
        MAX_REUSABLE_TASKS = 3

    store = NarrowCapStore()
    ctx = "thread-narrow-cap"
    for i in range(5):
        _complete_with_marker(store, ctx, _OWNER, kind="entity_id", value=f"ENT_{i}")

    combined = store.context_reusable_messages(ctx, _OWNER)
    values = _marker_values(combined)
    assert len(values) == 3, (
        f"subclass override of MAX_REUSABLE_TASKS had no effect, got {values!r}"
    )
    assert values == ["ENT_2", "ENT_3", "ENT_4"], values
