"""RT-005: a mid-turn ``build_artifact`` failure must repair the dangling
``toolUse`` tail, exactly like GH-150's cancel path and RT-002's deferred
path.

Root cause: ``run_loop`` folds a turn's assistant ``toolUse`` message into
``record.messages`` (``agent/loop.py:491``) BEFORE running that turn's
per-tool-call loop; the matching ``toolResult`` message is appended only
once every tool call in the turn finishes (``agent/loop.py:815``).
``ArtifactEvent`` is yielded mid-loop (``agent/loop.py:777``), and
``run_task_worker`` builds the artifact SYNCHRONOUSLY at that point
(``agent/runner.py``'s ``ArtifactEvent`` branch) — a ``build_artifact``
raise (e.g. ``_validate_a2ui_wire`` rejecting a non-conformant domain card,
or the JSON-serializability guard) therefore propagates out of the
``async for event in run_loop(...)`` BEFORE the turn's ``toolResult``
message is ever appended. Before this fix, ``run_task_worker``'s own
``except AgentError`` / ``except Exception`` terminal handlers set the task
FAILED without calling ``repair_dangling_tool_use`` — unlike GH-150's
``tasks_cancel`` and RT-002's ``_run_deferred_background``, which both
already did. FAILED is terminal, so ``context_messages()`` would replay the
dangling-toolUse transcript verbatim on the next contextId continuation —
the identical failure shape GH-150 fixed, on a path GH-150 did not cover.

Drives a real tier-1 (non-``long_running``) tool through ``run_task_worker``
whose declared ``emits`` is a plain (non-BaseModel) class and whose returned
instance is not JSON-serializable — the same fixture shape as
test_rt001_sync_artifact_nonserializable_emits.py, which already proves this
raises ValueError inside build_artifact and fails the task with -32006. That
existing test does not inspect ``record.messages``; this one does.

RT-B-201 (redteam, agent/runner.py review): this ``except Exception as exc:``
handler bound ``exc`` and used it only for ``isinstance(exc, ValueError)`` —
no ``logger`` call at all — so a pydantic ``ValidationError`` (a ``ValueError``
subclass, LRN-044) or any other mid-turn ``build_artifact`` raise reached the
wire as the fixed "invalid agent response" string with ZERO operator
attribution. Fixed to log ``type(exc).__name__`` before mapping to the wire
error, matching the pattern this module's sibling exception handlers already
use (``_run_deferred_background``'s ``logger.warning`` calls). This test now
also asserts that log line.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _NonSerializablePayload:
    """A plain (non-BaseModel) ``emits`` type: ``str()`` succeeds (so the
    TextPart fallback renders fine) but the instance is NOT JSON-serializable
    — build_artifact's plain-scalar branch embeds it raw and its own
    end-of-function json.dumps guard raises ValueError."""

    def __str__(self) -> str:  # noqa: D401
        return "renders fine but is not JSON-serializable"


_rt005_tools = ToolSet()


@_rt005_tools.tool(tier=1, emits=_NonSerializablePayload)
async def rt005_nonserializable_tool() -> _NonSerializablePayload:
    """Tool whose declared emits type is not a BaseModel and whose result
    is not JSON-serializable — makes build_artifact raise mid-turn."""
    return _NonSerializablePayload()


_RT005_REGISTRY = ToolRegistry([_rt005_tools], {})


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


def _tool_use_ids(message: dict[str, Any]) -> set[str]:
    return {
        block["toolUse"]["toolUseId"]
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolUse" in block
    }


def _tool_result_ids(message: dict[str, Any]) -> set[str]:
    return {
        block["toolResult"]["toolUseId"]
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolResult" in block
    }


def assert_no_dangling_tool_use(messages: list[dict[str, Any]]) -> None:
    """Every assistant toolUse turn must be immediately followed by a
    message carrying a matching toolResult for every toolUseId — the
    Converse-API-shaped invariant contextId continuation replay depends on."""
    for i, message in enumerate(messages):
        ids = _tool_use_ids(message)
        if not ids:
            continue
        assert i + 1 < len(messages), (
            f"assistant toolUse turn at index {i} has no following message "
            f"(dangling toolUseId(s): {ids!r})"
        )
        result_ids = _tool_result_ids(messages[i + 1])
        missing = ids - result_ids
        assert not missing, (
            f"toolUseId(s) {missing!r} at index {i} have no matching "
            f"toolResult in the immediately-following message"
        )


def assert_alternates(messages: list[dict[str, Any]]) -> None:
    """GH-147 AC3 / RT-004: no two consecutive entries in ``messages`` may
    share a ``role`` — the exact shape Bedrock's Converse API rejects
    outright."""
    for prev, cur in zip(messages, messages[1:]):
        assert prev.get("role") != cur.get("role"), (
            f"two consecutive {cur.get('role')!r} messages: {prev!r} then {cur!r}"
        )


@pytest.mark.asyncio
async def test_midturn_build_artifact_failure_repairs_dangling_tool_use(caplog) -> None:
    store = InMemoryTaskStore()
    record = _make_record(store)
    task_id = record.task.id

    # A scripted follow-up reply is provided so a passing test proves the
    # RT-005 guard actually fired, rather than the loop coincidentally never
    # reaching a second model turn.
    model = FakeModelClient().script(
        tool_call("rt005_nonserializable_tool", {}), reply("unreachable")
    )

    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.runner"):
        await run_task_worker(
            store=store,
            record=record,
            model=model,
            registry=_RT005_REGISTRY,
            adapters={},
            skills=None,
            system="test system prompt",
            capabilities=_CAPABILITIES,
            policies=LoopPolicies(),
        )

    # RT-B-201: the exception class name must reach the log even though the
    # wire message stays the fixed "invalid agent response" literal (SI-2).
    assert any(
        "ValueError" in r.message for r in caplog.records
    ), f"expected the exception class name in the log — got {[r.message for r in caplog.records]!r}"

    rec = store.get(task_id)
    assert rec is not None
    assert rec.task.status.state == TaskState.FAILED, (
        f"expected FAILED for a non-serializable synchronous artifact result, got {rec.task.status.state!r}"
    )
    error = rec.task.status.error
    assert error is not None
    assert error.code == -32006

    messages = rec.messages
    assert messages, "expected the folded assistant toolUse turn to survive"
    assert messages[-1].get("role") != "user", (
        "record.messages must never be left ending on 'user' (GH-147 AC3) — "
        f"got {messages[-1]!r}"
    )
    assert_no_dangling_tool_use(messages)
    assert_alternates(messages)
