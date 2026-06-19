"""GH-84: Static conformance tests for the archive-blocking behavior in wave-cycle.js
and sdk-wave.js.

Expected GH-84 blocking behavior:
  - ARCHIVE_INTENT_SCHEMA requires offendingHarnessPaths in addition to offendingPaths.
  - The dual blocking condition `(offendingPaths || offendingHarnessPaths)` blocks archive
    when either list is non-empty. This means dirty/untracked files under harness deliverable
    directories (tests/, workspace/learning/, workspace/scenarios/results/, workspace/prd/)
    will also block archive, even if those paths are not in the wave's allScope.
  - The archiveIntent agent prompt (step 4) instructs the agent to populate
    offendingHarnessPaths for paths starting with these four harness directories.

These are static text-parse tests — they verify the schema and prompt text without
running the workflow engine.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

# The two workflow files that implement GH-84 archive blocking
WAVE_CYCLE_RUNTIME = REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js"
SDK_WAVE = REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"

# The four harness deliverable directories checked by GH-84
HARNESS_DIRS = ["tests/", "workspace/learning/", "workspace/scenarios/results/", "workspace/prd/"]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    assert path.exists(), f"Workflow file not found: {path}"
    return path.read_text()


# ---------------------------------------------------------------------------
# Schema field presence: offendingHarnessPaths in ARCHIVE_INTENT_SCHEMA
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_archive_intent_schema_has_offending_harness_paths_in_required(wf_path: Path) -> None:
    """GH-84: ARCHIVE_INTENT_SCHEMA required array must include 'offendingHarnessPaths'.

    Without this field in the schema the agent is not constrained to return it,
    and the blocking condition silently skips harness-path checking.
    """
    content = _read(wf_path)
    # Find the ARCHIVE_INTENT_SCHEMA block and assert the field appears in required
    schema_match = re.search(
        r"const ARCHIVE_INTENT_SCHEMA\s*=\s*\{.*?required:\s*\[([^\]]*)\]",
        content,
        re.DOTALL,
    )
    assert schema_match, (
        f"{wf_path.name}: ARCHIVE_INTENT_SCHEMA not found or has no 'required' array"
    )
    required_array = schema_match.group(1)
    assert "offendingHarnessPaths" in required_array, (
        f"{wf_path.name}: 'offendingHarnessPaths' is missing from "
        f"ARCHIVE_INTENT_SCHEMA.required — GH-84 blocking will silently not work. "
        f"Required array found: {required_array!r}"
    )


@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_archive_intent_schema_has_offending_harness_paths_in_properties(wf_path: Path) -> None:
    """GH-84: ARCHIVE_INTENT_SCHEMA properties must define 'offendingHarnessPaths'."""
    content = _read(wf_path)
    assert "offendingHarnessPaths" in content, (
        f"{wf_path.name}: 'offendingHarnessPaths' does not appear anywhere — "
        "GH-84 schema and blocking logic are both missing"
    )
    # Check it appears in a property definition (after 'offendingPaths:' entry)
    # Simple heuristic: the field must appear at least twice (required[] and properties{})
    occurrences = content.count("offendingHarnessPaths")
    assert occurrences >= 2, (
        f"{wf_path.name}: 'offendingHarnessPaths' appears only {occurrences} time(s) — "
        "expected at least 2 (required array + properties definition). "
        "GH-84 schema may be incomplete."
    )


# ---------------------------------------------------------------------------
# Agent prompt: step 4 instructs agent to populate offendingHarnessPaths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_archive_intent_prompt_contains_harness_dirs(wf_path: Path) -> None:
    """GH-84: archiveIntent agent prompt must instruct the agent to check the four
    harness deliverable directories and populate offendingHarnessPaths.
    """
    content = _read(wf_path)
    for harness_dir in HARNESS_DIRS:
        assert harness_dir in content, (
            f"{wf_path.name}: harness directory '{harness_dir}' not found in the "
            f"archiveIntent agent prompt — step 4 (collect offendingHarnessPaths) is "
            f"missing or incomplete. GH-84 will not detect uncommitted harness deliverables."
        )


# ---------------------------------------------------------------------------
# Dual blocking condition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_dual_blocking_condition_present(wf_path: Path) -> None:
    """GH-84: the archive blocking condition must check BOTH offendingPaths and
    offendingHarnessPaths. A single-field check silently misses harness deliverables.
    """
    content = _read(wf_path)
    # The dual condition appears as: offendingPaths ... offendingHarnessPaths
    # within the same if-expression. Check both names appear near each other in an
    # elif/else-if block (within 300 chars of each other after 'archiveIntent').
    archive_intent_idx = content.find("archiveIntent.offendingPaths")
    assert archive_intent_idx != -1, (
        f"{wf_path.name}: 'archiveIntent.offendingPaths' not found — "
        "archive blocking condition is missing"
    )
    window = content[archive_intent_idx: archive_intent_idx + 300]
    assert "offendingHarnessPaths" in window, (
        f"{wf_path.name}: 'offendingHarnessPaths' not found within 300 chars of "
        f"'archiveIntent.offendingPaths' — dual blocking condition is missing or split. "
        f"Window: {window!r}"
    )
