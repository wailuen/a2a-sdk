"""GH-83 regression guard: acceptance SKILL.md must use scriptPath, not Workflow({name}).

The bug (GH-83): Workflow({name: 'acceptance-api', args: {...}}) silently drops
args inside Claude Code's named-workflow resolver. The fix replaces the name-based
invocation with a scriptPath-based one.

ACs verified for BOTH harness/skills/acceptance/SKILL.md AND
.claude/skills/acceptance/SKILL.md (the seeded agent-repo copy):
  1. The string `Workflow({name: 'acceptance-api'` does NOT appear anywhere in
     the file (old broken form is gone).
  2. The string `scriptPath` DOES appear in the section between
     `### Workflow invocation` and the closing code fence (fix is present).

These two assertions guard against silent regression if someone reverts the fix
or accidentally re-introduces the name-based form in either copy.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD_HARNESS = REPO_ROOT / "harness" / "skills" / "acceptance" / "SKILL.md"
SKILL_MD_CLAUDE = REPO_ROOT / ".claude" / "skills" / "acceptance" / "SKILL.md"


def _read_skill(path: Path) -> str:
    assert path.exists(), f"acceptance SKILL.md not found at {path}"
    return path.read_text()


def _assert_no_workflow_name(path: Path) -> None:
    """GH-83: Workflow({name: 'acceptance-api'}) must not appear — it drops args."""
    content = _read_skill(path)
    assert "Workflow({name: 'acceptance-api'" not in content, (
        f"REGRESSION: {path} contains "
        "Workflow({name: 'acceptance-api'}) which silently drops args (GH-83). "
        "The fix uses scriptPath instead — revert the revert."
    )


def _assert_scriptpath_in_section(path: Path) -> None:
    """GH-83: scriptPath must appear in the ### Workflow invocation section."""
    content = _read_skill(path)

    # Extract the section between "### Workflow invocation" and the next closing ```
    section_header = "### Workflow invocation"
    start = content.find(section_header)
    assert start != -1, (
        f"'### Workflow invocation' section not found in {path}"
    )

    # Find the opening code fence after the section header
    fence_open = content.find("```", start + len(section_header))
    assert fence_open != -1, (
        f"No opening code fence found after '### Workflow invocation' in {path}"
    )

    # Find the closing code fence after the opening one
    fence_close = content.find("```", fence_open + 3)
    assert fence_close != -1, (
        f"No closing code fence found after opening fence in '### Workflow invocation' in {path}"
    )

    section_code = content[fence_open: fence_close + 3]
    assert "scriptPath" in section_code, (
        f"REGRESSION: 'scriptPath' not found in the '### Workflow invocation' code "
        f"block of {path}. GH-83 fix requires "
        "scriptPath-based workflow invocation instead of Workflow({name: ...})."
    )


# --- harness copy ---

def test_no_workflow_name_invocation_harness() -> None:
    """GH-83: harness copy must not use Workflow({name: 'acceptance-api'})."""
    _assert_no_workflow_name(SKILL_MD_HARNESS)


def test_scriptpath_in_workflow_invocation_section_harness() -> None:
    """GH-83: harness copy must have scriptPath in the ### Workflow invocation section."""
    _assert_scriptpath_in_section(SKILL_MD_HARNESS)


# --- .claude (seeded agent-repo) copy ---

def test_no_workflow_name_invocation_claude() -> None:
    """GH-83: .claude copy must not use Workflow({name: 'acceptance-api'})."""
    _assert_no_workflow_name(SKILL_MD_CLAUDE)


def test_scriptpath_in_workflow_invocation_section_claude() -> None:
    """GH-83: .claude copy must have scriptPath in the ### Workflow invocation section."""
    _assert_scriptpath_in_section(SKILL_MD_CLAUDE)
