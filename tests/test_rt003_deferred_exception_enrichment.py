"""RT-002 (agent/runner.py review, supersedes this module's original RT-003
premise): the THREE bare ``except Exception`` blocks in ``agent/runner.py``'s
``_run_deferred_background`` — the handle-resolution try (``ValidationError``
and anything else other than ``asyncio.TimeoutError``/``CancelledError``),
the build/serialize try (``fold_result_content``/``build_artifact``/
``TaskArtifactUpdateEvent.wire()``, RT-B-201), and the post-build publish/
append/status-transition try — enrich the caught exception's class name
(``type(exc).__name__``) into the LOG line only, never into the wire message.

RT-B-201 (redteam, agent/runner.py review): the build/serialize block was
originally missed by this module's RT-002 log-only fix — it mapped
``ValueError`` straight to ``_fail("invalid agent response", code=-32006)``
with no ``logger`` call at all, so an operator had zero attribution for a
malformed domain card / non-serializable resolved value (LRN-044: pydantic's
``ValidationError`` IS a ``ValueError``, so this silently destroyed all
validation attribution). ``test_deferred_build_artifact_failure_wire_message_
is_fixed_and_logged`` below covers that third block specifically.

A prior wave's RT-003 pass had instead interpolated the class name straight
into the string ``_fail()`` publishes — reaching ``WireError.message``, the
user-facing status ``Message``, and ``ToolResultEvent.error``, all consumed
by the untrusted A2A/AG-UI caller. That directly contradicted RT-006 in the
SAME release, which removed the identical ``type(exc).__name__`` enrichment
from ``BedrockModelClient.converse``'s own wire message for exactly this
reason (a client could otherwise learn the upstream provider and its precise
auth/quota failure mode — ``NoCredentialsError``, ``ThrottlingException``,
...). The deferred handle wraps arbitrary tool/upstream code, so the same
leak applied here. Fixed to match RT-006's precedent and this module's own
fixed-string branches (``_fail("internal error")`` elsewhere in this same
function, ``msg = "internal error"`` in ``run_task_worker``'s terminal
handlers): the wire string is always one of the two fixed literals below; the
class name reaches only ``logger.warning``.

These tests drive real ``long_running`` tools through the real
``run_task_worker`` / ``InMemoryTaskStore`` (no mock/patch), mirroring
test_rt001_deferred_artifact_build_failure.py and
test_rt002_close_streams_finally_on_publish_failure.py's style, so they run
independently of the full FastAPI app (no ``build_app()`` / HTTP layer
involved).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import StreamItem, new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])

SECRET = "sk-leaked-secret-token-abc123"


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


async def _wait_for_state(
    store: InMemoryTaskStore, task_id: str, timeout: float = 5.0
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        record = store.get(task_id)
        assert record is not None, "task record evicted during wait"
        state = record.task.status.state
        if state in ("completed", "failed"):
            return state
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"task stuck in state {state!r} after {timeout}s")
        await asyncio.sleep(0.02)


# ── handle-resolution failure: a ValidationError from the deferred handle ──

_HandleFailModel = type("_HandleFailModel", (BaseModel,), {"__annotations__": {"x": int}})

_handle_fail_tools = ToolSet()


async def _validating_job() -> None:
    await asyncio.sleep(0)
    # Not a tool-argument validation error (that path is ToolInputValidationError) —
    # a ValidationError raised from INSIDE the deferred handle's own body, the
    # exact "swallowed by catch-all" shape LRN-044 describes.
    _HandleFailModel(x=SECRET)


@_handle_fail_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt003_validation_error_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle raises ValidationError."""
    return DeferredResult(handle=_validating_job())


_HANDLE_FAIL_REGISTRY = ToolRegistry([_handle_fail_tools], {})


@pytest.mark.asyncio
async def test_deferred_handle_validation_error_wire_message_is_fixed(caplog) -> None:
    store = InMemoryTaskStore()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("rt003_validation_error_deferred_tool", {}))

    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.runner"):
        await run_task_worker(
            store=store,
            record=record,
            model=model,
            registry=_HANDLE_FAIL_REGISTRY,
            adapters={},
            skills=None,
            system="test system prompt",
            capabilities=_CAPABILITIES,
            policies=LoopPolicies(),
        )

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.FAILED, final_state

    rec = store.get(task_id)
    assert rec is not None
    error = rec.task.status.error
    assert error is not None, "expected a WireError on the FAILED task"
    assert error.code == -32603, f"expected -32603 internal error, got {error.code}"
    # RT-002: the wire message is always the fixed literal — never the
    # exception's class name (matches bedrock.py's RT-006 precedent).
    assert error.message == "deferred job failed", error.message
    # SI-2: never the raw exception text (which embeds the secret value).
    assert SECRET not in error.message, f"raw exception text leaked (SI-2): {error.message!r}"
    # The class name is still available for an operator — in the log, not the wire.
    assert any(
        "ValidationError" in r.message for r in caplog.records
    ), f"expected the exception class name in the log — got {[r.message for r in caplog.records]!r}"


def test_validating_job_actually_raises_validation_error() -> None:
    """Guards the fixture: confirms _validating_job's ValidationError is not
    accidentally caught earlier (e.g. by ToolInputValidationError) — it must
    reach the bare ``except Exception`` this test targets."""
    with pytest.raises(ValidationError):
        _HandleFailModel(x=SECRET)


# ── post-build failure: a publish() raise after the handle resolves ok ─────

_publish_fail_tools = ToolSet()


class _GoodResult(BaseModel):
    data_type: str = "rt003_publish_fail_result"
    value: str = "ok"


async def _clean_job() -> _GoodResult:
    await asyncio.sleep(0)
    return _GoodResult()


@_publish_fail_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt003_publish_fail_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle resolves cleanly; the artifact-frame
    publish is what fails."""
    return DeferredResult(handle=_clean_job())


_PUBLISH_FAIL_REGISTRY = ToolRegistry([_publish_fail_tools], {})


class _ArtifactPublishRaisesRuntimeError(InMemoryTaskStore):
    """Mirrors test_rt002_close_streams_finally_on_publish_failure.py's
    ``_ArtifactPublishExplodesOnce`` — a real store subclass whose publish()
    raises on the artifact frame, driving the post-build
    ``except Exception`` branch this test targets."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._raised = False

    def publish(self, task_id: str, event: Any) -> None:
        if (
            not self._raised
            and isinstance(event, StreamItem)
            and isinstance(event.event, ArtifactEvent)
        ):
            self._raised = True
            raise RuntimeError(SECRET)
        super().publish(task_id, event)


@pytest.mark.asyncio
async def test_deferred_post_build_publish_failure_wire_message_is_fixed(caplog) -> None:
    store = _ArtifactPublishRaisesRuntimeError()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("rt003_publish_fail_deferred_tool", {}))

    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.runner"):
        await run_task_worker(
            store=store,
            record=record,
            model=model,
            registry=_PUBLISH_FAIL_REGISTRY,
            adapters={},
            skills=None,
            system="test system prompt",
            capabilities=_CAPABILITIES,
            policies=LoopPolicies(),
        )

        assert record.bg_task is not None
        await record.bg_task  # handled internally → no propagation

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.FAILED, final_state

    rec = store.get(task_id)
    assert rec is not None
    error = rec.task.status.error
    assert error is not None, "expected a WireError on the FAILED task"
    assert error.code == -32603, f"expected -32603 internal error, got {error.code}"
    # RT-002: the wire message is always the fixed literal — never the
    # exception's class name (matches bedrock.py's RT-006 precedent).
    assert error.message == "internal error", error.message
    # SI-2: never the raw exception text (which embeds the secret value).
    assert SECRET not in error.message, f"raw exception text leaked (SI-2): {error.message!r}"
    # The class name is still available for an operator — in the log, not the wire.
    assert any(
        "RuntimeError" in r.message for r in caplog.records
    ), f"expected the exception class name in the log — got {[r.message for r in caplog.records]!r}"


# ── build/serialize failure: build_artifact raises after the handle resolves ok ──

_build_fail_tools = ToolSet()


class _Unserializable:
    """A plain object with no special handling in build_artifact(): str()
    succeeds (fold_result_content's fallback branch is safe), but the
    instance is NOT JSON-serializable — reaches the plain-scalar branch of
    build_artifact() and fails its own end-of-function json.dumps guard,
    raising ValueError from INSIDE the build/serialize try (RT-B-201),
    distinct from both blocks above (which fail resolve_deferred_result and
    a post-build publish() respectively, never build_artifact itself)."""


async def _build_fail_job() -> _Unserializable:
    await asyncio.sleep(0)
    return _Unserializable()


@_build_fail_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt201_build_fail_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle resolves cleanly to a value build_artifact
    cannot serialize."""
    return DeferredResult(handle=_build_fail_job())


_BUILD_FAIL_REGISTRY = ToolRegistry([_build_fail_tools], {})


@pytest.mark.asyncio
async def test_deferred_build_artifact_failure_wire_message_is_fixed_and_logged(caplog) -> None:
    store = InMemoryTaskStore()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("rt201_build_fail_deferred_tool", {}))

    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.runner"):
        await run_task_worker(
            store=store,
            record=record,
            model=model,
            registry=_BUILD_FAIL_REGISTRY,
            adapters={},
            skills=None,
            system="test system prompt",
            capabilities=_CAPABILITIES,
            policies=LoopPolicies(),
        )

        assert record.bg_task is not None
        await record.bg_task  # handled internally → no propagation

    final_state = await _wait_for_state(store, task_id)
    assert final_state == TaskState.FAILED, final_state

    rec = store.get(task_id)
    assert rec is not None
    error = rec.task.status.error
    assert error is not None, "expected a WireError on the FAILED task"
    # build_artifact's own RT-001 guard maps a non-serializable payload's
    # ValueError to -32006 ("invalid agent response").
    assert error.code == -32006, f"expected -32006 invalid agent response, got {error.code}"
    assert error.message == "invalid agent response", error.message
    # RT-B-201: the bug this test guards was a MISSING log call on this
    # specific branch — the wire message was already fixed pre-fix, only the
    # operator-facing class name was silently dropped.
    assert any(
        "ValueError" in r.message for r in caplog.records
    ), f"expected the exception class name in the log — got {[r.message for r in caplog.records]!r}"
