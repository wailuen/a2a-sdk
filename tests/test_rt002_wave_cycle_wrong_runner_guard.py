"""RT-002 (redteam finding on .claude/skills/wave/SKILL.md, GH-136 wave): wave-cycle.js's
protocol-surface arrays (AUTH_SURFACE, A2A_SURFACE, MCP_SURFACE, AGUI_SURFACE, A2UI_SURFACE) are
hardcoded to `src/`-prefixed paths. Run against the a2a-sdk repo's own source tree — which lives
under `agent_sdk/`, not `src/` — every one of those arrays evaluates false for every touched path,
so `runProtocol` is always false and the entire Protocol Audit phase is skipped silently, with no
log line naming the mismatch.

The root cause traced to a self-contradictory instruction in .claude/skills/wave/SKILL.md: Mode A
step 2 correctly launches `sdk-wave.js` (the SDK-context runner, whose surfaces are `agent_sdk/`-
prefixed) for this repo, but Mode B (single-wave / resumption — the mode a redteam-triggered rerun
actually takes) said "Launch `wave-cycle.js` as in Mode A step 2", silently launching the wrong
runner. That doc bug is fixed separately; this module pins the defensive code-level guard requested
alongside it: wave-cycle.js's Parse phase must abort, before any wave-file parsing or downstream
work, when the repo root has an `agent_sdk/` package but no `src/` directory — the exact layout
that makes its protocol-surface arrays permanently unmatchable. This is a wave-cycle.js-only fix:
sdk-wave.js is the intended runner for that layout and must not gain a mirrored guard that would
abort on the condition it exists to handle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

WAVE_CYCLE_RUNTIME = REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js"
WAVE_CYCLE_HARNESS = REPO_ROOT / "harness" / "workflows" / "wave-cycle.js"

# Only the copies present in this checkout (template/ is a gitignored peer repo per LRN-071 and
# may be absent locally — test_workflow_sync.py owns keeping it in sync when present).
WAVE_CYCLE_FILES = [p for p in [WAVE_CYCLE_RUNTIME, WAVE_CYCLE_HARNESS] if p.exists()]
WAVE_CYCLE_IDS = [
    "wave-cycle.js(runtime)" if p == WAVE_CYCLE_RUNTIME else "wave-cycle.js(harness)"
    for p in WAVE_CYCLE_FILES
]


def _read(path: Path) -> str:
    assert path.exists(), f"Workflow file not found: {path}"
    return path.read_text()


def _section(content: str, start_marker: str, end_marker: str, wf_path: Path) -> str:
    start = content.find(start_marker)
    assert start != -1, f"{wf_path.name}: could not locate section marker {start_marker!r}."
    end = content.find(end_marker, start + len(start_marker))
    assert end != -1 and end > start, (
        f"{wf_path.name}: could not locate section marker {end_marker!r} after {start_marker!r}."
    )
    return content[start:end]


def _parse_phase_section(content: str, wf_path: Path) -> str:
    return _section(
        content, "// ─── phase 0: parse wave file", "// ─── phase 1", wf_path
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_repo_layout_check_schema_defined(wf_path: Path) -> None:
    content = _read(wf_path)
    assert "REPO_LAYOUT_CHECK_SCHEMA" in content, (
        f"{wf_path.name}: REPO_LAYOUT_CHECK_SCHEMA not found — the repo-layout gate schema "
        "is missing."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_repo_layout_check_schema_requires_wrong_runner_field(wf_path: Path) -> None:
    content = _read(wf_path)
    start = content.find("const REPO_LAYOUT_CHECK_SCHEMA")
    assert start != -1, f"{wf_path.name}: REPO_LAYOUT_CHECK_SCHEMA declaration not found."
    end = content.find("\n}", start)
    schema_block = content[start:end]
    assert "wrongRunnerForRepoLayout" in schema_block, (
        f"{wf_path.name}: REPO_LAYOUT_CHECK_SCHEMA must define a wrongRunnerForRepoLayout field."
    )
    assert "required" in schema_block and "wrongRunnerForRepoLayout" in schema_block.split(
        "required", 1
    )[1].split("]", 1)[0], (
        f"{wf_path.name}: wrongRunnerForRepoLayout must be in REPO_LAYOUT_CHECK_SCHEMA.required."
    )


# ---------------------------------------------------------------------------
# Gate placement and mechanism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_repo_layout_gate_checks_agent_sdk_without_src(wf_path: Path) -> None:
    parse_section = _parse_phase_section(_read(wf_path), wf_path)
    assert "test -d agent_sdk" in parse_section and "! test -d src" in parse_section, (
        f"{wf_path.name}: Parse phase must shell-check for an agent_sdk/ package with no "
        "src/ directory — the layout that makes the src/-prefixed protocol-surface arrays "
        "permanently unmatchable."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_repo_layout_gate_runs_before_wave_file_parse(wf_path: Path) -> None:
    """The repo-layout check is independent of wave-file content — it must run first, so a wave
    launched with the wrong runner fails before any wave-parsing or implementation work starts.
    """
    content = _read(wf_path)
    gate_idx = content.find("label: 'gate:repo-layout-check'")
    parse_idx = content.find("label: 'parse'")
    assert gate_idx != -1, f"{wf_path.name}: repo-layout gate call site not found."
    assert parse_idx != -1, f"{wf_path.name}: wave-file parse call site not found."
    assert gate_idx < parse_idx, (
        f"{wf_path.name}: the repo-layout gate must run BEFORE the wave-file parse call, not "
        "after — it does not depend on wave content and should fail fast."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_repo_layout_gate_fails_closed_on_null_or_true(wf_path: Path) -> None:
    """House convention (RT-001/WC-001, used throughout this file): a null agent response is
    unknown state and must be treated as failure, not silently allowed to proceed."""
    parse_section = _parse_phase_section(_read(wf_path), wf_path)
    idx = parse_section.find("repoLayoutCheck")
    assert idx != -1, f"{wf_path.name}: repoLayoutCheck result variable not found."
    guard = parse_section[idx : idx + 400]
    assert "!repoLayoutCheck" in guard or "repoLayoutCheck === null" in guard, (
        f"{wf_path.name}: repo-layout gate must fail-closed on a null response."
    )
    assert "wrongRunnerForRepoLayout" in guard, (
        f"{wf_path.name}: repo-layout gate must check wrongRunnerForRepoLayout."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_repo_layout_gate_abort_message_names_sdk_wave(wf_path: Path) -> None:
    parse_section = _parse_phase_section(_read(wf_path), wf_path)
    idx = parse_section.find("wrongRunnerForRepoLayout")
    abort_block = parse_section[idx : idx + 1200]
    assert "sdk-wave.js" in abort_block, (
        f"{wf_path.name}: the abort message must name sdk-wave.js as the correct runner for "
        "this repo layout."
    )
    assert ".claude/skills/wave/SKILL.md" in abort_block, (
        f"{wf_path.name}: the abort message must point at .claude/skills/wave/SKILL.md, which "
        "launches sdk-wave.js for this repo."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_repo_layout_gate_returns_error_on_abort(wf_path: Path) -> None:
    parse_section = _parse_phase_section(_read(wf_path), wf_path)
    idx = parse_section.find("wrongRunnerForRepoLayout")
    abort_block = parse_section[idx : idx + 1200]
    assert "return { error:" in abort_block, (
        f"{wf_path.name}: the repo-layout gate must return a structured error on abort, "
        "matching every other Parse-phase abort in this file."
    )


# ---------------------------------------------------------------------------
# sdk-wave.js must NOT gain a mirrored guard — it is the correct runner for the
# agent_sdk/-without-src/ layout and must not abort on the condition it exists to handle.
# ---------------------------------------------------------------------------


def test_sdk_wave_js_has_no_wrong_runner_guard() -> None:
    sdk_wave = REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"
    if not sdk_wave.exists():
        pytest.skip("sdk-wave.js not present in this checkout")
    content = sdk_wave.read_text()
    assert "REPO_LAYOUT_CHECK_SCHEMA" not in content, (
        "sdk-wave.js must not gain the wave-cycle.js-only wrong-runner guard — sdk-wave.js is "
        "the intended runner for an agent_sdk/-without-src/ repo layout."
    )
