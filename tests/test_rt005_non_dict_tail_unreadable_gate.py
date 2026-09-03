"""RT-005 (agent/loop.py redteam): a non-dict tail entry in ``messages`` must
gate the durable write the same way an unreadable-but-present ``toolUse``
tail already does (RT-004), not silently report "confirmed clean".

Before this fix, ``close_dangling_tool_use``'s outer guard —
``if not (messages and isinstance(messages[-1], dict) and ...)`` — collapsed
two different situations into the same ``False`` ("nothing to repair")
return: an EMPTY ``messages`` list (genuinely nothing to repair) and a
NON-EMPTY list whose last element is not a dict at all (unknown — we cannot
even tell whether it is an assistant ``toolUse`` turn). ``DanglingToolUseUnreadable``'s
own docstring defines ``False`` as meaning the tail is "CONFIRMED clean", but
a non-dict tail is never confirmed — it just can't be read.

That let ``repair_dangling_tool_use_safe`` report ``True`` (safe to persist)
for a transcript whose last element is e.g. a bare string, so
``set_task_status`` durably flushed ``record.messages`` — tail untouched —
plus the terminal status on top of it. The READ side
(``bridge_context_messages``) already drops a non-dict message outright
(RT-006, debug round 6) rather than trusting it, so the write side trusting
it instead was the one side of the invariant left unenforced.

Fix: a non-empty ``messages`` whose last element is not a dict now raises
``DanglingToolUseUnreadable`` too — the exact signal RT-004 already wired
``repair_dangling_tool_use_safe`` to catch and report ``False`` for, and
``set_task_status`` to gate both durable flushes on. An empty ``messages``
list is unaffected: there is no tail at all, so it remains a genuine,
confirmed-clean ``False``.
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


class _SpyStore(InMemoryTaskStore):
    def __init__(self) -> None:
        super().__init__()
        self.persist_messages_calls = 0
        self.persist_status_calls = 0

    def persist_messages(self, record: TaskRecord) -> None:
        self.persist_messages_calls += 1

    def persist_status(self, record: TaskRecord) -> None:
        self.persist_status_calls += 1


# ── close_dangling_tool_use: a non-dict tail now raises ────────────────────


def test_close_dangling_tool_use_raises_on_a_bare_string_tail() -> None:
    with pytest.raises(DanglingToolUseUnreadable):
        close_dangling_tool_use(["not a dict"], default_content=[{"text": "x"}])


def test_close_dangling_tool_use_raises_on_a_non_dict_object_tail() -> None:
    class _NotAMessage:
        pass

    messages: list[Any] = [{"role": "user", "content": [{"text": "go"}]}, _NotAMessage()]

    with pytest.raises(DanglingToolUseUnreadable):
        close_dangling_tool_use(messages, default_content=[{"text": "x"}])


def test_close_dangling_tool_use_still_returns_false_for_empty_messages() -> None:
    """No tail at all is genuinely, confirmedly nothing to repair — unlike a
    present-but-unreadable tail, this must not raise."""
    assert close_dangling_tool_use([], default_content=[{"text": "x"}]) is False


# ── repair_dangling_tool_use_safe: reports unsafe, does not mutate ─────────


def test_repair_dangling_tool_use_safe_reports_false_for_bare_string_tail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = _record(["not a dict"])

    with caplog.at_level(logging.ERROR, logger="agent_sdk.agent.runner"):
        ok = repair_dangling_tool_use_safe(record, default_content=[{"text": "cancelled"}])

    assert ok is False
    assert record.messages == ["not a dict"], "an unreadable tail must be left untouched"
    assert any("DanglingToolUseUnreadable" in r.message for r in caplog.records)


# ── end-to-end: set_task_status skips BOTH durable flushes ─────────────────


def test_bare_string_tail_gates_both_persist_hooks_via_set_task_status() -> None:
    record = _record(["not a dict"])
    store = _SpyStore()

    repaired = repair_dangling_tool_use_safe(record, default_content=[{"text": "failed"}])
    assert repaired is False

    set_task_status(record, TaskState.FAILED, store=store, repaired=repaired)

    assert store.persist_messages_calls == 0, "persist_messages must not fire on an unrepaired tail"
    assert store.persist_status_calls == 0, "persist_status must not fire on an unrepaired tail"
    # the in-memory status transition still commits — only the durable
    # writes are skipped (runner.py::set_task_status's own RT-001 rule).
    assert record.task.status.state == TaskState.FAILED


# ── bridge_context_messages (read side): unaffected, still drops it ────────


def test_bridge_context_messages_still_drops_a_bare_string_tail() -> None:
    """The read side already filters every non-dict message to a plain list
    BEFORE it ever reaches close_dangling_tool_use (RT-006, debug round 6),
    so this fix must not change its behaviour: no raise reaches this caller,
    and the non-dict tail is simply absent from the result.

    Dropping "not a dict" leaves the transcript ending on the ``user`` turn,
    which ``bridge_context_messages``'s own RT-003 re-assertion (this
    function calls ``bridge_trailing_user`` at the end) then closes with the
    fixed "(no response)" bridge — the same "never end on user" invariant
    every ``run_loop`` exit guards — so the ORIGINAL user content survives
    one turn earlier in the result, not as the tail."""
    prior: list[Any] = [{"role": "user", "content": [{"text": "go"}]}, "not a dict"]

    bridged = bridge_context_messages(prior)

    assert all(isinstance(m, dict) for m in bridged)
    assert bridged == [] or {"role": "user", "content": [{"text": "go"}]} in bridged
    assert not any(m == {"content": "not a dict"} or m == "not a dict" for m in bridged)
