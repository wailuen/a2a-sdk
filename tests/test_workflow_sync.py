"""CI sync-check: workflow files shipped in both .claude/workflows/ (runtime) and
harness/workflows/ (template/propagation source) MUST stay byte-identical.

RT-003 fix: the two copies of wave-cycle.js silently diverged across ~10 behaviors
(null-gate fail-closed guards, recheck guard, deferred notes, archive row-append).
Whenever a fix lands in one copy but not the other, it is silently un-applied for
whichever copy actually runs. This test fails the moment the copies drift, so the
divergence can never recur unnoticed.

Two sync axes are guarded:

1. .claude/workflows/ ↔ harness/workflows/ (runtime ↔ propagation source) — files
   present in BOTH directories must be byte-identical.

2. harness/workflows/ ↔ template/.claude/workflows/ (harness ↔ peer-repo template) —
   files that live only in harness/ but are propagated to the template repo must also
   stay byte-identical. acceptance-api.js is the canonical example: it is absent from
   .claude/workflows/ (no runtime copy here) but IS propagated to template/. Without
   this second axis the intersection-only check silently skips it, creating exactly the
   split-brain failure mode warned against in LRN-067/LRN-065.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUNTIME_DIR = REPO_ROOT / ".claude" / "workflows"
HARNESS_DIR = REPO_ROOT / "harness" / "workflows"
TEMPLATE_DIR = REPO_ROOT / "template" / ".claude" / "workflows"

# Axis 1: files present in both .claude/workflows/ and harness/workflows/
_runtime_names = {p.name for p in RUNTIME_DIR.glob("*.js")}
_harness_names = {p.name for p in HARNESS_DIR.glob("*.js")}
SHARED = sorted(_runtime_names & _harness_names)

# Axis 2: files present in both harness/workflows/ and template/.claude/workflows/
_template_names = {p.name for p in TEMPLATE_DIR.glob("*.js")} if TEMPLATE_DIR.exists() else set()
HARNESS_TEMPLATE_SHARED = sorted(_harness_names & _template_names)


def test_wave_cycle_is_shared() -> None:
    """Guard: wave-cycle.js must be present in both dirs (it is the core wave runner).

    If this fails, one copy was deleted/renamed — investigate before trusting the
    sync test below, which would otherwise silently skip the most important file.
    """
    assert "wave-cycle.js" in SHARED, (
        "wave-cycle.js missing from .claude/workflows/ or harness/workflows/ — "
        f"shared workflow files found: {SHARED}"
    )


def test_acceptance_api_is_harness_template_shared() -> None:
    """Guard: acceptance-api.js must be present in both harness/ and template/ dirs.

    acceptance-api.js is absent from .claude/workflows/ (no local runtime copy) but
    IS propagated to template/.claude/workflows/. If this fails, it was removed from
    one side without updating the other — investigate before the propagation axis
    check below silently shrinks.
    """
    assert "acceptance-api.js" in HARNESS_TEMPLATE_SHARED, (
        "acceptance-api.js missing from harness/workflows/ or "
        "template/.claude/workflows/ — "
        f"harness↔template shared workflow files found: {HARNESS_TEMPLATE_SHARED}"
    )


@pytest.mark.parametrize("name", SHARED)
def test_runtime_and_harness_copies_are_identical(name: str) -> None:
    runtime = (RUNTIME_DIR / name).read_text()
    harness = (HARNESS_DIR / name).read_text()
    assert runtime == harness, (
        f".claude/workflows/{name} and harness/workflows/{name} have diverged. "
        "These two copies must be byte-identical — a fix landing in only one copy "
        "is silently un-applied for the other. Reconcile into a single superset "
        "(diff the files to find the drift)."
    )


@pytest.mark.parametrize("name", HARNESS_TEMPLATE_SHARED)
def test_harness_and_template_copies_are_identical(name: str) -> None:
    harness = (HARNESS_DIR / name).read_text()
    template = (TEMPLATE_DIR / name).read_text()
    assert harness == template, (
        f"harness/workflows/{name} and template/.claude/workflows/{name} have diverged. "
        "These two copies must be byte-identical — a fix landing in only one copy "
        "is silently un-applied in the peer repo. Reconcile into a single superset "
        "(diff the files to find the drift), then copy the result to both locations."
    )
