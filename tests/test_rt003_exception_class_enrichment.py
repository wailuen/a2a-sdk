"""RT-001 (amended LRN-044 Check, this wave): every bare ``except Exception``
in agent/loop.py must log the caught exception's class name
(``type(exc).__name__``) for an operator — but must NEVER interpolate it into
the WIRE-facing ``ToolResultEvent.error`` string. ``ToolResultEvent.error`` is
stringified verbatim into the AG-UI ``TOOL_CALL_RESULT.content`` frame
(routes/ag_ui.py) and folded into ``record.messages``, replayed on every later
contextId continuation — an untrusted caller must never learn the exact
upstream failure class (SI-2). Mirrors bedrock.py's RT-006 / runner.py's
RT-002 precedent (test_rt003_deferred_exception_enrichment.py).

Covers all three bare handlers: the coroutine-tool branch, the
async-generator-tool branch, and the post-interrupt ``resume_handler``
branch.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import ToolInterrupt, run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.testing import FakeModelClient, tool_call

pytestmark = pytest.mark.asyncio

SECRET = "sk-leaked-secret-token-abc123"


class In(BaseModel):
    x: int


tools = ToolSet()


@tools.tool(tier=1)
async def coroutine_raises_tool(inp: In) -> Any:
    raise RuntimeError(SECRET)


@tools.tool(tier=1)
async def generator_raises_tool(inp: In) -> AsyncGenerator[Any, None]:
    raise RuntimeError(SECRET)
    yield None  # pragma: no cover - unreachable, keeps this an async generator


async def _bad_resume_handler(resume_value: Any) -> Any:
    raise RuntimeError(SECRET)


@tools.tool(tier=1)
async def interrupt_then_raising_resume_tool(inp: In) -> Any:
    raise ToolInterrupt(
        "need-more-info", "give me more", resume_handler=_bad_resume_handler
    )


REGISTRY = ToolRegistry([tools], {})


async def _collect(model: FakeModelClient):
    async def wait_resume(_interrupt_id: str) -> Any:
        return {"ok": True}

    events = []
    async for ev in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="test",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
        wait_resume=wait_resume,
    ):
        events.append(ev)
    return events


def _first_result(events: list[Any]) -> ToolResultEvent:
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results, "expected at least one ToolResultEvent"
    return results[0]


async def test_coroutine_generic_exception_wire_message_is_fixed_and_logged(caplog):
    model = FakeModelClient([tool_call("coroutine_raises_tool", {"x": 1})])
    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.loop"):
        result = _first_result(await _collect(model))
    assert not result.ok
    # RT-001: the wire message is always the fixed literal — never the
    # exception's class name (matches bedrock.py's RT-006 precedent).
    assert result.error == "tool 'coroutine_raises_tool' failed", result.error
    assert "RuntimeError" not in result.error, (
        f"exception class name leaked onto the wire: {result.error!r}"
    )
    assert SECRET not in result.error, f"raw exception text leaked (SI-2): {result.error!r}"
    # The class name is still available for an operator — in the log, not the wire.
    assert any(
        "RuntimeError" in r.message for r in caplog.records
    ), f"expected the exception class name in the log — got {[r.message for r in caplog.records]!r}"


async def test_generator_generic_exception_wire_message_is_fixed_and_logged(caplog):
    model = FakeModelClient([tool_call("generator_raises_tool", {"x": 1})])
    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.loop"):
        result = _first_result(await _collect(model))
    assert not result.ok
    assert result.error == "tool 'generator_raises_tool' failed", result.error
    assert "RuntimeError" not in result.error, (
        f"exception class name leaked onto the wire: {result.error!r}"
    )
    assert SECRET not in result.error, f"raw exception text leaked (SI-2): {result.error!r}"
    assert any(
        "RuntimeError" in r.message for r in caplog.records
    ), f"expected the exception class name in the log — got {[r.message for r in caplog.records]!r}"


async def test_resume_handler_generic_exception_wire_message_is_fixed_and_logged(caplog):
    model = FakeModelClient([tool_call("interrupt_then_raising_resume_tool", {"x": 1})])
    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.loop"):
        result = _first_result(await _collect(model))
    assert not result.ok
    assert result.error == (
        "tool 'interrupt_then_raising_resume_tool' failed after resume"
    ), result.error
    assert "RuntimeError" not in result.error, (
        f"exception class name leaked onto the wire: {result.error!r}"
    )
    assert SECRET not in result.error, f"raw exception text leaked (SI-2): {result.error!r}"
    assert any(
        "RuntimeError" in r.message for r in caplog.records
    ), f"expected the exception class name in the log — got {[r.message for r in caplog.records]!r}"
