"""GH-147: assistant-turn fold on the no-tool-call completion branch.

Root cause: run_loop returned on the no-tool-call branch (loop.py) before the
assistant-turn fold block ran — that fold only executed on the tool-call
path. A completed task's record.messages therefore never contained the
model's own final plain-text reply, so A2A contextId continuation replay
never showed the model what it said last turn.

Secondary defect, same root cause: a tool-using task's stored transcript
always ended on the user toolResult message, and continuation appended
another user message — two consecutive user-role entries, malformed for
Converse-shaped backends.

RT-001 (AC3 follow-up): the fold above was branch-local — it only ran on the
happy no-tool-call path, and only when there was non-whitespace text to
fold. Three more exits left record.messages ending on 'user' at a terminal
(replayable) task: a whitespace/empty-only final turn on an otherwise
COMPLETED task, DoneEvent(ok=False) from max-turns/deadline/token-budget
exhaustion, and an upstream AgentError from model.converse. FAILED is a
terminal state exactly like COMPLETED, so context_messages() picks those
records up too. run_loop now bridges every such exit with a fixed assistant
placeholder (see bridge_trailing_user in loop.py) so the transcript never
ends on 'user' regardless of why the loop stopped.
"""

from __future__ import annotations

import uuid
from typing import Any

from agent_sdk.agent.events import DoneEvent
from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.model_client import ModelResponse
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import wait_for_state

EMPTY_REGISTRY = ToolRegistry([ToolSet()], {})


def user_msg(text: str, *, context_id: str | None = None, task_id: str | None = None) -> dict:
    msg: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if context_id:
        msg["contextId"] = context_id
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


def roles_have_no_adjacent_duplicate(roles: list[str]) -> bool:
    return all(a != b for a, b in zip(roles, roles[1:]))


async def _run(
    model: FakeModelClient,
    messages: list[dict[str, Any]],
    *,
    policies: LoopPolicies | None = None,
    clock: Any = None,
) -> list[Any]:
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    events = []
    async for ev in run_loop(
        model=model,
        registry=EMPTY_REGISTRY,
        adapters={},
        system="test",
        messages=messages,
        policies=policies,
        **kwargs,
    ):
        events.append(ev)
    return events


# ── unit: run_loop folds the assistant turn before the early return ───────


async def test_no_tool_call_folds_assistant_reply_into_messages():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]
    model = FakeModelClient([reply("final answer")])
    events = await _run(model, messages)

    assert any(isinstance(e, DoneEvent) and e.ok for e in events)
    assert len(messages) == 2
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == [{"text": "final answer"}]


async def test_no_tool_call_fold_has_no_tool_use_blocks():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]
    model = FakeModelClient([reply("just text, no tools")])
    await _run(model, messages)

    assert not any("toolUse" in block for block in messages[-1]["content"])


async def test_no_tool_call_fold_preserves_multiple_text_segments():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]
    model = FakeModelClient(
        [ModelResponse(text_segments=["part one", "part two"], stop_reason="end_turn")]
    )
    await _run(model, messages)

    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == [{"text": "part one"}, {"text": "part two"}]


async def test_no_tool_call_all_whitespace_segments_bridges_placeholder():
    """RT-001 (a): there is no text worth folding, but messages must still
    not end on 'user' — a fixed assistant placeholder bridges the boundary
    instead of skipping it outright."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]
    model = FakeModelClient([ModelResponse(text_segments=["   ", ""], stop_reason="end_turn")])
    await _run(model, messages)

    assert len(messages) == 2
    assert messages[-1]["role"] == "assistant"
    assert roles_have_no_adjacent_duplicate([m["role"] for m in messages])


async def test_no_tool_call_no_segments_bridges_placeholder():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]
    model = FakeModelClient([ModelResponse(text_segments=[], stop_reason="end_turn")])
    await _run(model, messages)

    assert len(messages) == 2
    assert messages[-1]["role"] == "assistant"
    assert roles_have_no_adjacent_duplicate([m["role"] for m in messages])


# ── unit: RT-001 — every non-happy-path exit also bridges 'user' ──────────


async def test_max_turns_exceeded_after_tool_round_bridges_trailing_user():
    """RT-001 (b): max-turns exhaustion right after a tool round leaves
    messages ending on the 'user' toolResult fold — the max-turns
    DoneEvent(ok=False) must bridge it before returning."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1})])
    events = await _run(model, messages, policies=LoopPolicies(max_turns=1))

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and done[-1].ok is False
    assert "max turns" in (done[-1].error or "")
    assert messages[-1]["role"] == "assistant"
    assert done[-1].summary  # GH-155: notice (script exhausted) folded/bridged, not skipped
    assert roles_have_no_adjacent_duplicate([m["role"] for m in messages])


async def test_converse_agent_error_after_tool_round_bridges_trailing_user():
    """RT-001 (c): an upstream AgentError from model.converse the turn AFTER
    a tool round leaves messages ending on the 'user' toolResult fold from
    the completed round — must be bridged before the ok=False DoneEvent."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    # Only one scripted response: the tool call. The turn-2 converse() call
    # finds the script exhausted and FakeModelClient raises AgentError,
    # standing in for a real upstream failure mid-conversation.
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1})])
    events = await _run(model, messages)

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and done[-1].ok is False
    assert messages[-1]["role"] == "assistant"
    assert roles_have_no_adjacent_duplicate([m["role"] for m in messages])


async def test_deadline_exceeded_after_tool_round_bridges_trailing_user():
    """RT-001 (b): deadline exhaustion checked at the top of the next turn,
    right after a tool round, must also bridge the trailing 'user' fold."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1}), reply("unreachable")])
    clock_calls = {"n": 0}

    def clock() -> float:
        # Call #1 (Deadline.__init__) and #2 (turn-1 exceeded() check) return
        # the same baseline so turn 1 runs normally; call #3 (turn-2
        # exceeded() check, right after the tool round) jumps far past the
        # 1-second deadline.
        clock_calls["n"] += 1
        return 0.0 if clock_calls["n"] <= 2 else 10_000.0

    events = await _run(
        model, messages, policies=LoopPolicies(deadline_seconds=1.0), clock=clock
    )

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and done[-1].ok is False
    assert "deadline" in (done[-1].error or "")
    assert messages[-1]["role"] == "assistant"
    assert roles_have_no_adjacent_duplicate([m["role"] for m in messages])


async def test_token_budget_exceeded_after_tool_round_bridges_trailing_user():
    """RT-001 (b): token-budget exhaustion checked at the top of the next
    turn, right after a tool round, must also bridge the trailing 'user' fold."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient(
        [tool_call("unknown_tool", {"x": 1}, output_tokens=1_000_000)]
    )
    events = await _run(model, messages, policies=LoopPolicies(token_budget=10))

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and done[-1].ok is False
    assert "token budget" in (done[-1].error or "")
    assert messages[-1]["role"] == "assistant"
    assert roles_have_no_adjacent_duplicate([m["role"] for m in messages])


# ── route level: stored record + contextId continuation replay ────────────


async def test_no_tool_call_completion_stores_assistant_reply(client, fake_model):
    fake_model.script(reply("the final word"))
    r = await client.post("/v1/message:send", json=user_msg("hello"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    record = client.app.state.task_store.get(task_id)
    assert record is not None
    assert record.messages[-1]["role"] == "assistant"
    assert "the final word" in str(record.messages[-1]["content"])


async def test_no_tool_call_context_continuation_shows_prior_reply(client, fake_model):
    fake_model.script(reply("remember this fact"))
    r = await client.post("/v1/message:send", json=user_msg("turn one"))
    assert r.status_code == 200, r.text
    completed = await wait_for_state(client, r.json()["id"])
    ctx = completed["contextId"]

    fake_model.calls.clear()
    fake_model.script(reply("second reply"))
    r2 = await client.post("/v1/message:send", json=user_msg("turn two", context_id=ctx))
    assert r2.status_code == 200, r2.text
    await wait_for_state(client, r2.json()["id"])

    assert fake_model.calls, "converse must have been called for turn 2"
    turn2_messages = fake_model.calls[0]["messages"]
    assert any(
        m["role"] == "assistant" and "remember this fact" in str(m["content"])
        for m in turn2_messages
    ), f"assistant's prior reply missing from replayed history: {turn2_messages!r}"


async def test_tool_using_transcript_no_consecutive_same_role(client, fake_model):
    fake_model.script(tool_call("echo", {"text": "hi"}), reply("tool done"))
    r = await client.post("/v1/message:send", json=user_msg("use a tool"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    completed = await wait_for_state(client, task_id)

    record = client.app.state.task_store.get(task_id)
    assert record is not None
    roles = [m["role"] for m in record.messages]
    assert roles_have_no_adjacent_duplicate(roles), f"adjacent same-role messages: {roles}"
    assert roles[-1] == "assistant"


async def test_tool_using_transcript_no_consecutive_same_role_across_continuation(
    client, fake_model
):
    fake_model.script(tool_call("echo", {"text": "hi"}), reply("tool done"))
    r = await client.post("/v1/message:send", json=user_msg("use a tool"))
    assert r.status_code == 200, r.text
    completed = await wait_for_state(client, r.json()["id"])
    ctx = completed["contextId"]

    fake_model.script(reply("turn two reply"))
    r2 = await client.post("/v1/message:send", json=user_msg("turn two", context_id=ctx))
    assert r2.status_code == 200, r2.text
    task2_id = r2.json()["id"]
    await wait_for_state(client, task2_id)

    record2 = client.app.state.task_store.get(task2_id)
    assert record2 is not None
    roles = [m["role"] for m in record2.messages]
    assert roles_have_no_adjacent_duplicate(
        roles
    ), f"adjacent same-role messages across continuation: {roles}"


# ── route level: RT-001 — the three reachable-but-unbridged shapes ────────


async def test_whitespace_final_turn_context_continuation_no_adjacent_same_role(
    client, fake_model
):
    """RT-001 (a) end-to-end: a COMPLETED task whose final model turn is
    whitespace-only must not leave record.messages ending on 'user' — the
    next contextId turn would otherwise append a second consecutive 'user'
    message, which Bedrock's Converse API rejects outright."""
    fake_model.script(ModelResponse(text_segments=["   "], stop_reason="end_turn"))
    r = await client.post("/v1/message:send", json=user_msg("turn one"))
    assert r.status_code == 200, r.text
    completed = await wait_for_state(client, r.json()["id"])
    assert completed["status"]["state"] == "completed"
    ctx = completed["contextId"]

    record = client.app.state.task_store.get(r.json()["id"])
    assert record is not None
    roles = [m["role"] for m in record.messages]
    assert roles_have_no_adjacent_duplicate(roles), f"adjacent same-role messages: {roles}"
    assert roles[-1] == "assistant"

    fake_model.calls.clear()
    fake_model.script(reply("second reply"))
    r2 = await client.post("/v1/message:send", json=user_msg("turn two", context_id=ctx))
    assert r2.status_code == 200, r2.text
    await wait_for_state(client, r2.json()["id"])

    assert fake_model.calls, "converse must have been called for turn 2"
    roles2 = [m["role"] for m in fake_model.calls[0]["messages"]]
    assert roles_have_no_adjacent_duplicate(
        roles2
    ), f"adjacent same-role messages sent upstream: {roles2}"


async def test_max_turns_failed_task_context_continuation_no_adjacent_same_role(
    client, fake_model
):
    """RT-001 (b) end-to-end: a FAILED task from max-turns exhaustion right
    after a tool round must not leave record.messages ending on the 'user'
    toolResult — FAILED is a terminal state, so context_messages() replays
    it on the next contextId turn exactly like a COMPLETED task."""
    client.app.state.loop_policies = LoopPolicies(max_turns=1)
    fake_model.script(tool_call("echo", {"text": "hi"}))
    r = await client.post("/v1/message:send", json=user_msg("use a tool"))
    assert r.status_code == 200, r.text
    failed = await wait_for_state(client, r.json()["id"])
    assert failed["status"]["state"] == "failed"
    ctx = failed["contextId"]

    record = client.app.state.task_store.get(r.json()["id"])
    assert record is not None
    roles = [m["role"] for m in record.messages]
    assert roles_have_no_adjacent_duplicate(roles), f"adjacent same-role messages: {roles}"
    assert roles[-1] == "assistant"

    # Restore default policies so turn two is not itself max-turns-exhausted.
    client.app.state.loop_policies = LoopPolicies()
    fake_model.calls.clear()
    fake_model.script(reply("turn two reply"))
    r2 = await client.post("/v1/message:send", json=user_msg("turn two", context_id=ctx))
    assert r2.status_code == 200, r2.text
    await wait_for_state(client, r2.json()["id"])

    assert fake_model.calls, "converse must have been called for turn 2"
    roles2 = [m["role"] for m in fake_model.calls[0]["messages"]]
    assert roles_have_no_adjacent_duplicate(
        roles2
    ), f"adjacent same-role messages sent upstream: {roles2}"


async def test_converse_agent_error_failed_task_context_continuation_no_adjacent_same_role(
    client, fake_model
):
    """RT-001 (c) end-to-end: an upstream AgentError from model.converse on
    the turn after a tool round must not leave record.messages ending on
    the 'user' toolResult — the FAILED task's transcript is still replayed
    on the next contextId turn."""
    fake_model.script(tool_call("echo", {"text": "hi"}))
    # No second scripted response: FakeModelClient raises AgentError on the
    # turn-2 converse() call, standing in for a real upstream failure.
    r = await client.post("/v1/message:send", json=user_msg("use a tool"))
    assert r.status_code == 200, r.text
    failed = await wait_for_state(client, r.json()["id"])
    assert failed["status"]["state"] == "failed"
    ctx = failed["contextId"]

    record = client.app.state.task_store.get(r.json()["id"])
    assert record is not None
    roles = [m["role"] for m in record.messages]
    assert roles_have_no_adjacent_duplicate(roles), f"adjacent same-role messages: {roles}"
    assert roles[-1] == "assistant"

    fake_model.calls.clear()
    fake_model.script(reply("turn two reply"))
    r2 = await client.post("/v1/message:send", json=user_msg("turn two", context_id=ctx))
    assert r2.status_code == 200, r2.text
    await wait_for_state(client, r2.json()["id"])

    assert fake_model.calls, "converse must have been called for turn 2"
    roles2 = [m["role"] for m in fake_model.calls[0]["messages"]]
    assert roles_have_no_adjacent_duplicate(
        roles2
    ), f"adjacent same-role messages sent upstream: {roles2}"


# ── regression: AG-UI client-supplied-history path is unaffected ──────────



# ── unit: RT-001 — mirror-image trailing-assistant guard (both fold sites) ─


async def test_no_tool_call_fold_merges_into_preexisting_assistant_tail():
    """RT-001: bridge_trailing_user only guards a trailing 'user' — the
    mirror-image break is a caller-supplied ``messages`` that already ends
    on 'assistant' before run_loop's own no-tool-call fold runs (e.g. AG-UI's
    _fold_history only strips a LEADING assistant prefix, never a trailing
    one). The new reply must merge into the existing assistant tail, not
    become a second, adjacent assistant entry."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "prior reply"}]},
    ]
    model = FakeModelClient([reply("continued answer")])
    await _run(model, messages)

    assert roles_have_no_adjacent_duplicate([m["role"] for m in messages])
    assert len(messages) == 2
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == [
        {"text": "prior reply"},
        {"text": "continued answer"},
    ]


async def test_tool_use_fold_merges_into_preexisting_assistant_tail():
    """RT-001: same guard on the toolUse fold (loop.py's other
    ``messages.append({"role": "assistant", ...})`` site). An
    assistant-tailed transcript plus a tool-calling turn must not leave two
    adjacent assistant messages in ``messages`` — and turn 2's converse()
    call, built from that same ``messages`` list, must not carry the
    duplicate either."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "go"}]},
        {"role": "assistant", "content": [{"text": "prior reply"}]},
    ]
    model = FakeModelClient([tool_call("unknown_tool", {"x": 1}), reply("done")])
    await _run(model, messages)

    roles = [m["role"] for m in messages]
    assert roles_have_no_adjacent_duplicate(roles), f"adjacent same-role messages: {roles}"

    assert len(model.calls) == 2, "turn 2's converse() call must have happened"
    turn2_roles = [m["role"] for m in model.calls[1]["messages"]]
    assert roles_have_no_adjacent_duplicate(turn2_roles), (
        f"adjacent same-role messages sent upstream on turn 2: {turn2_roles}"
    )


async def test_ag_ui_client_supplied_history_still_drives_converse(client, fake_model):
    """AG-UI resends full history with every run (no server-side continuation
    via context_messages()) — the loop.py fold must not change that path's
    input construction."""
    fake_model.script(reply("hi there"))
    body = {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": "hello"}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    r = await client.post("/ag-ui/run", json=body)
    assert r.status_code == 200, r.text
    assert fake_model.calls
    first_call_messages = fake_model.calls[0]["messages"]
    assert len(first_call_messages) == 1
    assert first_call_messages[0]["role"] == "user"
