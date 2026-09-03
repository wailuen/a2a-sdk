"""RT-004 (agent/runner.py review): ``repair_dangling_tool_use_safe`` must
report ``False`` — not safe to persist — for a dangling ``toolUse`` tail that
is present but unreadable, not only for one that raises through some other
unrelated cause.

Before this fix, ``close_dangling_tool_use``'s RT-B-008/RT-001 hardening
(``agent/loop.py``) made a malformed dangling tail — a non-list ``content``,
a ``toolUse`` value that is not a dict, or one missing ``toolUseId`` —
degrade to "nothing to repair" and return ``False`` WITHOUT raising, exactly
the same signal a genuinely clean (non-dangling) tail produces.
``repair_dangling_tool_use`` (``agent/runner.py``) ignored that return value,
so ``repair_dangling_tool_use_safe`` reported ``True``, and
``set_task_status``'s ``repaired`` gate then durably flushed the
still-unrepaired transcript AND committed the terminal status over it — the
precise fail-open the gate exists to prevent.

Fix: ``close_dangling_tool_use`` now raises ``DanglingToolUseUnreadable``
for that shape (distinct from returning ``False`` for a tail that genuinely
carries no ``toolUse`` block at all), ``repair_dangling_tool_use`` lets it
propagate, and ``repair_dangling_tool_use_safe`` — which already catches any
in-memory repair failure — reports ``False`` for it like any other.

RT-006 (debug round 4) narrows "that shape". The original fix used
"``content`` is not a list" as its unreadability test, which swept in a plain
``str`` tail — a shape that provably cannot contain a ``toolUse`` block at
all, and one both other tail-shape helpers in ``agent/loop.py``
(``_is_user_turn_boundary``, ``append_assistant_turn``) already read as text.
That false unreadable failed the persist gate for transcripts that were never
dangling, permanently stranding a durable record non-terminal. The
unreadability test is now "could this be carrying a ``toolUse`` claim I
cannot read": a ``str``/``bytes`` or empty ``content`` is clean, a bare
``dict`` or any other non-sequence still raises. See
``tests/test_dbg4_plain_text_assistant_tail.py`` for the harm chain.

This module pins the WRITE-side gate end-to-end (``repair_dangling_tool_use_safe``
→ ``set_task_status``, with neither durable hook firing) plus the low-level
``close_dangling_tool_use`` contract and the READ-side (``bridge_context_messages``)
graceful degrade, both of which route through the same shared fold rule
(C-018) and must not regress independently.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_sdk.agent.loop import (
    DanglingToolUseUnreadable,
    bridge_context_messages,
    close_dangling_tool_use,
)
from agent_sdk.agent.runner import repair_dangling_tool_use_safe, set_task_status
from agent_sdk.models.a2a import Task, TaskState, TaskStatus
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord


def _record(messages: list[Any]) -> TaskRecord:
    task = Task(id="t1", contextId="c1", status=TaskStatus(state=TaskState.WORKING))
    record = TaskRecord(task=task, identity=("api_key", "test"), created_at=0.0, updated_at=0.0)
    record.messages = messages
    return record


_MALFORMED_TAIL_TOOLUSE_NOT_DICT = [
    {"role": "user", "content": [{"text": "go"}]},
    {"role": "assistant", "content": [{"toolUse": "not-a-dict"}]},
]

_MALFORMED_TAIL_MISSING_TOOLUSEID = [
    {"role": "user", "content": [{"text": "go"}]},
    {"role": "assistant", "content": [{"toolUse": {"name": "t", "input": {}}}]},
]

_MALFORMED_TAIL_NON_LIST_CONTENT = [
    {"role": "user", "content": [{"text": "go"}]},
    # RT-006 (debug round 4): this case used to be the string "not-a-list".
    # A ``str`` provably cannot contain a ``toolUse`` block, so calling it
    # unreadable was a FALSE positive that failed the persist gate for a
    # transcript that was never dangling — see the module docstring and
    # ``tests/test_dbg4_plain_text_assistant_tail.py``. A bare ``dict`` is
    # the shape that genuinely CAN be an attempted, unreadable toolUse claim
    # (a durable store deserialising a single block loosely), so it is what
    # this "content is not a list" case must pin.
    {"role": "assistant", "content": {"toolUse": {"name": "t", "input": {}}}},
]

_PLAIN_TEXT_STRING_TAIL = [
    {"role": "user", "content": [{"text": "go"}]},
    {"role": "assistant", "content": "done"},
]


# ── close_dangling_tool_use: raises on an unreadable-but-present tail ──────


@pytest.mark.parametrize(
    "messages",
    [
        _MALFORMED_TAIL_TOOLUSE_NOT_DICT,
        _MALFORMED_TAIL_MISSING_TOOLUSEID,
        _MALFORMED_TAIL_NON_LIST_CONTENT,
    ],
    ids=["toolUse-not-dict", "missing-toolUseId", "content-bare-dict"],
)
def test_close_dangling_tool_use_raises_on_unreadable_tail(messages: list[Any]) -> None:
    with pytest.raises(DanglingToolUseUnreadable):
        close_dangling_tool_use(list(messages), default_content=[{"text": "x"}])


def test_close_dangling_tool_use_still_returns_false_for_a_genuinely_clean_tail() -> None:
    """A tail with no toolUse block at all — a plain text assistant reply —
    is a real "nothing to repair" and must NOT raise."""
    healthy = [
        {"role": "user", "content": [{"text": "go"}]},
        {"role": "assistant", "content": [{"text": "done"}]},
    ]
    assert close_dangling_tool_use(list(healthy), default_content=[{"text": "x"}]) is False


def test_close_dangling_tool_use_returns_false_for_a_plain_string_tail() -> None:
    """RT-006: the same "plain text assistant reply" principle as the test
    above, for the ``str`` spelling of it. A string cannot contain a toolUse
    block, so it is clean — not unreadable."""
    assert (
        close_dangling_tool_use(list(_PLAIN_TEXT_STRING_TAIL), default_content=[{"text": "x"}])
        is False
    )


def test_repair_safe_reports_persistable_for_a_plain_string_tail() -> None:
    """RT-006: and the gate above it must therefore report SAFE to persist."""
    record = _record(list(_PLAIN_TEXT_STRING_TAIL))
    assert repair_dangling_tool_use_safe(record, default_content=[{"text": "x"}]) is True


def test_close_dangling_tool_use_raises_for_a_non_dict_tail() -> None:
    """RT-005 (supersedes RT-B-008): a completely non-dict tail entry — we
    cannot even tell it's an assistant turn, let alone a clean one — is no
    longer a quiet False no-op. RT-B-008's original "degrade to False"
    behavior let a non-dict tail from a durable store's own loose
    deserialisation reach ``repair_dangling_tool_use_safe`` reporting
    "confirmed clean", the exact fail-open this whole gate exists to close —
    see tests/test_rt005_non_dict_tail_unreadable_gate.py for the full
    write-side/read-side reconciliation."""
    with pytest.raises(DanglingToolUseUnreadable):
        close_dangling_tool_use(["not a dict"], default_content=[{"text": "x"}])


# ── repair_dangling_tool_use_safe: reports unsafe, does not mutate ─────────


@pytest.mark.parametrize(
    "messages",
    [
        _MALFORMED_TAIL_TOOLUSE_NOT_DICT,
        _MALFORMED_TAIL_MISSING_TOOLUSEID,
        _MALFORMED_TAIL_NON_LIST_CONTENT,
    ],
    ids=["toolUse-not-dict", "missing-toolUseId", "content-bare-dict"],
)
def test_repair_dangling_tool_use_safe_reports_false_for_unreadable_tail(
    messages: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    record = _record(list(messages))

    with caplog.at_level(logging.ERROR, logger="agent_sdk.agent.runner"):
        ok = repair_dangling_tool_use_safe(record, default_content=[{"text": "cancelled"}])

    assert ok is False
    assert record.messages == messages, "an unreadable tail must be left untouched, not repaired"
    assert any("DanglingToolUseUnreadable" in r.message for r in caplog.records), (
        f"expected the unreadable-tail error type in the log line; got "
        f"{[r.message for r in caplog.records]!r}"
    )


# ── end-to-end: set_task_status skips BOTH durable flushes ─────────────────


class _SpyStore(InMemoryTaskStore):
    def __init__(self) -> None:
        super().__init__()
        self.persist_messages_calls = 0
        self.persist_status_calls = 0

    def persist_messages(self, record: TaskRecord) -> None:
        self.persist_messages_calls += 1

    def persist_status(self, record: TaskRecord) -> None:
        self.persist_status_calls += 1


def test_unreadable_tail_gates_both_persist_hooks_via_set_task_status() -> None:
    """The full write-side path a real terminal transition takes: repair,
    then set_task_status(..., repaired=<that result>, store=store). Neither
    persist_messages nor persist_status may fire when the repair reports
    unsafe — this is the exact fail-open the repaired gate exists to close."""
    record = _record(list(_MALFORMED_TAIL_TOOLUSE_NOT_DICT))
    store = _SpyStore()

    repaired = repair_dangling_tool_use_safe(record, default_content=[{"text": "failed"}])
    assert repaired is False

    set_task_status(record, TaskState.FAILED, store=store, repaired=repaired)

    assert store.persist_messages_calls == 0, "persist_messages must not fire on an unrepaired tail"
    assert store.persist_status_calls == 0, "persist_status must not fire on an unrepaired tail"
    # the in-memory status transition still commits — only the durable
    # writes are skipped (runner.py::set_task_status's own RT-001 rule).
    assert record.task.status.state == TaskState.FAILED


# ── bridge_context_messages (read side): degrades, never raises ───────────


def test_bridge_context_messages_drops_an_unreadable_tail_instead_of_raising() -> None:
    """The read side re-asserts this invariant on data ``TaskStore.context_messages()``
    hands back — it must never crash _create_task_record over a corrupted
    stored transcript. Unlike the write side, there is no "skip the flush"
    option here, so the unreadable tail is dropped rather than replayed."""
    prior = list(_MALFORMED_TAIL_TOOLUSE_NOT_DICT)

    bridged = bridge_context_messages(prior)

    assert bridged, "the leading healthy user turn must survive"
    assert not any(
        isinstance(m, dict) and m.get("role") == "assistant" and m.get("content") == [{"toolUse": "not-a-dict"}]
        for m in bridged
    ), "the unreadable tail must not be replayed verbatim into a fresh record"
    # never ends on 'user' either, per bridge_context_messages's own contract
    assert bridged[-1]["role"] == "assistant"
