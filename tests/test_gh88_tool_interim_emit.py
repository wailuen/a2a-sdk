"""GH-88: async-generator tool can yield ProgressEvent/ToolProgressEvent
during execution and return its terminal ArtifactEvent-typed result.

Tests:
1. Generator tool yields 2 ToolProgressEvents then returns a result → all 3
   events appear downstream (2 interim + terminal ArtifactEvent).
2. Existing coroutine tool (return, not yield) still works unchanged.
3. Generator and coroutine tool paths produce identical terminal artifacts.
4. Generator tool yielding a non-ToolProgressEvent LoopEvent subclass:
   the event is silently dropped and a logger.warning is emitted (RT-W025-005).
5. RT-W025-003: Generator tool that yields only the terminal result (no interim
   events) → no crash, ArtifactEvent emitted correctly.
6. RT-W025-003: Generator tool that yields nothing at all → result=None,
   no ArtifactEvent, no crash, loop completes successfully.

No MagicMock/AsyncMock — uses FakeModelClient and the real run_loop.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import (
    ArtifactEvent,
    DoneEvent,
    LoopEvent,
    NoteEvent,
    ProgressEvent,
    TextEvent,
    ToolProgressEvent,
    ToolResultEvent,
)
from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.registry import ToolEntry, ToolRegistry, ToolSet
from agent_sdk.testing import FakeModelClient, reply, tool_call


# ── shared content type ──


class FakeResult(BaseModel):
    data_type: str = "fake_result"
    value: str


# ── tools under test ──

gen_tools = ToolSet()
coro_tools = ToolSet()


@gen_tools.tool(tier=1, emits=FakeResult)
async def slow_gen_tool() -> AsyncGenerator[Any, None]:
    """Generator tool that emits 2 progress events then yields the terminal result.

    Contract: yield ToolProgressEvent items for interim notifications;
    yield the terminal result (non-LoopEvent) as the final yield.
    Python async generators cannot use ``return <value>`` — the terminal
    result must be the last ``yield``.
    """
    yield ToolProgressEvent(message="step 1 of 2", tool_name="slow_gen_tool")
    yield ToolProgressEvent(message="step 2 of 2", tool_name="slow_gen_tool")
    yield FakeResult(value="done")  # terminal result — must be the last yield


@coro_tools.tool(tier=1, emits=FakeResult)
async def slow_coro_tool() -> FakeResult:
    """Coroutine tool — existing path, no yield."""
    return FakeResult(value="done")


GEN_REGISTRY = ToolRegistry([gen_tools], {})
CORO_REGISTRY = ToolRegistry([coro_tools], {})


# ── helpers ──


async def collect_events(model: FakeModelClient, registry: ToolRegistry) -> list[Any]:
    events: list[Any] = []
    async for ev in run_loop(
        model=model,
        registry=registry,
        adapters={},
        system="test",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
        policies=LoopPolicies(max_turns=5),
    ):
        events.append(ev)
    return events


# ── tests ──


@pytest.mark.asyncio
async def test_generator_tool_yields_interim_and_terminal():
    """Generator tool: 2 ToolProgressEvents appear BEFORE the terminal ArtifactEvent."""
    model = FakeModelClient().script(
        tool_call("slow_gen_tool", {}),
        reply("finished"),
    )
    events = await collect_events(model, GEN_REGISTRY)

    progress = [e for e in events if isinstance(e, ToolProgressEvent)]
    artifacts = [e for e in events if isinstance(e, ArtifactEvent)]
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    done = [e for e in events if isinstance(e, DoneEvent)]

    # 2 interim progress events
    assert len(progress) == 2, f"Expected 2 ToolProgressEvents, got {len(progress)}: {progress}"
    assert progress[0].message == "step 1 of 2"
    assert progress[1].message == "step 2 of 2"
    assert all(p.tool_name == "slow_gen_tool" for p in progress)

    # 1 terminal artifact
    assert len(artifacts) == 1
    assert artifacts[0].tool_name == "slow_gen_tool"
    assert isinstance(artifacts[0].model, FakeResult)
    assert artifacts[0].model.value == "done"

    # tool result exists and is ok
    assert results and results[0].ok

    # loop completed successfully
    assert done and done[-1].ok

    # progress events come BEFORE the artifact in the event stream
    first_progress_idx = events.index(progress[0])
    artifact_idx = events.index(artifacts[0])
    assert first_progress_idx < artifact_idx, "Progress events must precede the terminal artifact"


@pytest.mark.asyncio
async def test_coroutine_tool_unchanged():
    """Existing coroutine tool still works — no ToolProgressEvent, returns artifact."""
    model = FakeModelClient().script(
        tool_call("slow_coro_tool", {}),
        reply("finished"),
    )
    events = await collect_events(model, CORO_REGISTRY)

    progress = [e for e in events if isinstance(e, ToolProgressEvent)]
    artifacts = [e for e in events if isinstance(e, ArtifactEvent)]
    done = [e for e in events if isinstance(e, DoneEvent)]

    # no progress events for a plain coroutine tool
    assert progress == [], f"Coroutine tool must not emit ToolProgressEvent, got {progress}"

    # terminal artifact present
    assert len(artifacts) == 1
    assert isinstance(artifacts[0].model, FakeResult)
    assert artifacts[0].model.value == "done"

    assert done and done[-1].ok


@pytest.mark.asyncio
async def test_generator_and_coroutine_produce_identical_terminal_artifacts():
    """Both paths emit the same terminal FakeResult value."""
    model_gen = FakeModelClient().script(
        tool_call("slow_gen_tool", {}),
        reply("finished"),
    )
    model_coro = FakeModelClient().script(
        tool_call("slow_coro_tool", {}),
        reply("finished"),
    )

    gen_events = await collect_events(model_gen, GEN_REGISTRY)
    coro_events = await collect_events(model_coro, CORO_REGISTRY)

    gen_artifact = next(e for e in gen_events if isinstance(e, ArtifactEvent))
    coro_artifact = next(e for e in coro_events if isinstance(e, ArtifactEvent))

    assert gen_artifact.model.value == coro_artifact.model.value
    assert type(gen_artifact.model) is type(coro_artifact.model)
    assert gen_artifact.tool_name == coro_artifact.tool_name.replace("coro", "gen")


@pytest.mark.asyncio
async def test_tool_entry_is_generator_flag():
    """ToolEntry.decl.is_generator is set correctly for each tool type."""
    gen_entry = GEN_REGISTRY.get("slow_gen_tool")
    coro_entry = CORO_REGISTRY.get("slow_coro_tool")

    assert gen_entry is not None and gen_entry.decl.is_generator is True
    assert coro_entry is not None and coro_entry.decl.is_generator is False


# ── RT-W025-005: silent-drop contract + warning ──

bad_event_tools = ToolSet()


@bad_event_tools.tool(tier=1, emits=FakeResult)
async def mixed_event_gen_tool() -> AsyncGenerator[Any, None]:
    """Generator tool that yields non-ToolProgressEvent LoopEvent subclasses.

    Contract: only ToolProgressEvent is forwarded downstream; TextEvent,
    NoteEvent, ProgressEvent, etc. are silently dropped with a logger.warning.
    This tool intentionally exercises the drop path (RT-W025-005).
    """
    yield ToolProgressEvent(message="ok progress", tool_name="mixed_event_gen_tool")
    yield TextEvent(text="this should be dropped")         # not forwarded
    yield NoteEvent(note="also dropped")                   # not forwarded
    yield ProgressEvent(message="dropped too")             # not forwarded
    yield FakeResult(value="done")  # terminal result


BAD_EVENT_REGISTRY = ToolRegistry([bad_event_tools], {})


# ── RT-W025-003: empty-generator edge cases ──

no_interim_tools = ToolSet()
empty_gen_tools = ToolSet()


@no_interim_tools.tool(tier=1, emits=FakeResult)
async def no_interim_gen_tool() -> AsyncGenerator[Any, None]:
    """Generator tool that yields only the terminal result — no interim events.

    Edge case: the drain loop in invoke_gen should handle this correctly:
    prev receives the terminal value on the very first iteration, then
    _ToolTerminalResult(value=<FakeResult>) is yielded.
    """
    yield FakeResult(value="direct")  # terminal result only — no interim events


@empty_gen_tools.tool(tier=1, emits=FakeResult)
async def empty_gen_tool() -> AsyncGenerator[Any, None]:
    """Generator tool that yields nothing at all.

    Edge case: the drain loop in invoke_gen never enters the async-for body, so
    prev stays as _SENTINEL → terminal=None → _ToolTerminalResult(value=None).
    The loop sets result=None; isinstance(None, FakeResult) is False so no
    ArtifactEvent is emitted. The loop must not crash.
    """
    # Intentionally yield nothing — this makes it an async generator function
    # (required by the is_generator detection) but produces an empty sequence.
    return
    yield  # noqa: unreachable — required to make this an async generator function


NO_INTERIM_REGISTRY = ToolRegistry([no_interim_tools], {})
EMPTY_GEN_REGISTRY = ToolRegistry([empty_gen_tools], {})


@pytest.mark.asyncio
async def test_non_tool_progress_loop_events_dropped_with_warning(caplog):
    """RT-W025-005: non-ToolProgressEvent LoopEvent subclasses yielded by a
    gen-tool are dropped (not forwarded downstream) and a logger.warning is
    emitted for each one so gen-tool authors can detect routing mistakes.
    """
    model = FakeModelClient().script(
        tool_call("mixed_event_gen_tool", {}),
        reply("finished"),
    )

    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.loop"):
        events = await collect_events(model, BAD_EVENT_REGISTRY)

    # Only the valid ToolProgressEvent is forwarded downstream
    progress = [e for e in events if isinstance(e, ToolProgressEvent)]
    assert len(progress) == 1
    assert progress[0].message == "ok progress"

    # TextEvent / NoteEvent / ProgressEvent from the gen-tool must NOT appear.
    # Note: TextEvent can legitimately appear from the model's reply text ("finished"),
    # so we check by content that the *tool-yielded* values are not present.
    text_events = [e for e in events if isinstance(e, TextEvent)]
    assert not any(e.text == "this should be dropped" for e in text_events), (
        "TextEvent yielded by gen-tool must not be forwarded downstream"
    )
    assert not any(isinstance(e, NoteEvent) for e in events), (
        "NoteEvent yielded by gen-tool must not be forwarded downstream"
    )
    assert not any(isinstance(e, ProgressEvent) for e in events), (
        "ProgressEvent yielded by gen-tool must not be forwarded downstream"
    )

    # A warning must have been emitted for each dropped LoopEvent
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    dropped_names = {r.getMessage() for r in warnings}
    assert any("TextEvent" in msg for msg in dropped_names), (
        "Expected a warning mentioning TextEvent"
    )
    assert any("NoteEvent" in msg for msg in dropped_names), (
        "Expected a warning mentioning NoteEvent"
    )
    assert any("ProgressEvent" in msg for msg in dropped_names), (
        "Expected a warning mentioning ProgressEvent"
    )

    # Terminal artifact still arrives correctly
    artifacts = [e for e in events if isinstance(e, ArtifactEvent)]
    assert len(artifacts) == 1
    assert artifacts[0].model.value == "done"

    # Loop completes successfully despite the unexpected event types
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and done[-1].ok


# ── RT-W025-003: sentinel-logic regression guards ──


@pytest.mark.asyncio
async def test_generator_no_interim_events_yields_terminal_artifact():
    """RT-W025-003: generator that yields ONLY the terminal result (no interim
    ToolProgressEvent items) must not crash and must emit the ArtifactEvent."""
    model = FakeModelClient().script(
        tool_call("no_interim_gen_tool", {}),
        reply("finished"),
    )
    events = await collect_events(model, NO_INTERIM_REGISTRY)

    # No progress events expected
    progress = [e for e in events if isinstance(e, ToolProgressEvent)]
    assert progress == [], f"Expected no ToolProgressEvents, got {progress}"

    # Terminal artifact must still be emitted
    artifacts = [e for e in events if isinstance(e, ArtifactEvent)]
    assert len(artifacts) == 1, f"Expected 1 ArtifactEvent, got {len(artifacts)}"
    assert isinstance(artifacts[0].model, FakeResult)
    assert artifacts[0].model.value == "direct"
    assert artifacts[0].tool_name == "no_interim_gen_tool"

    # ToolResultEvent must be ok
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results and results[0].ok

    # Loop completes successfully
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and done[-1].ok


@pytest.mark.asyncio
async def test_generator_empty_yields_none_result_no_crash():
    """RT-W025-003: generator that yields nothing at all → result=None, no
    ArtifactEvent, no crash. Asserts the sentinel branch behaviour so a
    regression in the _SENTINEL logic would be caught immediately."""
    model = FakeModelClient().script(
        tool_call("empty_gen_tool", {}),
        reply("finished"),
    )
    events = await collect_events(model, EMPTY_GEN_REGISTRY)

    # No progress events
    progress = [e for e in events if isinstance(e, ToolProgressEvent)]
    assert progress == [], f"Expected no ToolProgressEvents, got {progress}"

    # No ArtifactEvent — result is None and isinstance(None, FakeResult) is False
    artifacts = [e for e in events if isinstance(e, ArtifactEvent)]
    assert artifacts == [], (
        "Empty generator produces result=None; no ArtifactEvent should be emitted"
    )

    # ToolResultEvent exists but carries result=None
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results, "Expected a ToolResultEvent even for an empty generator"
    assert results[0].ok, "Empty generator should not mark tool as failed"
    assert results[0].result is None, (
        f"Expected result=None for empty generator, got {results[0].result!r}"
    )

    # Loop completes successfully — no crash
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert done and done[-1].ok
