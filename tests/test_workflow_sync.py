"""CI sync-check: workflow files shipped in both .claude/workflows/ (runtime) and
harness/workflows/ (template/propagation source) MUST stay byte-identical.

RT-003 fix: the two copies of wave-cycle.js silently diverged across ~10 behaviors
(null-gate fail-closed guards, recheck guard, deferred notes, archive row-append).
Whenever a fix lands in one copy but not the other, it is silently un-applied for
whichever copy actually runs. This test fails the moment the copies drift, so the
divergence can never recur unnoticed.

Only files that exist in BOTH directories are compared. Files unique to one side
(e.g. sdk-wave.js in .claude/, acceptance-api.js in harness/) are intentionally
not synced and are skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUNTIME_DIR = REPO_ROOT / ".claude" / "workflows"
HARNESS_DIR = REPO_ROOT / "harness" / "workflows"


def _shared_workflow_names() -> list[str]:
    runtime = {p.name for p in RUNTIME_DIR.glob("*.js")}
    harness = {p.name for p in HARNESS_DIR.glob("*.js")}
    return sorted(runtime & harness)


SHARED = _shared_workflow_names()


def test_wave_cycle_is_shared() -> None:
    """Guard: wave-cycle.js must be present in both dirs (it is the core wave runner).

    If this fails, one copy was deleted/renamed — investigate before trusting the
    sync test below, which would otherwise silently skip the most important file.
    """
    assert "wave-cycle.js" in SHARED, (
        "wave-cycle.js missing from .claude/workflows/ or harness/workflows/ — "
        f"shared workflow files found: {SHARED}"
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
