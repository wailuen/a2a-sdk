"""RT-002: cooperative cancellation of the deferred background awaiter must
survive a failing teardown.

``_run_deferred_background``'s ``except asyncio.CancelledError:`` branch
calls ``_fail("deferred job cancelled")`` (which invokes ``store.publish()``
/ ``store.close_streams()``) before re-raising. If a custom/persistent
``TaskStore`` raises during that teardown call (a plausible ordering: a
concurrent ``close_all()`` already closed streams, or a durable write
fails), the exception must NOT replace the ``CancelledError`` — doing so
would break cooperative cancellation of this fire-and-forget background
``asyncio.Task`` (the canceller — e.g. ``evict()`` during shutdown — expects
``await bg_task`` to raise ``CancelledError``, not an unrelated store
exception).

Drives a real ``long_running`` tool's background awaiter through a
never-resolving handle, cancels it mid-flight against a ``TaskStore`` whose
``publish()`` raises once armed, and asserts ``await record.bg_task`` raises
``asyncio.CancelledError`` — never the store's ``RuntimeError``. No
mock/patch — real ``run_task_worker`` + an ``InMemoryTaskStore`` subclass,
mirroring test_rt002_close_streams_finally_on_publish_failure.py's store-
failure-injection pattern.

RT-B-201 (redteam, agent/runner.py review): the ``except Exception: pass``
that swallows this teardown failure used to drop the exception's class name
entirely — LRN-044's exact "bare except Exception loses the class" shape.
Fixed to ``except Exception as exc:`` + ``logger.warning(...,
type(exc).__name__)`` before the ``raise``, so an operator sees WHICH
teardown error happened during an already-failing cancellation, even though
none of it reaches the wire.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])


class _RaisesOnPublishOnceArmed(InMemoryTaskStore):
    """Simulates a persistent-store durable-write failure during the
    CancelledError branch's ``_fail()`` teardown — armed only after the
    background task has begun awaiting the (never-resolving) handle, so the
    initial WORKING-status publish and task setup are unaffected."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.armed = False

    def publish(self, task_id: str, event: Any) -> None:
        if self.armed:
            raise RuntimeError("simulated durable store failure during cancel teardown")
        super().publish(task_id, event)


_cancel_tools = ToolSet()


async def _never_resolving_job() -> dict[str, Any]:
    await asyncio.sleep(100)
    return {"unreachable": True}  # pragma: no cover


@_cancel_tools.tool(tier=1, long_running=True, tool_timeout_override=30.0)
async def rt002_cancel_deferred_tool() -> DeferredResult:
    """Deferred tool whose handle never resolves on its own — cancelled by
    the test instead."""
    return DeferredResult(handle=_never_resolving_job())


_CANCEL_REGISTRY = ToolRegistry([_cancel_tools], {})


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


@pytest.mark.asyncio
async def test_cancelled_error_survives_failing_teardown_during_cancel(caplog) -> None:
    store = _RaisesOnPublishOnceArmed()
    record = _make_record(store)

    model = FakeModelClient().script(tool_call("rt002_cancel_deferred_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_CANCEL_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    assert record.bg_task is not None, "deferred background task was not launched"

    # let the background task actually begin awaiting the handle before
    # cancelling it.
    await asyncio.sleep(0.01)

    store.armed = True
    record.bg_task.cancel()

    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.runner"):
        with pytest.raises(asyncio.CancelledError):
            await record.bg_task

    # RT-B-201: the teardown failure (RuntimeError from store.publish) must
    # still be visible to an operator — logged, never swallowed silently.
    assert any(
        "RuntimeError" in r.message for r in caplog.records
    ), f"expected the teardown exception class name in the log — got {[r.message for r in caplog.records]!r}"
