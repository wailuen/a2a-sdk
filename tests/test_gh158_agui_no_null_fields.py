"""GH-158: AG-UI frames never carry a top-level null; parentMessageId is omitted when absent."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames


def run_body(**extra) -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": "hi"}],
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


def assert_no_top_level_null(frames: list[dict]) -> None:
    for f in frames:
        for key, value in f.items():
            if f["type"] == "CUSTOM" and key == "value":
                continue
            assert value is not None, f"null {key!r} in {f}"


async def test_tool_first_turn_omits_parent_message_id(client, fake_model):
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    frames = await run(client, run_body())
    start = next(f for f in frames if f["type"] == "TOOL_CALL_START")
    assert "parentMessageId" not in start
    assert_no_top_level_null(frames)


async def test_text_then_tool_turn_keeps_parent_message_id(client, fake_model):
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}, text="thinking"), reply("done"))
    frames = await run(client, run_body())
    assert_no_top_level_null(frames)
    text_start = next(f for f in frames if f["type"] == "TEXT_MESSAGE_START")
    start = next(f for f in frames if f["type"] == "TOOL_CALL_START")
    assert start["parentMessageId"] == text_start["messageId"]


async def test_resume_run_has_no_null_fields(client, fake_model):
    fake_model.script(tool_call("publish_note", {"note": "n"}), reply("after resume"))
    first = await run(client, run_body())
    intr = first[-1]["outcome"]["interrupts"][0]
    frames = await run(
        client,
        run_body(
            resume=[{"interrupt_id": intr["id"], "status": "resolved", "payload": {"decision": "approved"}}]
        ),
    )
    start = next(f for f in frames if f["type"] == "TOOL_CALL_START")
    assert "parentMessageId" not in start
    assert_no_top_level_null(first)
    assert_no_top_level_null(frames)


_ROOT = Path(__file__).resolve().parent.parent
_AGUI_SKILL_COPIES = (
    ".claude/skills/ag-ui-check/SKILL.md",
    "harness/skills/ag-ui-check/SKILL.md",
    "template/.claude/skills/ag-ui-check/SKILL.md",
)
_SYNCED_SKILLS = ("ag-ui-check", "new-agent")


def _read_copy(rel: str) -> str:
    p = _ROOT / rel
    if not p.exists():
        pytest.xfail(f"mirror absent: {rel}")
    return p.read_text()


@pytest.mark.parametrize("rel", _AGUI_SKILL_COPIES)
def test_skill_has_no_stale_parent_message_id_trap(rel: str) -> None:
    body = _read_copy(rel)
    assert "Missing `parent_message_id`" not in body
    assert "Missing `parentMessageId`" not in body


def test_agui_skill_claude_and_harness_copies_identical() -> None:
    assert _read_copy(_AGUI_SKILL_COPIES[0]) == _read_copy(_AGUI_SKILL_COPIES[1])


@pytest.mark.parametrize("name", _SYNCED_SKILLS)
def test_harness_skill_matches_template_mirror(name: str) -> None:
    harness = _read_copy(f"harness/skills/{name}/SKILL.md")
    template = _read_copy(f"template/.claude/skills/{name}/SKILL.md")
    assert harness == template
