"""RT-003 (w040 follow-up): REVIEWS.md Round 8 records the removal of
TimeSeriesChart's typed `metadata` sub-shape row as **PROPOSED, pending user
ratification** — explicitly not SIGNED OFF, per the standing project rule
that a wave's own redteam/implementer cannot ratify a frozen-contract doc
change alone (memory/feedback-wave-signoff-needs-user-ratification).

Before this fix, `tests/test_rt002_a2ui_wire_shape_mirror_parity.py` hard
`assert`ed the row's absence unconditionally, so a maintainer reverting the
unratified proposal (restoring the typed row) would break the test suite —
the enforced status in tests contradicted the provisional status recorded in
REVIEWS.md. This test pins the gating behaviour that keeps them in sync:
while `ROUND_8_METADATA_ROW_REMOVAL_RATIFIED` is False, a reverted/stale row
must warn, not fail; flipping the flag to True (only once a maintainer marks
Round 8 SIGNED OFF in REVIEWS.md) must upgrade it back to a hard failure.
"""

from __future__ import annotations

import warnings

import pytest

from tests.test_rt002_a2ui_wire_shape_mirror_parity import (
    ROUND_8_METADATA_ROW_REMOVAL_RATIFIED,
    STALE_TIME_SERIES_METADATA_ROW,
    _assert_metadata_row_removed_or_warn,
)


def test_round_8_is_not_yet_ratified():
    """Guards against silently flipping the flag without a REVIEWS.md update."""
    assert ROUND_8_METADATA_ROW_REMOVAL_RATIFIED is False, (
        "ROUND_8_METADATA_ROW_REMOVAL_RATIFIED flipped to True — this must "
        "only happen alongside a REVIEWS.md Round 8 entry marked SIGNED OFF "
        "by a maintainer, not as an incidental test edit"
    )


def test_stale_row_warns_but_does_not_fail_while_unratified():
    text = f"...\n{STALE_TIME_SERIES_METADATA_ROW}\n..."
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _assert_metadata_row_removed_or_warn(
            "fake/path.md", text, ratified=False
        )
    assert len(caught) == 1
    assert "still carries the stale" in str(caught[0].message)


def test_stale_row_raises_once_ratified():
    text = f"...\n{STALE_TIME_SERIES_METADATA_ROW}\n..."
    with pytest.raises(AssertionError, match="still carries the stale"):
        _assert_metadata_row_removed_or_warn(
            "fake/path.md", text, ratified=True
        )


def test_absent_row_is_silent_regardless_of_ratification():
    text = "no stale row here"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _assert_metadata_row_removed_or_warn("fake/path.md", text, ratified=False)
        _assert_metadata_row_removed_or_warn("fake/path.md", text, ratified=True)
    assert caught == []
