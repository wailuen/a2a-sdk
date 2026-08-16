"""GH-131: wave-cycle.js's args.today fallback used `new Date()`, but the workflow
sandbox bans Date outright — so the fallback always threw when it fired. It fired
whenever args.today was falsy, including when args itself arrived as a JSON-encoded
string (making `args.today` read as undefined through the object accessor). A launch
with stringified args therefore died in ~5ms with zero agents spawned and an error
pointing at Date instead of naming the actual missing arg.

Fix (both .claude/workflows/wave-cycle.js and harness/workflows/wave-cycle.js):
  - normalize args (`typeof args === 'string' ? JSON.parse(args) : (args || {})`)
    BEFORE reading .waveFile/.today off it
  - remove the `new Date()` fallback entirely
  - fail fast with a clear error naming the missing arg(s) when waveFile/today are
    still absent after normalization

Static text-parse tests — verify the fix textually in both wave-cycle.js copies
without running the workflow engine (mirrors the existing tests/test_workflows.py
pattern, which is itself static-text-only per its own module docstring).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

WAVE_CYCLE_RUNTIME = REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js"
WAVE_CYCLE_HARNESS = REPO_ROOT / "harness" / "workflows" / "wave-cycle.js"
SDK_WAVE = REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"

WAVE_CYCLE_FILES = [WAVE_CYCLE_RUNTIME, WAVE_CYCLE_HARNESS]
WAVE_CYCLE_IDS = ["runtime", "harness"]

# RT-002 (fix wave): GH-131 was ported to sdk-wave.js in the same wave that fixed GH-132
# there — sdk-wave.js is not a byte-identical wave-cycle.js mirror (different path dialect,
# different pytest invocation), so it is excluded from the byte-identical-copies test below
# but included in every generic textual assertion, which only checks for the presence of
# the normalization pattern, not exact file equality.
ALL_ARGS_NORM_FILES = WAVE_CYCLE_FILES + [SDK_WAVE]
ALL_ARGS_NORM_IDS = WAVE_CYCLE_IDS + ["sdk-wave.js"]


def _args_section(text: str) -> str:
    """Everything from the top of the file up to (not including) the WAVE_FILE
    assignment — i.e. the args-handling block this GH-131 fix targets."""
    marker = "const WAVE_FILE ="
    idx = text.index(marker)
    return text[:idx]


@pytest.mark.parametrize("wf_path", ALL_ARGS_NORM_FILES, ids=ALL_ARGS_NORM_IDS)
def test_new_date_fallback_removed(wf_path: Path) -> None:
    text = wf_path.read_text()
    assert "new Date(" not in text, (
        f"{wf_path}: `new Date()` fallback still present — the workflow sandbox bans "
        "Date outright, so this always throws when it fires (GH-131)."
    )


@pytest.mark.parametrize("wf_path", ALL_ARGS_NORM_FILES, ids=ALL_ARGS_NORM_IDS)
def test_args_normalized_before_reading_wavefile_or_today(wf_path: Path) -> None:
    section = _args_section(wf_path.read_text())
    assert "typeof args === 'string'" in section, (
        f"{wf_path}: args must be type-checked for a JSON-encoded string before "
        ".waveFile/.today are read off it (GH-131)."
    )
    assert "JSON.parse(args)" in section, (
        f"{wf_path}: a string-encoded args payload must be JSON.parse()'d, not read "
        "as an object directly (GH-131)."
    )
    assert re.search(r"args\s*\|\|\s*\{\}", section), (
        f"{wf_path}: a missing/falsy args must default to {{}} (not crash on "
        f"`args.waveFile` of undefined) (GH-131)."
    )


@pytest.mark.parametrize("wf_path", ALL_ARGS_NORM_FILES, ids=ALL_ARGS_NORM_IDS)
def test_missing_wavefile_or_today_fails_fast_naming_the_arg(wf_path: Path) -> None:
    section = _args_section(wf_path.read_text())
    assert "'waveFile'" in section, (
        f"{wf_path}: a missing waveFile must be named explicitly in the fail-fast "
        "error, not folded into a generic message (GH-131)."
    )
    assert "'today'" in section, (
        f"{wf_path}: a missing today must be named explicitly in the fail-fast "
        "error, not folded into a generic message (GH-131)."
    )
    assert "throw new Error(" in section, (
        f"{wf_path}: missing waveFile/today must fail fast via a thrown error, not "
        "silently continue with an undefined value (GH-131)."
    )


@pytest.mark.parametrize("wf_path", ALL_ARGS_NORM_FILES, ids=ALL_ARGS_NORM_IDS)
def test_wave_file_and_today_assigned_from_normalized_args(wf_path: Path) -> None:
    text = wf_path.read_text()
    assert "const WAVE_FILE = normalizedArgs.waveFile" in text, (
        f"{wf_path}: WAVE_FILE must be assigned from the normalized args object, not "
        "the raw `args` parameter directly (GH-131)."
    )
    assert "const TODAY     = normalizedArgs.today" in text or "const TODAY = normalizedArgs.today" in text, (
        f"{wf_path}: TODAY must be assigned from the normalized args object, not the "
        "raw `args` parameter directly (GH-131)."
    )


@pytest.mark.parametrize("wf_path", ALL_ARGS_NORM_FILES, ids=ALL_ARGS_NORM_IDS)
def test_fail_fast_check_precedes_wave_file_assignment(wf_path: Path) -> None:
    text = wf_path.read_text()
    normalize_idx = text.index("normalizedArgs")
    throw_idx = text.index("throw new Error(")
    wave_file_idx = text.index("const WAVE_FILE = normalizedArgs.waveFile")
    assert normalize_idx < throw_idx < wave_file_idx, (
        f"{wf_path}: args must be normalized, THEN validated (fail fast), THEN "
        "WAVE_FILE/TODAY assigned — in that order (GH-131)."
    )


def test_runtime_and_harness_copies_stay_identical() -> None:
    assert WAVE_CYCLE_RUNTIME.read_text() == WAVE_CYCLE_HARNESS.read_text(), (
        "wave-cycle.js copies diverged — the GH-131 fix must land identically in "
        ".claude/workflows/wave-cycle.js and harness/workflows/wave-cycle.js "
        "(tests/test_workflow_sync.py enforces this generally; pinned here too since "
        "this is the exact section GH-131 touches)."
    )
