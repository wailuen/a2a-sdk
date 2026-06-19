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


def _assert_scriptpath_uses_layout(path: Path, expected_subpath: str) -> None:
    """Two-path model: harness copy uses harness/workflows/..., .claude copy uses .claude/workflows/...

    The two SKILL.md copies must NOT be identical: each must reference the workflow
    script at the path that matches its deployment layout.
    """
    content = _read_skill(path)

    section_header = "### Workflow invocation"
    start = content.find(section_header)
    assert start != -1, f"'### Workflow invocation' section not found in {path}"

    fence_open = content.find("```", start + len(section_header))
    assert fence_open != -1, f"No opening code fence found after '### Workflow invocation' in {path}"

    fence_close = content.find("```", fence_open + 3)
    assert fence_close != -1, f"No closing code fence found in '### Workflow invocation' in {path}"

    section_code = content[fence_open: fence_close + 3]
    assert expected_subpath in section_code, (
        f"scriptPath in {path} must contain '{expected_subpath}' "
        f"(two-path model: harness copy → harness/workflows/acceptance-api.js; "
        f".claude copy → .claude/workflows/acceptance-api.js). "
        f"The active Workflow() call does not match the expected layout for this copy."
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


# --- path existence check ---

def test_scriptpath_target_exists_harness() -> None:
    """The scriptPath target in the harness copy must actually exist on disk.

    This catches path typos that would pass the string-presence checks above
    but fail at runtime with a file-not-found error when /acceptance is invoked.

    Two-path model:
    - harness copy (harness/skills/acceptance/SKILL.md): uses harness/workflows/acceptance-api.js
      — this file lives in the SDK repo and can be existence-checked here.
    - .claude copy (.claude/skills/acceptance/SKILL.md): uses .claude/workflows/acceptance-api.js
      — this path resolves inside seeded agent repos (not in the SDK repo itself),
      so we cannot existence-check it here. The two-layout test below guards the path string.
    """
    target = REPO_ROOT / "harness" / "workflows" / "acceptance-api.js"
    assert target.exists(), (
        f"acceptance-api.js not found at {target}. "
        "The harness/skills/acceptance/SKILL.md scriptPath points to this file — "
        "either the file was moved/deleted or the path in SKILL.md is wrong."
    )


# --- two-path model: each copy must use its own layout-specific scriptPath ---

def test_harness_copy_uses_harness_workflow_path() -> None:
    """harness copy must use harness/workflows/acceptance-api.js (SDK repo layout)."""
    _assert_scriptpath_uses_layout(SKILL_MD_HARNESS, "harness/workflows/acceptance-api.js")


def test_claude_copy_uses_claude_workflow_path() -> None:
    """.claude copy must use .claude/workflows/acceptance-api.js (seeded agent-repo layout).

    This guards against the regression where the .claude copy incorrectly references
    harness/workflows/acceptance-api.js, which does not exist in seeded agent repos
    and causes a file-not-found error when /acceptance is invoked from an agent repo.
    """
    _assert_scriptpath_uses_layout(SKILL_MD_CLAUDE, ".claude/workflows/acceptance-api.js")
