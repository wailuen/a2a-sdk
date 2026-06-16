"""AG-UI resume: synthetic TOOL_CALL_START/END lifecycle on resumed stream.

When a run is interrupted mid-tool-call and then resumed, the new SSE stream
must not emit an orphan TOOL_CALL_RESULT. The _RunMapper detects that the
START event was never emitted in the current stream (resume path) and injects
synthetic TOOL_CALL_START + TOOL_CALL_END before the TOOL_CALL_RESULT.
"""

from __future__ import annotations

import pytest

from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames


def run_body(text: str = "hello", **extra) -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


async def run(client, body) -> list[dict]:
    r = await client.post("/ag-ui/run", json=body)
    assert r.status_code == 200, r.text
    return sse_frames(r.text)


async def test_resume_emits_synthetic_tool_lifecycle(client, fake_model):
    """Resume stream must include TOOL_CALL_START → TOOL_CALL_END before
    TOOL_CALL_RESULT even though the START/ARGS/END occurred in the prior
    interrupted stream."""
    # First run: triggers an interrupt mid tool-call
    fake_model.script(tool_call("publish_note", {"note": "n"}), reply("after resume"))
    frames = await run(client, run_body("publish"))
    assert frames[-1]["type"] == "RUN_FINISHED"
    outcome = frames[-1]["outcome"]
    assert outcome["type"] == "interrupt"
    intr = outcome["interrupts"][0]
    interrupt_id = intr["id"]
    interrupted_tool_call_id = intr["toolCallId"]

    # Resume run: the tool result arrives in a NEW stream
    resume_frames = await run(
        client,
        run_body(
            resume=[
                {"interrupt_id": interrupt_id, "status": "resolved", "payload": {"decision": "approved"}}
            ]
        ),
    )
    types = [f["type"] for f in resume_frames]

    # Basic run shape
    assert types[0] == "RUN_STARTED"
    assert types[1] == "STATE_SNAPSHOT"
    assert types[-1] == "RUN_FINISHED"

    # The resumed stream MUST contain synthetic lifecycle frames before the result
    assert "TOOL_CALL_START" in types, f"Missing TOOL_CALL_START in resume stream: {types}"
    assert "TOOL_CALL_END" in types, f"Missing TOOL_CALL_END in resume stream: {types}"
    assert "TOOL_CALL_RESULT" in types, f"Missing TOOL_CALL_RESULT in resume stream: {types}"

    # Ordering: TOOL_CALL_START must precede TOOL_CALL_END which must precede TOOL_CALL_RESULT
    idx_start = types.index("TOOL_CALL_START")
    idx_end = types.index("TOOL_CALL_END")
    idx_result = types.index("TOOL_CALL_RESULT")
    assert idx_start < idx_end < idx_result, (
        f"Expected TOOL_CALL_START < TOOL_CALL_END < TOOL_CALL_RESULT, "
        f"got indices {idx_start}, {idx_end}, {idx_result}"
    )

    # toolCallId must be consistent across the synthetic frames and the result
    start_frame = next(f for f in resume_frames if f["type"] == "TOOL_CALL_START")
    end_frame = next(f for f in resume_frames if f["type"] == "TOOL_CALL_END")
    result_frame = next(f for f in resume_frames if f["type"] == "TOOL_CALL_RESULT")

    assert start_frame["toolCallId"] == interrupted_tool_call_id
    assert end_frame["toolCallId"] == interrupted_tool_call_id
    assert result_frame["toolCallId"] == interrupted_tool_call_id

    # TOOL_CALL_RESULT messageId must be a fresh UUID, never the toolCallId
    assert result_frame["messageId"] != interrupted_tool_call_id

    # The synthetic START must carry toolCallName
    assert "toolCallName" in start_frame

    # Post-resume text response still arrives
    assert "TEXT_MESSAGE_CONTENT" in types


async def test_normal_run_no_duplicate_tool_lifecycle(client, fake_model):
    """On a normal (non-resume) run the TOOL_CALL_START must appear exactly
    once — the synthetic injection must NOT fire when START was already emitted
    in the current stream."""
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    frames = await run(client, run_body("kpis"))
    types = [f["type"] for f in frames]

    # Exactly one TOOL_CALL_START and one TOOL_CALL_END
    assert types.count("TOOL_CALL_START") == 1, types
    assert types.count("TOOL_CALL_END") == 1, types
    assert types.count("TOOL_CALL_RESULT") == 1, types

    # TOOL_CALL_ARGS must exist (real path only, not synthetic)
    assert "TOOL_CALL_ARGS" in types, types
