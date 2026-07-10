"""SI-2 coverage: unknown-skill errors must never leak the raw caller-supplied
``load_skill`` name onto the wire (GH-99).

The unknown-*tool* branch in ``loop.py`` truncates + strips control chars
from the model-supplied name before folding it into ``ToolResultEvent.error``
(loop.py:392-393). The unknown-*skill* branch (loop.py:372) never adopted the
same treatment, so a crafted ``load_skill`` argument reaches both the A2A
``ToolResultEvent.error`` and, downstream, the AG-UI ``TOOL_CALL_RESULT`` SSE
frame verbatim.
"""

from __future__ import annotations

from pathlib import Path

from agent_sdk.agent.events import DoneEvent, ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.skills import SkillsRegistry
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import sse_frames

# Exercises a control char from every class the sanitizer must strip: C0
# (NUL 0x00, BEL 0x07, ESC 0x1b), DEL (0x7f) and C1 (CSI 0x9b — a single-byte
# ANSI escape introducer). Each survives repr() as its \xNN escape, so an
# unsanitized name would surface the literal escape in the wire/error string.
CRAFTED_SKILL_NAME = "evil\x00\x07\x1b[31m\x7f\x9b-skill" + "X" * 200
LONG_PAYLOAD_RUN = "X" * 200
ESCAPED_ESC_SEQUENCE = r"\x1b"
ESCAPED_NUL_SEQUENCE = r"\x00"
ESCAPED_DEL_SEQUENCE = r"\x7f"
ESCAPED_C1_SEQUENCE = r"\x9b"

EMPTY_TOOLS = ToolSet()
EMPTY_REGISTRY = ToolRegistry([EMPTY_TOOLS], {})


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


async def run_ag_ui(client, body) -> list[dict]:
    r = await client.post("/ag-ui/run", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return sse_frames(r.text)


class TestUnknownSkillSI2SurfaceCoverage:
    async def test_agui_stream_leaks_unknown_skill_name_sdk_candidate(
        self, client, fake_model
    ):
        fake_model.script(
            tool_call("load_skill", {"name": CRAFTED_SKILL_NAME}), reply("done")
        )
        frames = await run_ag_ui(client, run_body())

        result_frame = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")
        content = result_frame["content"]

        assert CRAFTED_SKILL_NAME not in content
        assert LONG_PAYLOAD_RUN not in content, "unsanitized long payload reached the wire"
        assert ESCAPED_ESC_SEQUENCE not in content, "raw control char reached the wire"
        assert ESCAPED_NUL_SEQUENCE not in content, "raw control char reached the wire"
        assert ESCAPED_DEL_SEQUENCE not in content, "raw DEL (0x7f) reached the wire"
        assert ESCAPED_C1_SEQUENCE not in content, "raw C1 (0x9b) control char reached the wire"
        assert len(content) < 120

    async def test_run_loop_unknown_skill_error_is_sanitized(self):
        skills = SkillsRegistry(Path("/nonexistent/no-such-skills-dir"))
        model = FakeModelClient(
            [tool_call("load_skill", {"name": CRAFTED_SKILL_NAME}), reply("ok")]
        )
        events = []
        async for ev in run_loop(
            model=model,
            registry=EMPTY_REGISTRY,
            adapters={},
            system="test",
            messages=[{"role": "user", "content": [{"text": "go"}]}],
            skills=skills,
        ):
            events.append(ev)

        assert isinstance(events[-1], DoneEvent) and events[-1].ok
        failed = [e for e in events if isinstance(e, ToolResultEvent) and not e.ok]
        assert failed, "expected the unknown-skill call to fail"
        error = failed[0].error
        assert error is not None

        assert CRAFTED_SKILL_NAME not in error
        assert LONG_PAYLOAD_RUN not in error, "unsanitized long payload reached ToolResultEvent.error"
        assert ESCAPED_ESC_SEQUENCE not in error, "raw control char reached ToolResultEvent.error"
        assert ESCAPED_NUL_SEQUENCE not in error, "raw control char reached ToolResultEvent.error"
        assert ESCAPED_DEL_SEQUENCE not in error, "raw DEL (0x7f) reached ToolResultEvent.error"
        assert ESCAPED_C1_SEQUENCE not in error, "raw C1 (0x9b) reached ToolResultEvent.error"
        assert len(error) < 120
