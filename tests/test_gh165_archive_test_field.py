"""GH-165: Archive step 3 must also fill `Test: [pending]` in FR entries."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WAVE_CYCLE = [
    ROOT / "harness" / "workflows" / "wave-cycle.js",
    ROOT / ".claude" / "workflows" / "wave-cycle.js",
]
ALL = [*WAVE_CYCLE, ROOT / ".claude" / "workflows" / "sdk-wave.js"]
TEMPLATE = ROOT / "template" / ".claude" / "workflows" / "wave-cycle.js"


def _archive_step3(path: Path) -> str:
    text = path.read_text()
    start = text.index("3. For each path in the scope list")
    return text[start : text.index("Scope paths", start)]


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.parent.parent.name + "/" + p.name)
def test_archive_step3_fills_test_field(path: Path) -> None:
    step = _archive_step3(path)
    assert "Test: says [pending]" in step
    assert "tests/<file>.py::<test_name>" in step
    assert "exists and passed" in step
    assert "leave" in step.lower() and "[pending]" in step


@pytest.mark.parametrize("path", WAVE_CYCLE, ids=lambda p: p.parent.parent.name)
def test_phase_detail_mentions_test_field(path: Path) -> None:
    head = "\n".join(path.read_text().splitlines()[:20])
    assert "backfill FR Implementation: and Test: fields" in head


def test_harness_and_runtime_copies_identical() -> None:
    assert WAVE_CYCLE[0].read_bytes() == WAVE_CYCLE[1].read_bytes()


@pytest.mark.skipif(not TEMPLATE.exists(), reason="template repo absent")
def test_template_archive_step_matches() -> None:
    assert _archive_step3(TEMPLATE) == _archive_step3(WAVE_CYCLE[0])
