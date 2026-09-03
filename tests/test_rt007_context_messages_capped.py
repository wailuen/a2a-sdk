"""RT-007: InMemoryTaskStore.context_messages() must bound how much of a
long-lived contextId thread it hands back to a fresh (non-resume)
message/send.

Before this fix, context_messages() returned the full prior task's
``messages`` with no cap, and routes/a2a.py's ``_create_task_record`` folded
all of it into every new task's ``record.messages`` — so the model prompt
grows linearly with total turns for the life of a thread. The sibling
carriers already bound themselves: ``context_reusable_messages()`` caps the
number of terminal TASKS it scans (``MAX_REUSABLE_TASKS``, RT-010), and
AG-UI's ``routes/ag_ui.py::_fold_history`` caps the number of MESSAGES it
replays (``MAX_HISTORY_MESSAGES``). ``context_messages()`` was the one
primary-carrier holdout.

The cap must truncate from the front on a turn boundary — a genuine
user-authored turn start (``role == "user"`` with no ``toolResult`` block in
its content) — never landing mid-tool-round on a ``toolResult`` (or a
toolUse-carrying assistant turn) whose matching half was cut off, which
Bedrock's Converse API rejects outright.
"""

from __future__ import annotations

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState, TaskStatus
from agent_sdk.tasks.memory import MAX_CONTEXT_MESSAGES, InMemoryTaskStore

_OWNER = Identity(kind="api_key", subject="owner", admin=False)


def _user_text(text: str) -> dict:
    return {"role": "user", "content": [{"text": text}]}


def _assistant_text(text: str) -> dict:
    return {"role": "assistant", "content": [{"text": text}]}


def _assistant_tool_use(tool_use_id: str) -> dict:
    return {
        "role": "assistant",
        "content": [{"toolUse": {"toolUseId": tool_use_id, "name": "lookup", "input": {}}}],
    }


def _user_tool_result(tool_use_id: str, value: str) -> dict:
    return {
        "role": "user",
        "content": [{"toolResult": {"toolUseId": tool_use_id, "content": [{"text": value}], "status": "success"}}],
    }


def _complete(store: InMemoryTaskStore, context_id: str, identity: Identity, messages: list[dict]):
    task = new_task(context_id)
    record = store.create(task, identity)
    record.messages.extend(messages)
    record.task.status = TaskStatus(state=TaskState.COMPLETED)
    return record


def _plain_turns(n: int) -> list[dict]:
    """n independent user/assistant turn-pairs, no tool calls."""
    turns: list[dict] = []
    for i in range(n):
        turns.append(_user_text(f"turn-{i}-user"))
        turns.append(_assistant_text(f"turn-{i}-assistant"))
    return turns


def test_context_messages_returns_full_transcript_when_under_cap() -> None:
    store = InMemoryTaskStore()
    ctx = "thread-under-cap"
    messages = _plain_turns(3)
    _complete(store, ctx, _OWNER, messages)

    replayed = store.context_messages(ctx, _OWNER)
    assert replayed == messages


def test_context_messages_capped_to_max_context_messages_trailing() -> None:
    store = InMemoryTaskStore()
    ctx = "thread-over-cap"
    turn_count = MAX_CONTEXT_MESSAGES  # 2 messages per turn -> well over cap
    messages = _plain_turns(turn_count)
    _complete(store, ctx, _OWNER, messages)

    replayed = store.context_messages(ctx, _OWNER)
    assert len(replayed) <= MAX_CONTEXT_MESSAGES, (
        f"expected at most {MAX_CONTEXT_MESSAGES} messages, got {len(replayed)}"
    )
    assert len(replayed) < len(messages), "must actually truncate, not return everything"
    # newest content must survive — the tail end of the transcript
    assert replayed[-1] == messages[-1]
    assert f"turn-{turn_count - 1}-assistant" in str(replayed[-1])


def test_context_messages_cap_truncates_from_front_at_turn_boundary() -> None:
    """A cap that lands mid-tool-round (a toolResult with no matching
    toolUse still in the window, or a dangling assistant toolUse tail) must
    be pushed forward to the next genuine user-authored turn start."""
    store = InMemoryTaskStore()
    ctx = "thread-turn-boundary"

    # Build a transcript where a naive trailing-N slice would land inside a
    # tool round: many small filler turns, then one turn with a tool call,
    # then a final plain turn.
    messages: list[dict] = []
    messages.extend(_plain_turns(MAX_CONTEXT_MESSAGES - 2))
    messages.append(_user_text("please look something up"))
    messages.append(_assistant_tool_use("call-1"))
    messages.append(_user_tool_result("call-1", "looked-up-value"))
    messages.append(_assistant_text("here is the answer"))
    messages.append(_user_text("final-turn"))
    messages.append(_assistant_text("final-answer"))
    _complete(store, ctx, _OWNER, messages)

    replayed = store.context_messages(ctx, _OWNER)
    assert replayed, "must not be empty"
    first = replayed[0]
    assert first.get("role") == "user", f"must start on a user turn, got {first!r}"
    content = first.get("content") or []
    assert not any(
        isinstance(block, dict) and "toolResult" in block for block in content
    ), f"must not start mid-tool-round on a dangling toolResult, got {first!r}"


def test_max_context_messages_is_a_class_attribute() -> None:
    """Mirrors RT-006's precedent for MAX_REUSABLE_TASKS: the cap must be a
    real, overridable class attribute, not just a module constant closed
    over directly by the method."""
    assert hasattr(InMemoryTaskStore, "MAX_CONTEXT_MESSAGES")
    assert InMemoryTaskStore.MAX_CONTEXT_MESSAGES == MAX_CONTEXT_MESSAGES


def test_subclass_can_override_max_context_messages_cap() -> None:
    class NarrowCapStore(InMemoryTaskStore):
        MAX_CONTEXT_MESSAGES = 4

    store = NarrowCapStore()
    ctx = "thread-narrow-cap"
    messages = _plain_turns(10)
    _complete(store, ctx, _OWNER, messages)

    replayed = store.context_messages(ctx, _OWNER)
    assert len(replayed) <= 4, (
        f"subclass override of MAX_CONTEXT_MESSAGES had no effect, got {len(replayed)} messages"
    )
