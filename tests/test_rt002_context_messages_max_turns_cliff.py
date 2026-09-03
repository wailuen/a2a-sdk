"""RT-002: MAX_CONTEXT_MESSAGES must not silently disable A2A contextId
continuation for a single task whose own transcript legitimately exceeds
the cap.

A task that never finishes runs ``policies.max_turns`` turns, each folding
an assistant ``toolUse`` message and a ``user`` ``toolResult`` message
(2 messages/turn), plus the seed user message and the final
``bridge_trailing_user`` synthetic assistant turn: ``2 * max_turns + 2``
messages total. The ONLY genuine turn boundary (a plain ``user`` message
with no ``toolResult`` block) is the seed message at index 0.

With the default ``MAX_CONTEXT_MESSAGES = 50``, ``max_turns = 24`` produces
exactly 50 messages (fits, no truncation). ``max_turns = 25`` produces 52 —
truncation kicks in, the trailing 50-message window excludes the only
boundary (index 0), and before the RT-002 fix ``_turn_boundary_slice``
returned ``[]``: the entire prior transcript silently vanished from
contextId continuation, with no log line, for every operator running
``AGENT_SDK_MAX_TURNS`` above ~24.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState, TaskStatus
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_OWNER = Identity(kind="api_key", subject="owner", admin=False)

tools = ToolSet()


class EchoIn(BaseModel):
    text: str


@tools.tool(tier=1)
async def echo(inp: EchoIn) -> dict:
    """Echoes input (never finishes the loop on its own)."""
    return {"echo": inp.text}


REGISTRY = ToolRegistry([tools], {})


async def _run_to_max_turns_exhaustion(max_turns: int) -> list[dict]:
    model = FakeModelClient([tool_call("echo", {"text": f"t{i}"}) for i in range(max_turns)])
    messages: list[dict] = [{"role": "user", "content": [{"text": "go"}]}]
    async for _ in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="test",
        messages=messages,
        policies=LoopPolicies(max_turns=max_turns),
    ):
        pass
    return messages


def _complete(store: InMemoryTaskStore, context_id: str, messages: list[dict]):
    task = new_task(context_id)
    record = store.create(task, _OWNER)
    record.messages.extend(messages)
    record.task.status = TaskStatus(state=TaskState.FAILED)
    return record


async def test_max_turns_25_transcript_shape_has_no_boundary_in_cap_window() -> None:
    """Pins the exact math the fix relies on, independent of the store."""
    messages = await _run_to_max_turns_exhaustion(25)
    assert len(messages) == 2 * 25 + 2 == 52
    assert len(messages) > InMemoryTaskStore.MAX_CONTEXT_MESSAGES
    tail = messages[-InMemoryTaskStore.MAX_CONTEXT_MESSAGES :]
    assert all(
        not (m.get("role") == "user" and not any(
            isinstance(b, dict) and "toolResult" in b for b in (m.get("content") or [])
        ))
        for m in tail
    ), "fixture invariant broken: a boundary landed inside the cap window"


async def test_context_messages_does_not_drop_entire_transcript_at_max_turns_25(
    sdk_caplog,
) -> None:
    messages = await _run_to_max_turns_exhaustion(25)
    store = InMemoryTaskStore()
    ctx = "thread-max-turns-25"

    with sdk_caplog("agent_sdk.tasks.memory", logging.WARNING) as records:
        _complete(store, ctx, messages)
        replayed = store.context_messages(ctx, _OWNER)

    assert replayed, "must not silently drop the entire prior transcript"
    assert replayed[-1] == messages[-1]
    assert replayed[0].get("role") == "user"
    content = replayed[0].get("content") or []
    assert not any(isinstance(b, dict) and "toolResult" in b for b in content)
    assert any("turn boundary" in r.getMessage() for r in records), (
        "the cap-window miss must be logged, not silent"
    )


async def test_context_messages_full_transcript_still_returned_when_under_cap_at_max_turns_24(
    sdk_caplog,
) -> None:
    """max_turns=24 -> exactly 50 messages == the cap: no truncation at all,
    so no fallback and no warning — the cliff is specific to exceeding it."""
    messages = await _run_to_max_turns_exhaustion(24)
    assert len(messages) == InMemoryTaskStore.MAX_CONTEXT_MESSAGES == 50

    store = InMemoryTaskStore()
    ctx = "thread-max-turns-24"
    with sdk_caplog("agent_sdk.tasks.memory", logging.WARNING) as records:
        _complete(store, ctx, messages)
        replayed = store.context_messages(ctx, _OWNER)

    assert replayed == messages
    assert not records
