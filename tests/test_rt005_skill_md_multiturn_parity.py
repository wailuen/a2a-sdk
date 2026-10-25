"""RT-005: the multi-turn A2A contract in `acceptance/SKILL.md` must stay at
parity across all three tracked copies — `harness/skills/acceptance/SKILL.md`
(authoring source), `.claude/skills/acceptance/SKILL.md` (this repo's own
executing copy), and `template/.claude/skills/acceptance/SKILL.md` (the peer
`wailuen/a2a-agent-template` runtime copy downstream agents execute,
LRN-071/LRN-085).

LRN-103 fixed the harness copy to split turns 2-N on the prior task's state
(interrupted -> send `taskId`; terminal -> send `contextId` with no
`taskId`, else the server 400s with -32004 per GH-144). Editing only the
authoring source left the two copies this repo and downstream agents
actually EXECUTE still teaching the pre-fix, single-branch instruction
("always send taskId") — which fails on turn 2+ of every multi-turn run
once GH-144 lands. This module pins all three copies at parity on that
paragraph so a future edit to one can never silently leave the others stale
again.
"""

from __future__ import annotations

from pathlib import Path

import agent_sdk.app as _app_module

_START_MARKER = "**Multi-turn A2A:**"
_END_MARKER = "### AG-UI transport"


def _repo_root() -> Path:
    return Path(_app_module.__file__).parent.parent


def _multiturn_section(text: str) -> str:
    start = text.find(_START_MARKER)
    end = text.find(_END_MARKER)
    assert start != -1, f"{_START_MARKER!r} not found"
    assert end != -1 and end > start, f"{_END_MARKER!r} not found after the multi-turn marker"
    return text[start:end]


def _skill_paths() -> dict[str, Path]:
    root = _repo_root()
    return {
        "harness": root / "harness" / "skills" / "acceptance" / "SKILL.md",
        "dot_claude": root / ".claude" / "skills" / "acceptance" / "SKILL.md",
        "template": root / "template" / ".claude" / "skills" / "acceptance" / "SKILL.md",
    }


def test_harness_copy_states_the_completed_vs_interrupted_split() -> None:
    """Pins the FIXED contract itself, not just cross-copy parity — guards
    against all three copies drifting back to the pre-LRN-103 instruction
    together."""
    paths = _skill_paths()
    section = _multiturn_section(paths["harness"].read_text())

    assert "input-required" in section and "auth-required" in section, (
        "must distinguish the non-terminal interrupt states that resume via taskId"
    )
    assert "no `taskId`" in section, (
        "the terminal branch must explicitly send contextId with NO taskId"
    )
    assert "-32004" in section, (
        "must explain why: re-addressing a terminal task via taskId returns 400/-32004"
    )


def test_dot_claude_copy_matches_harness_source() -> None:
    paths = _skill_paths()
    harness_section = _multiturn_section(paths["harness"].read_text())
    dot_claude_section = _multiturn_section(paths["dot_claude"].read_text())
    assert dot_claude_section == harness_section, (
        ".claude/skills/acceptance/SKILL.md (the copy this repo actually "
        "executes) has drifted from harness/skills/acceptance/SKILL.md's "
        "multi-turn A2A contract"
    )


def test_template_copy_matches_harness_source() -> None:
    paths = _skill_paths()
    if not paths["template"].exists():
        return  # template/ is a separate, gitignored nested repo (LRN-071)
    harness_section = _multiturn_section(paths["harness"].read_text())
    template_section = _multiturn_section(paths["template"].read_text())
    assert template_section == harness_section, (
        "template/.claude/skills/acceptance/SKILL.md (the peer "
        "wailuen/a2a-agent-template runtime copy downstream agents execute) "
        "has drifted from harness/skills/acceptance/SKILL.md's multi-turn "
        "A2A contract"
    )
