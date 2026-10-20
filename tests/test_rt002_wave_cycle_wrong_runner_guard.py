"""wave-cycle.js's protocol-surface arrays are src/-rooted, so it refuses to run in a repo
whose root has agent_sdk/ and no src/ (the a2a-sdk layout) — every protocol audit would be
skipped silently. That guard is pinned behaviourally in tests/test_wave_cycle_behaviour.py
(preflight abort before any parse, fail-closed on an untrustworthy preflight, the abort
message, and the preflight script's layout check run against a real repo).

This module pins the other half: sdk-wave.js is the intended runner for that layout and must
not gain a mirrored guard that would abort on the condition it exists to handle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def test_sdk_wave_js_has_no_wrong_runner_guard() -> None:
    sdk_wave = REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"
    if not sdk_wave.exists():
        pytest.skip("sdk-wave.js not present in this checkout")
    content = sdk_wave.read_text()
    assert "REPO_LAYOUT_CHECK_SCHEMA" not in content and "wrongRunnerForRepoLayout" not in content, (
        "sdk-wave.js must not gain the wave-cycle.js-only wrong-runner guard — sdk-wave.js is "
        "the intended runner for an agent_sdk/-without-src/ repo layout."
    )
