"""RT-001: ``resolve_deferred_result``'s max-depth rejection (registry.py)
must clean up an abandoned Task/Future-backed handle, not just a coroutine
one.

``DeferredResult.handle`` is documented (deferred.py:10-13) as any
``Awaitable[Any]`` — "typically a coroutine or an asyncio.Future". The
max-depth cleanup only ever called ``.close()`` on the abandoned innermost
handle, which exists on coroutine objects but not on ``asyncio.Future``/
``asyncio.Task`` (those only support ``.cancel()``). At >=3-deep nesting a
Task-backed handle was therefore neither closed nor cancelled — its
detached background work ran to completion with the result silently
discarded.

Fix: also attempt ``.cancel()`` on the abandoned handle so a Future/Task is
actually cancelled rather than left running unobserved.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.registry import ToolDecl, ToolEntry
from agent_sdk.models.errors import AgentError


def _deferred_entry(handle_coro) -> ToolEntry:
    async def _fn() -> DeferredResult:
        return DeferredResult(handle=handle_coro)

    decl = ToolDecl(
        fn=_fn,
        name="rt001_task_handle_tool",
        description="deferred tool",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
        long_running=True,
    )
    return ToolEntry(decl=decl)


async def test_invoke_any_cancels_abandoned_task_handle_on_triple_nesting():
    async def _level_c_job():
        await asyncio.sleep(10)
        return {"unreachable": True}

    level_c_task: asyncio.Task = asyncio.ensure_future(_level_c_job())

    async def _level_b_job():
        await asyncio.sleep(0)
        return DeferredResult(handle=level_c_task)

    async def _level_a_job():
        await asyncio.sleep(0)
        return DeferredResult(handle=_level_b_job())

    entry = _deferred_entry(_level_a_job())

    try:
        with pytest.raises(AgentError):
            await entry.invoke_any({}, {})

        with pytest.raises(asyncio.CancelledError):
            await level_c_task

        assert level_c_task.cancelled(), (
            "abandoned Task-backed handle must be cancelled at the "
            "max-depth boundary, not left running unobserved"
        )
    finally:
        if not level_c_task.done():
            level_c_task.cancel()
