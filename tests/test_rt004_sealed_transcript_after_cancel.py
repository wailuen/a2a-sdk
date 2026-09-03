"""RT-004 (debug round 4): a terminal-state guard placed in the event CONSUMER
does not stop the generator below it from mutating shared state.

``tasks_cancel`` repairs ``record.messages``, bridges it, and commits CANCELED
with no await in between — correct against a cooperative worker. But
``run_loop`` holds a live reference to that very list (``run_task_worker``
passes ``messages=record.messages``) and commits each turn with
``messages.append({"role": "user", "content": list(result_blocks)})``. If the
worker's ``asyncio.CancelledError`` never lands — a tool catching
``BaseException``, or ``asyncio.wait_for``'s cancel-vs-timeout race on 3.11+
surfacing a ``TimeoutError`` — ``run_loop`` finishes the turn normally and
appends its own toolResult message AFTER ``tasks_cancel`` already appended the
synthetic toolResult and the "(no response)" assistant bridge. The result is a
duplicate ``toolUseId`` plus an orphan ``user``/``toolResult`` with no
immediately-preceding assistant ``toolUse``, on a CANCELED (terminal, hence
replayable) task that ``context_messages()`` selects for the next ``contextId``
continuation — GH-150's failure mode, reintroduced.

``run_task_worker``'s RT-B-102 top-of-loop terminal guard does not close this:
it stops status mutations, artifact appends and publishes, but it runs in the
consumer ABOVE ``run_loop``, and ``run_loop``'s ``messages.append`` executes
inside the generator before the next event is ever yielded. The runner's own
comment names both escape paths as reachable.

Fix: seal the STATE, not the consumer loop — ``run_loop`` takes a ``sealed``
predicate and stops mutating ``messages`` once another owner has committed the
task terminal.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.models.a2a import TERMINAL_STATES, TaskState
from agent_sdk.testing import reply, tool_call
from agent_sdk.testing.fake_model import FakeModelClient


def _assert_no_dangling_tool_use(messages: list[dict[str, Any]]) -> None:
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        ids = [
            b["toolUse"]["toolUseId"]
            for b in msg.get("content", [])
            if isinstance(b, dict) and isinstance(b.get("toolUse"), dict)
        ]
        if not ids:
            continue
        assert i + 1 < len(messages), f"assistant toolUse {ids} at {i} has no following message"
        nxt = messages[i + 1]
        assert nxt.get("role") == "user", f"toolUse {ids} answered by role={nxt.get('role')!r}"
        answered = [
            b["toolResult"]["toolUseId"]
            for b in nxt.get("content", [])
            if isinstance(b, dict) and isinstance(b.get("toolResult"), dict)
        ]
        assert set(ids) <= set(answered), f"toolUse {ids} unanswered; got {answered}"


def _assert_alternates(messages: list[dict[str, Any]]) -> None:
    roles = [m["role"] for m in messages]
    assert all(a != b for a, b in zip(roles, roles[1:])), (
        f"two consecutive same-role messages — Converse rejects this: {roles}"
    )


def _assert_no_orphan_tool_results(messages: list[dict[str, Any]]) -> None:
    """Every user/toolResult must be immediately preceded by an assistant
    turn carrying the matching toolUse."""
    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        answered = [
            b["toolResult"]["toolUseId"]
            for b in msg.get("content", [])
            if isinstance(b, dict) and isinstance(b.get("toolResult"), dict)
        ]
        if not answered:
            continue
        assert i > 0, f"toolResult {answered} at index 0 has no preceding assistant toolUse"
        prev = messages[i - 1]
        assert prev.get("role") == "assistant", (
            f"orphan toolResult {answered}: preceded by role={prev.get('role')!r}"
        )
        opened = [
            b["toolUse"]["toolUseId"]
            for b in prev.get("content", [])
            if isinstance(b, dict) and isinstance(b.get("toolUse"), dict)
        ]
        assert set(answered) <= set(opened), (
            f"orphan toolResult {answered}: preceding assistant opened {opened}"
        )


def _assert_no_duplicate_tool_use_ids(messages: list[dict[str, Any]]) -> None:
    seen: list[str] = []
    for msg in messages:
        for b in msg.get("content", []):
            if isinstance(b, dict) and isinstance(b.get("toolResult"), dict):
                seen.append(b["toolResult"]["toolUseId"])
    assert len(seen) == len(set(seen)), f"duplicate toolResult toolUseIds: {seen}"


class _FakeTerminalState:
    """Stands in for ``record.task.status.state``, flipped by the simulated
    concurrent ``tasks_cancel``."""

    def __init__(self) -> None:
        self.state: Any = TaskState.WORKING

    def cancel(self) -> None:
        self.state = TaskState.CANCELED


@pytest.mark.asyncio
async def test_swallowed_cancellation_cannot_append_after_a_terminal_commit() -> None:
    """The RT-004 scenario end to end: a tool swallows the CancelledError, and
    a concurrent cancel repairs + commits the transcript while that tool is
    mid-call. run_loop must not then append the turn on top."""
    status = _FakeTerminalState()
    tools = ToolSet()

    @tools.tool(tier=1, name="slow")
    async def slow_tool() -> str:
        """A tool that catches BaseException — one of the two escape paths
        run_task_worker's own comments name as reachable."""
        try:
            await asyncio.sleep(3600)
        except BaseException:  # noqa: BLE001 — deliberately the bug shape
            # meanwhile the "cancel request" lands and commits terminal state,
            # exactly as tasks_cancel does: repair, bridge, commit, no await
            # in between.
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": "call-1",
                                "content": [{"text": "tool call cancelled"}],
                                "status": "error",
                            }
                        }
                    ],
                }
            )
            messages.append({"role": "assistant", "content": [{"text": "(no response)"}]})
            status.cancel()
            return "swallowed"
        return "never"

    registry = ToolRegistry([tools], {})
    model = FakeModelClient()
    model.script(tool_call("slow", {}, tool_call_id="call-1"), reply("after"))
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]

    async def drive() -> None:
        async for _ in run_loop(
            model=model,
            registry=registry,
            adapters={},
            system="s",
            messages=messages,
            sealed=lambda: status.state in TERMINAL_STATES,
        ):
            pass

    task = asyncio.create_task(drive())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    _assert_no_dangling_tool_use(messages)
    _assert_alternates(messages)
    _assert_no_orphan_tool_results(messages)
    _assert_no_duplicate_tool_use_ids(messages)
    assert messages[-1]["role"] == "assistant", (
        "the canceller's bridged transcript must remain the tail — run_loop "
        "must not have appended its own turn on top of it"
    )


@pytest.mark.asyncio
async def test_sealed_stops_the_loop_before_the_next_turn() -> None:
    """The other seal point: a task sealed between turns must not start
    another model turn or fold another assistant message."""
    status = _FakeTerminalState()
    registry = ToolRegistry([ToolSet()], {})
    model = FakeModelClient()
    model.script(reply("turn one"), reply("turn two"))
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]

    status.cancel()  # already terminal before the first turn begins
    events = [
        ev
        async for ev in run_loop(
            model=model,
            registry=registry,
            adapters={},
            system="s",
            messages=messages,
            sealed=lambda: status.state in TERMINAL_STATES,
        )
    ]

    assert messages == [{"role": "user", "content": [{"text": "go"}]}], (
        "a sealed run_loop must not mutate the transcript at all"
    )
    assert events and getattr(events[-1], "ok", None) is False, (
        "run_loop's contract still holds: it always terminates with a DoneEvent"
    )


@pytest.mark.asyncio
async def test_sealed_mid_converse_cannot_append_after_a_terminal_commit() -> None:
    """RT-006 (debug round 4 follow-up regression): a seal landing DURING
    ``await model.converse(...)`` — not before the turn started, and not
    after the turn's tool calls finished — must still stop run_loop before
    it folds a new assistant turn onto the already-repaired transcript.
    Neither of the two existing seal checks (top-of-turn, pre-commit) covers
    this window: the top-of-turn check already passed before this call
    began, and the pre-commit check only runs after a full round of tool
    calls, by which point ``append_assistant_turn`` has already mutated
    ``messages``. Drives run_loop directly (not through run_task_worker) so
    the seal-in-the-model-await window is exercised in isolation from the
    consumer-side terminal guard."""
    status = _FakeTerminalState()

    class _SealingDuringConverseModel:
        """Stands in for the real ModelClient — simulates a concurrent
        tasks_cancel repairing and committing the record while
        ``model.converse`` is in flight, the exact window RT-006 closes."""

        def __init__(self, response: Any) -> None:
            self._response = response

        async def converse(self, **kwargs: Any) -> Any:
            status.cancel()
            return self._response

    registry = ToolRegistry([ToolSet()], {})
    model = _SealingDuringConverseModel(tool_call("whatever", {}, tool_call_id="call-2"))

    # The transcript a concurrent tasks_cancel already repaired + bridged
    # before this turn's model call returns — mirrors the shape
    # repair_dangling_tool_use leaves behind.
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "go"}]},
        {
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": "call-1", "name": "slow", "input": {}}}],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "call-1",
                        "content": [{"text": "tool call cancelled"}],
                        "status": "error",
                    }
                }
            ],
        },
        {"role": "assistant", "content": [{"text": "(no response)"}]},
    ]
    before = [dict(m) for m in messages]

    events = [
        ev
        async for ev in run_loop(
            model=model,
            registry=registry,
            adapters={},
            system="s",
            messages=messages,
            sealed=lambda: status.state in TERMINAL_STATES,
        )
    ]

    assert messages == before, (
        "a seal landing mid-converse must stop run_loop before it folds "
        "another assistant turn onto the already-repaired transcript — got "
        f"{messages!r}"
    )
    _assert_no_dangling_tool_use(messages)
    assert messages[-1]["role"] == "assistant", (
        "the canceller's bridged transcript must remain the tail"
    )
    assert events and getattr(events[-1], "ok", None) is False, (
        "run_loop's contract still holds: it always terminates with a DoneEvent"
    )


@pytest.mark.asyncio
async def test_unsealed_loop_is_completely_unaffected() -> None:
    """Green companion: omitting ``sealed`` (and a never-sealed predicate)
    keeps the previous behaviour exactly."""
    tools = ToolSet()

    @tools.tool(tier=1, name="ok")
    async def ok_tool() -> str:
        return "fine"

    registry = ToolRegistry([tools], {})
    model = FakeModelClient()
    model.script(tool_call("ok", {}, tool_call_id="call-1"), reply("done"))
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]

    async for _ in run_loop(
        model=model, registry=registry, adapters={}, system="s", messages=messages
    ):
        pass

    _assert_no_dangling_tool_use(messages)
    _assert_alternates(messages)
    _assert_no_orphan_tool_results(messages)
    assert any(
        isinstance(b, dict) and isinstance(b.get("toolResult"), dict)
        for m in messages
        for b in m.get("content", [])
    ), "the normal path must still commit the turn's toolResult"
