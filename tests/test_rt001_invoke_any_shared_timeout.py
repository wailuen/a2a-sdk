"""RT-001: ``ToolEntry.invoke_any`` must accept a caller-supplied ``timeout``
(and optional ``policies``) so ``routes/mcp.py`` and ``routes/admin.py`` can
share one is_generator/DeferredResult dispatch implementation instead of each
re-implementing it (LRN-116 Prevention clause).

RT-003 (folded into this same helper): when a ``timeout`` is given and the
resolved result is a ``DeferredResult``, the handle must be awaited under the
REMAINING portion of that one deadline — not a fresh ``timeout`` seconds on
top — so a slow initial invoke/drain can't double the worst-case wall-clock
block.

Tests:
1. test_invoke_any_timeout_bounds_hanging_coroutine: an explicit ``timeout``
   bounds a plain coroutine tool that never resolves.
2. test_invoke_any_timeout_bounds_hanging_generator: same, for the
   async-generator branch.
3. test_invoke_any_deferred_result_single_deadline_not_doubled: a slow
   initial invoke() (returning a DeferredResult) plus a handle that resolves
   just inside the remaining budget must succeed within ~timeout total wall
   clock, never ~2x timeout.
4. test_invoke_any_deferred_result_timeout_uses_remaining_budget: a slow
   initial invoke() that consumes nearly the whole timeout budget leaves the
   handle almost no remaining time, so a handle that takes longer than what's
   left must raise TimeoutError promptly (not be granted a fresh full budget).
5. test_invoke_any_no_timeout_preserves_legacy_behavior: omitting ``timeout``
   (the commitments-executor call shape) leaves the initial invoke/drain
   unbounded and only resolves a DeferredResult via ``resolve_tool_timeout``
   against ``policies`` — unchanged regression guard for the existing
   behavior other callers depend on.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.events import ToolProgressEvent
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolDecl, ToolEntry


def _entry(fn, *, is_generator=False, tool_timeout_override=None) -> ToolEntry:
    decl = ToolDecl(
        fn=fn,
        name="rt001_shared_timeout_tool",
        description="test tool",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
        is_generator=is_generator,
        long_running=True,
        tool_timeout_override=tool_timeout_override,
    )
    return ToolEntry(decl=decl)


async def test_invoke_any_timeout_bounds_hanging_coroutine() -> None:
    async def _hang():
        await asyncio.sleep(9999)
        return "unreachable"

    entry = _entry(_hang)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(entry.invoke_any({}, {}, timeout=0.05), timeout=5.0)


async def test_invoke_any_timeout_bounds_hanging_generator() -> None:
    async def _hang_gen():
        yield ToolProgressEvent(message="working", tool_name="rt001_shared_timeout_tool")
        await asyncio.sleep(9999)
        yield "unreachable"

    entry = _entry(_hang_gen, is_generator=True)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(entry.invoke_any({}, {}, timeout=0.05), timeout=5.0)


async def test_invoke_any_deferred_result_single_deadline_not_doubled() -> None:
    async def _slow_then_defer():
        await asyncio.sleep(0.1)

        async def _handle():
            await asyncio.sleep(0.1)
            return "resolved"

        return DeferredResult(handle=_handle())

    entry = _entry(_slow_then_defer)
    start = time.monotonic()
    result = await asyncio.wait_for(entry.invoke_any({}, {}, timeout=0.6), timeout=5.0)
    elapsed = time.monotonic() - start

    assert result == "resolved"
    assert elapsed < 0.6, (
        f"single deadline must cover both the initial call and the handle "
        f"await, not double the budget; took {elapsed:.2f}s"
    )


async def test_invoke_any_deferred_result_timeout_uses_remaining_budget() -> None:
    async def _slow_then_defer():
        await asyncio.sleep(0.4)

        async def _handle():
            await asyncio.sleep(9999)

        return DeferredResult(handle=_handle())

    entry = _entry(_slow_then_defer)
    start = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(entry.invoke_any({}, {}, timeout=0.5), timeout=5.0)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, (
        "the handle must only get the REMAINING budget (~0.1s here), not a "
        f"fresh 0.5s timeout on top of the 0.4s already spent; took {elapsed:.2f}s"
    )


async def test_invoke_any_no_timeout_preserves_legacy_behavior() -> None:
    ran = {"value": False}

    async def _job():
        await asyncio.sleep(0)
        ran["value"] = True
        return "deferred-done"

    async def _fn():
        return DeferredResult(handle=_job())

    entry = _entry(_fn, tool_timeout_override=5.0)
    result = await entry.invoke_any({}, {}, policies=LoopPolicies())

    assert result == "deferred-done"
    assert ran["value"] is True
