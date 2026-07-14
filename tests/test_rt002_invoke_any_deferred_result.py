"""RT-002: ToolEntry.invoke_any() must resolve DeferredResult, not discard it.

Before the fix, invoke_any() (registry.py) only special-cased the
async-generator long-running form (RT-002/LRN-116's GH-115 mirror). A
long_running=True COROUTINE tool returning DeferredResult was returned
verbatim: the caller (the commitments executor, which has no background
delivery channel of its own — routes/mcp.py resolves this inline for the
same reason) never awaited ``deferred.handle``, so the background job never
ran, the commitment was still marked 'fired', and the handle coroutine leaked
an "was never awaited" RuntimeWarning.

Tests:
1. test_invoke_any_resolves_deferred_result_for_coroutine_tool: invoke_any()
   on a long_running=True coroutine tool returning DeferredResult must return
   the RESOLVED handle value, and the handle's side effect must have run.
2. test_invoke_any_still_resolves_generator_terminal_value: the existing
   async-generator branch is untouched by the fix (regression guard).
3. test_executor_fire_actually_runs_deferred_handle: end-to-end through the
   real CommitmentExecutor + a real ToolSet/ToolRegistry-built ToolEntry (no
   FakeEntry) — the deferred job's side effect must run before the commitment
   is marked fired.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import ToolProgressEvent
from agent_sdk.agent.registry import ToolDecl, ToolEntry, ToolRegistry, ToolSet, ToolTerminalResult
from agent_sdk.contrib.commitments import CommitmentExecutor, CommitmentStore


def _coroutine_deferred_entry(handle_coro, *, tool_timeout_override=None) -> ToolEntry:
    async def _fn() -> DeferredResult:
        return DeferredResult(handle=handle_coro)

    decl = ToolDecl(
        fn=_fn,
        name="rt002_deferred_tool",
        description="deferred tool",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
        long_running=True,
        tool_timeout_override=tool_timeout_override,
    )
    return ToolEntry(decl=decl)


async def test_invoke_any_resolves_deferred_result_for_coroutine_tool():
    ran = {"value": False}

    async def _job():
        await asyncio.sleep(0)
        ran["value"] = True
        return {"ok": True, "value": "deferred-done"}

    entry = _coroutine_deferred_entry(_job())
    result = await entry.invoke_any({}, {})

    assert not isinstance(result, DeferredResult), (
        f"handle must be resolved, not returned verbatim: {result!r}"
    )
    assert result == {"ok": True, "value": "deferred-done"}
    assert ran["value"] is True, "the deferred handle's side effect never ran"


async def test_invoke_any_deferred_result_honors_timeout_override():
    entry = _coroutine_deferred_entry(asyncio.sleep(9999), tool_timeout_override=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(entry.invoke_any({}, {}), timeout=5.0)


async def test_invoke_any_still_resolves_generator_terminal_value():
    async def _gen_fn():
        yield ToolProgressEvent(message="working", tool_name="rt002_gen_tool")
        yield {"ok": True}

    decl = ToolDecl(
        fn=_gen_fn,
        name="rt002_gen_tool",
        description="gen tool",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
        is_generator=True,
        long_running=True,
    )
    entry = ToolEntry(decl=decl)
    result = await entry.invoke_any({}, {})
    assert result == {"ok": True}


async def test_executor_fire_actually_runs_deferred_handle(tmp_path):
    store = CommitmentStore(str(tmp_path / "commitments.db"))
    store.initialize()
    ran = {"value": False}

    async def _job():
        await asyncio.sleep(0)
        ran["value"] = True

    tools = ToolSet()

    @tools.tool(tier=1, long_running=True)
    async def rt002_commitment_tool() -> DeferredResult:
        """Long-running tool committed and fired by the executor."""
        return DeferredResult(handle=_job())

    registry = ToolRegistry([tools], {})
    from datetime import datetime, timedelta, timezone

    fire_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cid = store.add(tool="rt002_commitment_tool", args={}, fire_at=fire_at)

    executor = CommitmentExecutor(store, registry, {})
    fired = await executor.tick_once()

    assert fired == 1
    assert ran["value"] is True, "the deferred handle was dropped unawaited"
    assert store.get(cid).status == "fired"
    store.close()


async def test_executor_fire_marks_failed_when_deferred_handle_times_out(tmp_path):
    # RT-001: the mark_FAILED-on-timeout complement to
    # test_executor_fire_actually_runs_deferred_handle. A committed
    # long_running tool whose DeferredResult handle never resolves within the
    # tool's timeout must leave the commitment FAILED (not fired), driven
    # through the real CommitmentExecutor + a real ToolRegistry-built entry
    # (no FakeEntry) so the executor's real invoke_any/resolve_deferred_result
    # timeout path is exercised end-to-end.
    store = CommitmentStore(str(tmp_path / "commitments.db"))
    store.initialize()

    tools = ToolSet()

    @tools.tool(tier=1, long_running=True, tool_timeout_override=0.05)
    async def rt001_slow_commitment_tool() -> DeferredResult:
        """Long-running tool whose deferred handle never resolves in time."""
        return DeferredResult(handle=asyncio.sleep(9999))

    registry = ToolRegistry([tools], {})
    from datetime import datetime, timedelta, timezone

    fire_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cid = store.add(tool="rt001_slow_commitment_tool", args={}, fire_at=fire_at)

    executor = CommitmentExecutor(store, registry, {})
    fired = await executor.tick_once()

    assert fired == 1  # the due commitment was claimed and processed
    assert store.get(cid).status == "failed", (
        "a deferred handle that times out must mark the commitment failed, "
        "not fired"
    )
    store.close()
