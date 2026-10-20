"""Regression coverage for a redteam pass on .claude/workflows/wave-cycle.js (and its
byte-identical harness/workflows/ mirror, enforced separately by test_workflow_sync.py):

RT-003 (phase redteam round-8 budget exit): the break previously fired a bare log() — no
deferred note, no codify capture of surviving critical/high findings, and no blocking flag —
so the wave would archive as if clean even though the GH-132 severity floor means reaching
the round cap now signals SURVIVING critical/high findings. Fix: codify capture moved before
the break, a deferred note is written, and phaseBudgetBlocked (folded into protocolBlocked)
stops archive.

RT-004 (unit redteam round-5 budget exit): the deferred note was already written, but codify
capture happened AFTER the break (unreachable) and no blocking flag was set, so a group could
exit round 5 with unresolved critical/high findings and the wave would still archive. Fix:
codify capture moved before the break, and unitBudgetBlocked (folded into protocolBlocked)
stops archive.

RT-016 (findingsCount cross-validation): the old two-special-case guard (findingsCount===0
with a non-empty array; findingsCount>0 with an empty array) missed PARTIAL mismatches (e.g.
findingsCount=5, findings=[<1 item>]), which passed both checks untouched while `blocking`
(derived from rt.findings only) silently dropped the other findings. Fix: a single inequality
check (findingsCount !== findings.length) replaces both special cases, fail-closed.

RT-006 (AGENT_CALL_BUDGET default): a flat 150-call ceiling was documented (in the file's own
comment) as already below the honest cost of a routine 4-group wave. Fix: the ceiling is
recomputed once wave.groups.length is known, scaling with group count; an explicit
args.agentBudget of exactly 0 is now rejected instead of silently falling back to the default.

RT-017 (args JSON.parse): a string args payload that is not valid JSON died with a bare,
unattributed SyntaxError — the same unactionable failure mode GH-131 set out to remove, one
layer up. Fix: the parse is wrapped in try/catch and rethrown with a clear, attributed message.

RT-018 (MAX_LRN_PER_WAVE cap): findings beyond the per-wave LRN capture cap were dropped with
only a transient log() line, losing them permanently. Fix: a deferred note captures the
overflow findings, mirroring every other truncation/budget path in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

WAVE_CYCLE_RUNTIME = REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js"
WAVE_CYCLE_HARNESS = REPO_ROOT / "harness" / "workflows" / "wave-cycle.js"

# Only the two wave-cycle.js copies present in this checkout (template/ is a gitignored peer
# repo per LRN-071 and may be absent locally — test_workflow_sync.py owns keeping it in sync
# when present). sdk-wave.js is intentionally NOT included: these fixes were scoped to
# wave-cycle.js only.
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


def _unit_redteam_section(content: str, wf_path: Path) -> str:
    return _section(
        content, "// ─── phase 3: unit redteam", "// ─── phase 4: phase redteam", wf_path
    )


def _phase_redteam_section(content: str, wf_path: Path) -> str:
    return _section(
        content, "// ─── phase 4: phase redteam", "// ─── phase 5: protocol audit", wf_path
    )


def _codify_section(content: str, wf_path: Path) -> str:
    return _section(content, "// ─── phase 6: codify", "// ─── phase 7: archive", wf_path)


def _args_section(content: str, wf_path: Path) -> str:
    return _section(content, "// ─── args ", "// ─── protocol surface paths", wf_path)


# ---------------------------------------------------------------------------
# RT-017: args JSON.parse fails loudly and attributably on invalid JSON.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_rt017_args_json_parse_wrapped_in_try_catch(wf_path: Path) -> None:
    args_section = _args_section(_read(wf_path), wf_path)
    assert "try {" in args_section and "JSON.parse(args)" in args_section, (
        f"{wf_path.name}: args normalization no longer wraps JSON.parse(args)."
    )
    try_idx = args_section.find("try {")
    parse_idx = args_section.find("JSON.parse(args)")
    catch_idx = args_section.find("} catch", parse_idx)
    assert -1 < try_idx < parse_idx < catch_idx, (
        f"{wf_path.name}: JSON.parse(args) must sit inside a try/catch block, not a bare, "
        "unguarded call — an invalid-JSON string payload must not throw a raw SyntaxError."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_rt017_json_parse_catch_rethrows_attributed_error(wf_path: Path) -> None:
    args_section = _args_section(_read(wf_path), wf_path)
    catch_idx = args_section.find("} catch")
    assert catch_idx != -1, f"{wf_path.name}: no catch block found after JSON.parse(args)."
    catch_block = args_section[catch_idx : catch_idx + 400]
    assert "wave-cycle:" in catch_block and "not valid JSON" in catch_block, (
        f"{wf_path.name}: the JSON.parse catch block must rethrow an attributed error naming "
        "'wave-cycle:' and explaining the payload is not valid JSON — a bare re-throw or a "
        "generic message reproduces the exact unactionable failure mode GH-131 removed, one "
        "layer up."
    )


# ---------------------------------------------------------------------------
# RT-006: AGENT_CALL_BUDGET scales with wave.groups.length; agentBudget: 0 is rejected.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_rt006_agent_call_budget_is_mutable_for_recompute(wf_path: Path) -> None:
    content = _read(wf_path)
    assert "let AGENT_CALL_BUDGET" in content, (
        f"{wf_path.name}: AGENT_CALL_BUDGET must be declared with `let`, not `const` — it is "
        "recomputed once wave.groups.length is known."
    )
    assert "const AGENT_CALL_BUDGET" not in content, (
        f"{wf_path.name}: AGENT_CALL_BUDGET must not also be declared `const` anywhere — that "
        "would collide with the `let` declaration or indicate the recompute site is missing."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_rt011_explicit_zero_agent_budget_rejected_via_consolidated_guard(wf_path: Path) -> None:
    """RT-011 (fix round): the dedicated agentBudget===0 guard was fully redundant with
    the finite/positive guard immediately below it (0 fails `> 0` too) and has been
    folded away — the standalone `=== 0` check must no longer appear anywhere in the
    file, and the single remaining guard must still reject an explicit 0 override."""
    content = _read(wf_path)
    assert "Number(normalizedArgs.agentBudget) === 0" not in content, (
        f"{wf_path.name}: the redundant standalone agentBudget===0 guard should have been "
        "removed — it is fully subsumed by the Number.isFinite(...) && ... > 0 guard."
    )
    finite_check_idx = content.find(
        "!(Number.isFinite(Number(normalizedArgs.agentBudget)) && "
        "Number(normalizedArgs.agentBudget) > 0)"
    )
    assert finite_check_idx != -1, (
        f"{wf_path.name}: the consolidated finite/positive agentBudget guard is missing — "
        "an explicit override of 0 would no longer be rejected at all."
    )
    throw_idx = content.find("throw new Error(", finite_check_idx)
    assert -1 < finite_check_idx < throw_idx < finite_check_idx + 400, (
        f"{wf_path.name}: the consolidated guard must throw, not just log — an invalid "
        "override should fail fast like the missing-args check above it."
    )


# ---------------------------------------------------------------------------
# RT-016: findingsCount cross-validation collapses to one fail-closed inequality check,
# in both the unit and phase redteam loops.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-004: unit redteam round-5 budget exit captures codify findings and blocks archive.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-003: phase redteam round-8 budget exit writes a deferred note, captures codify
# findings, and blocks archive.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_rt003_rt004_archive_skip_message_distinguishes_budget_block_cause(wf_path: Path) -> None:
    content = _read(wf_path)
    skip_block_idx = content.find("if (protocolBlocked) {")
    assert skip_block_idx != -1, f"{wf_path.name}: archive-skip message block not found."
    skip_block = content[skip_block_idx : skip_block_idx + 3000]
    assert "phaseBudgetBlocked" in skip_block and "unitBudgetBlocked" in skip_block, (
        f"{wf_path.name}: the archive-skip message block must branch on phaseBudgetBlocked / "
        "unitBudgetBlocked — misdirected remediation (e.g. pointing at /agent-verify for a "
        "budget-exhausted block) wastes developer time, the exact rationale the existing "
        "testsBlockedArchive/templatePropagationBlocked branches in this same block document."
    )


# ---------------------------------------------------------------------------
# RT-018: MAX_LRN_PER_WAVE overflow writes a durable deferred note instead of only logging.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_rt018_lrn_cap_overflow_writes_deferred_note(wf_path: Path) -> None:
    codify = _codify_section(_read(wf_path), wf_path)
    cap_check_idx = codify.find("if (toCodeify.length > MAX_LRN_PER_WAVE) {")
    assert cap_check_idx != -1, f"{wf_path.name}: MAX_LRN_PER_WAVE overflow branch not found."
    note_idx = codify.find("-lrn-cap-exceeded.md", cap_check_idx)
    assert note_idx != -1, (
        f"{wf_path.name}: MAX_LRN_PER_WAVE overflow must write a deferred note "
        "(<wave>-lrn-cap-exceeded.md) — every other truncation/budget path in this file does "
        "this (including the AGENT_CALL_BUDGET throw, per RT-012); a bare log() line loses the "
        "overflow findings permanently."
    )
    close_brace_idx = codify.find("\n}", cap_check_idx)
    assert cap_check_idx < note_idx < close_brace_idx, (
        f"{wf_path.name}: the deferred-note write must be inside the "
        "`if (toCodeify.length > MAX_LRN_PER_WAVE)` branch."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_FILES, ids=WAVE_CYCLE_IDS)
def test_rt018_lrn_cap_deferred_note_includes_overflow_findings(wf_path: Path) -> None:
    codify = _codify_section(_read(wf_path), wf_path)
    cap_check_idx = codify.find("if (toCodeify.length > MAX_LRN_PER_WAVE) {")
    assert cap_check_idx != -1, f"{wf_path.name}: MAX_LRN_PER_WAVE overflow branch not found."
    overflow_decl_window = codify[cap_check_idx : cap_check_idx + 300]
    assert "toCodeify.slice(MAX_LRN_PER_WAVE)" in overflow_decl_window, (
        f"{wf_path.name}: the overflow branch must derive the overflow set from "
        "toCodeify.slice(MAX_LRN_PER_WAVE) — the findings past the cap."
    )
    note_idx = codify.find("-lrn-cap-exceeded.md", cap_check_idx)
    assert note_idx != -1, f"{wf_path.name}: MAX_LRN_PER_WAVE deferred note not found."
    window = codify[note_idx : note_idx + 800]
    assert "JSON.stringify(" in window, (
        f"{wf_path.name}: the LRN-cap deferred note must serialize the overflow findings "
        "(already fixed by the redteam loop but not individually codified) into the note body."
    )
