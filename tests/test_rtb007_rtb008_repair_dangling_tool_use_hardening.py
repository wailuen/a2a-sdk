"""RT-B-007 + RT-B-008: two hardening fixes inside
``agent/runner.py::repair_dangling_tool_use`` itself, independent of any
``TaskStore``.

RT-B-007: every synthetic ``toolResult`` block built for a turn with several
dangling ``toolUseId``s used to embed the SAME ``content`` list object by
reference — the caller's own ``default_content`` (or a shared pending/
override entry) — across every one of them. A later mutation of that list by
the caller, or by a store's serializer, silently rewrote every one of those
transcript entries at once.

RT-B-008 (superseded by RT-005): the tail-message read (``messages[-1].get
("role")``) had no ``isinstance(messages[-1], dict)`` guard, unlike the
``pending_tool_results`` loop just above it (which already checks each
block). A non-dict tail entry raised ``AttributeError`` — which, per
RT-B-002, would have escaped every caller of this helper before that fix.
The guard's original outcome ("nothing to repair", ``False``/quiet no-op)
was itself superseded by RT-005 (agent/loop.py's ``close_dangling_tool_use``,
tests/test_rt005_non_dict_tail_unreadable_gate.py): an unreadable tail is no
longer distinguishable from a confirmed-clean one, so it now raises
``DanglingToolUseUnreadable`` instead — caught by
``repair_dangling_tool_use_safe``, never by this lower-level function, same
as every other unreadable-tail shape.

Unit-level (agent_sdk.agent.runner + agent_sdk.tasks.memory only — no
FastAPI app boot), mirroring
tests/test_rt005_gh150_taskstore_persist_messages_hook.py's direct-store-
layer style.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_sdk.agent.loop import DanglingToolUseUnreadable
from agent_sdk.agent.runner import repair_dangling_tool_use
from agent_sdk.models.a2a import Task, TaskState, TaskStatus
from agent_sdk.tasks.store import TaskRecord


def _record(messages: list[Any]) -> TaskRecord:
    task = Task(id="t1", contextId="c1", status=TaskStatus(state=TaskState.WORKING))
    record = TaskRecord(task=task, identity=("api_key", "test"), created_at=0.0, updated_at=0.0)
    record.messages = messages
    return record


# ── RT-B-007: no shared content-list aliasing across dangling toolUseIds ───


def test_multiple_dangling_ids_get_independent_content_lists() -> None:
    default_content = [{"text": "cancelled"}]
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "tu1", "name": "a", "input": {}}},
                    {"toolUse": {"toolUseId": "tu2", "name": "b", "input": {}}},
                ],
            },
        ]
    )

    repair_dangling_tool_use(record, default_content=default_content)

    # bridge_trailing_user unconditionally appends an assistant bridge turn
    # after the synthetic toolResult 'user' message, so the result message
    # itself is the second-to-last entry.
    result_message = record.messages[-2]
    blocks = [b["toolResult"] for b in result_message["content"] if "toolResult" in b]
    assert len(blocks) == 2

    content_1 = blocks[0]["content"]
    content_2 = blocks[1]["content"]
    assert content_1 is not content_2, (
        "RT-B-007: each dangling toolUseId's synthetic toolResult must own "
        "its own content list, not share the same object across entries"
    )
    assert content_1 is not default_content and content_2 is not default_content, (
        "RT-B-007: neither transcript entry may alias the caller's own "
        "default_content list"
    )

    # Mutating one entry's content must not leak into the other, or into the
    # caller's original default_content.
    content_1.append({"text": "mutated"})
    assert content_2 == [{"text": "cancelled"}]
    assert default_content == [{"text": "cancelled"}]


def test_multiple_dangling_ids_get_independently_mutable_content_blocks() -> None:
    """RT-B-206: RT-B-007's own fix (``list(content)``) only copies the OUTER
    list — the dict elements inside it are still the SAME objects shared
    across every dangling id's synthetic toolResult (and the caller's own
    default_content). Mutating one BLOCK in place — e.g. a store's
    serializer normalising a content block — must not rewrite the others,
    the exact parenthetical RT-B-007's own docstring left open."""
    default_content = [{"text": "cancelled"}]
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "tu1", "name": "a", "input": {}}},
                    {"toolUse": {"toolUseId": "tu2", "name": "b", "input": {}}},
                ],
            },
        ]
    )

    repair_dangling_tool_use(record, default_content=default_content)

    result_message = record.messages[-2]
    blocks = [b["toolResult"] for b in result_message["content"] if "toolResult" in b]
    content_1 = blocks[0]["content"]
    content_2 = blocks[1]["content"]

    content_1[0]["text"] = "mutated in place"
    assert content_2[0]["text"] == "cancelled", (
        "RT-B-206: mutating one dangling id's content block in place must "
        "not rewrite a sibling id's synthetic toolResult"
    )
    assert default_content[0]["text"] == "cancelled", (
        "RT-B-206: mutating one dangling id's content block in place must "
        "not rewrite the caller's own default_content"
    )


def test_pending_result_content_list_not_aliased_into_transcript() -> None:
    """The same aliasing risk applies to a pending_tool_results fallback
    (tr.get("content", default_content)) — copy at the embed point closes it
    regardless of which source (default/pending/override) supplied the list."""
    pending_content = [{"json": {"ok": True}}]
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "tu1", "name": "a", "input": {}}}],
            },
        ]
    )
    record.pending_tool_results.append(
        {"toolResult": {"toolUseId": "tu1", "content": pending_content, "status": "success"}}
    )

    repair_dangling_tool_use(record, default_content=[{"text": "cancelled"}])

    result_message = record.messages[-2]
    embedded = result_message["content"][0]["toolResult"]["content"]
    assert embedded == pending_content
    assert embedded is not pending_content, (
        "RT-B-007: the transcript's content list must be a copy of the "
        "pending block's content, not the same object"
    )
    embedded.append({"text": "mutated"})
    assert pending_content == [{"json": {"ok": True}}]


# ── RT-B-008: a non-dict tail message must not raise ────────────────────────


def test_non_dict_tail_message_raises_unreadable() -> None:
    """RT-005 (supersedes this module's original RT-B-008 expectation): a
    durable store deserialising loosely (or a future caller appending
    something other than a plain dict) can no longer be confirmed clean, so
    ``close_dangling_tool_use`` raises ``DanglingToolUseUnreadable`` instead
    of quietly treating it as "nothing to repair" — this function itself
    stays unguarded (only ``repair_dangling_tool_use_safe`` catches it), same
    as it already does for every other unreadable-tail shape (RT-001/RT-004
    above)."""
    record = _record(["not a dict"])

    with pytest.raises(DanglingToolUseUnreadable):
        repair_dangling_tool_use(record, default_content=[{"text": "cancelled"}])


def test_non_dict_tail_message_with_object_raises_unreadable() -> None:
    class _NotAMessage:
        pass

    record = _record([{"role": "user", "content": [{"text": "go"}]}, _NotAMessage()])

    with pytest.raises(DanglingToolUseUnreadable):
        repair_dangling_tool_use(record, default_content=[{"text": "cancelled"}])
