"""RT-003 (routes/a2a.py review follow-up): ``repair_dangling_tool_use_safe``
must not conflate a failed in-memory repair (no repair happened at all —
``record.messages`` still ends on the dangling ``toolUse`` tail) with a
failed durable flush (the repair landed in memory; only the store's copy is
stale). The wrapper's own docstring, and ``tasks_cancel``'s RT-B-106 comment
and warning text (``routes/a2a.py``), previously asserted "only the trailing
store.persist_messages flush can fail" / "the in-memory repair ... has
already landed either way" — false: ``repair_dangling_tool_use`` could itself
raise (a malformed dangling ``toolUse`` block) before it appended anything,
which is a materially worse condition for incident triage than a stale
durable copy.

RT-001 (agent/runner.py review, follow-up) / RT-004 (correction): an
intermediate "fix" once made the id-extraction comprehension guard the
nested read by treating a malformed block as "nothing to repair" rather than
raising — but that silently turned this exact fail-closed gate into a
fail-open one: ``close_dangling_tool_use`` returned ``False`` (its "no
toolUse tail, safe" signal) for a tail that was in fact still a dangling,
unrepaired ``toolUse`` turn, so ``repair_dangling_tool_use_safe`` reported
``True`` over an unrepaired transcript. RT-004 restores the raise —
``close_dangling_tool_use`` now raises ``DanglingToolUseUnreadable`` for
this exact shape (see ``test_rt004_malformed_dangling_tool_use_reported_unrepaired``
below), which this wrapper catches like any other in-memory repair failure.
The in-memory-vs-flush distinction this module pins also still exercises a
FORCED generic failure of the append/bridge stage (monkeypatched) below, to
prove the wrapper degrades correctly for whatever OTHER future cause raises
there too, not only this one now-typed case.

RT-001/RT-007 (debug round 4): the distinction is now made STRUCTURALLY
instead of by two log strings behind one boolean. ``repair_dangling_tool_use_safe``
no longer takes a ``store`` and performs no durable flush at all, so the only
failure it can report is the in-memory one — which is exactly what its return
value means to ``set_task_status``'s ``repaired`` gate. Folding a durable-write
failure into that same boolean made a transient ``persist_messages`` blip skip
``set_task_status``'s own (correct) flush-and-gate path, permanently stranding
the durable record non-terminal; and it issued two durable writes of the same
unchanged record per terminal transition. Durable-flush behaviour is now owned
solely by ``set_task_status`` and covered by
``tests/test_rt001_set_status_gated_on_unrepaired_transcript.py``.

Unit-level (agent_sdk.agent.runner + agent_sdk.tasks.memory only — no
FastAPI app boot), mirroring
tests/test_rtb007_rtb008_repair_dangling_tool_use_hardening.py's direct-
call style.
"""

from __future__ import annotations

import inspect
import logging

from agent_sdk.agent.runner import repair_dangling_tool_use_safe
from agent_sdk.models.a2a import Task, TaskState, TaskStatus
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskRecord


def _record(messages: list) -> TaskRecord:
    task = Task(id="t1", contextId="c1", status=TaskStatus(state=TaskState.WORKING))
    record = TaskRecord(task=task, identity=("api_key", "test"), created_at=0.0, updated_at=0.0)
    record.messages = messages
    return record


def test_rt004_malformed_dangling_tool_use_reported_unrepaired() -> None:
    """RT-004: a malformed dangling toolUse block (its "toolUse" value is not
    a dict) cannot be repaired — there is no toolUseId to correlate a
    synthetic toolResult against — so it must be reported as NOT safe to
    persist, not conflated with "nothing to repair". The malformed block
    itself is left exactly as it was; no synthetic toolResult is fabricated
    for it."""
    messages = [
        {"role": "user", "content": [{"text": "go"}]},
        {"role": "assistant", "content": [{"toolUse": "not-a-dict"}]},
    ]
    record = _record(list(messages))

    ok = repair_dangling_tool_use_safe(record, default_content=[{"text": "cancelled"}])

    assert ok is False
    assert record.messages == messages


class _ExplodingPendingResults(list):
    """Raises the moment it's iterated — simulates a durable store handing
    back a ``pending_tool_results`` collection the id-extraction/pending-fold
    logic cannot safely walk, forcing a failure at the very first step of
    ``repair_dangling_tool_use``'s in-memory work, before it appends
    anything."""

    def __iter__(self):  # type: ignore[override]
        raise RuntimeError("simulated in-memory repair failure")


def test_in_memory_repair_failure_is_reported_and_logged(caplog) -> None:
    """A generic failure of the in-memory repair stage (forced here, since
    the one concrete cause RT-001 could reproduce — a malformed toolUse
    block — is now guarded against at the source) must leave record.messages
    untouched, return False, and log that the transcript was left
    unrepaired."""
    messages = [
        {"role": "user", "content": [{"text": "go"}]},
        {
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": "call-1", "name": "t", "input": {}}}],
        },
    ]
    record = _record(list(messages))
    record.pending_tool_results = _ExplodingPendingResults()

    with caplog.at_level(logging.ERROR, logger="agent_sdk.agent.runner"):
        ok = repair_dangling_tool_use_safe(record, default_content=[{"text": "cancelled"}])

    assert ok is False
    assert record.messages == messages, (
        "the in-memory repair must not silently be treated as landed when it "
        "never ran at all"
    )
    assert any("in-memory" in r.message for r in caplog.records), (
        "a repair-stage failure must say the transcript was left unrepaired — "
        f"got {[r.message for r in caplog.records]!r}"
    )


def test_wrapper_takes_no_store_and_never_flushes() -> None:
    """RT-001/RT-007 (debug round 4): the wrapper's return value must mean
    exactly one thing — "record.messages is safe to persist". It therefore
    accepts no ``store`` and performs no durable write, so a store failure
    can never be reported through that same boolean and cannot suppress
    ``set_task_status``'s own flush-and-gate path."""
    params = inspect.signature(repair_dangling_tool_use_safe).parameters
    assert "store" not in params, (
        "repair_dangling_tool_use_safe must not take a store — set_task_status "
        "is the single persist_messages flush point for every terminal "
        "transition (RT-007), and a flush failure must never masquerade as an "
        "unrepaired transcript (RT-001)"
    )


def test_successful_repair_does_not_touch_the_store(caplog) -> None:
    """Behavioural companion to the signature check: a store whose every
    write hook raises must not affect the wrapper at all — it never calls
    one."""
    calls: list[str] = []

    class _RaisesOnEveryWrite(InMemoryTaskStore):
        def persist_messages(self, record: TaskRecord) -> None:
            calls.append("messages")
            raise RuntimeError("the wrapper must not call this")

        def persist_status(self, record: TaskRecord) -> None:
            calls.append("status")
            raise RuntimeError("the wrapper must not call this")

    _RaisesOnEveryWrite()  # instantiable; simply never reached by the wrapper
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [{"toolUse": {"toolUseId": "call-1", "name": "t", "input": {}}}],
            },
        ]
    )

    with caplog.at_level(logging.ERROR, logger="agent_sdk.agent.runner"):
        ok = repair_dangling_tool_use_safe(record, default_content=[{"text": "cancelled"}])

    assert ok is True
    assert calls == [], "the repair wrapper must issue no durable write of its own"
    # the in-memory repair still landed
    result_message = record.messages[-2]
    assert result_message["content"][0]["toolResult"]["toolUseId"] == "call-1"
    assert [r.message for r in caplog.records] == []
