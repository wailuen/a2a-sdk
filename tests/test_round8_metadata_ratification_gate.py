"""RT-004 (w040 follow-up, REVIEWS.md Round 10): a wave's own redteam/
implementer cannot ratify a frozen A2UI Standard Profile v1 field-contract
doc edit alone (memory/feedback-wave-signoff-needs-user-ratification).

REVIEWS.md Round 8 recorded w040's removal of `TimeSeriesChart`'s typed
`metadata` row as PROPOSED, pending user ratification — never SIGNED OFF.
The pre-RT-004 gate only warned when a reverted row reappeared, so nothing
blocked the unratified removal itself from shipping — the exact inverse of
GH-149, where code was changed to conform to this same frozen table.

RT-004 reverts the doc edit (the row is restored) and inverts the gate: this
test pins the new behaviour — while `ROUND_8_METADATA_ROW_REMOVAL_RATIFIED`
is False, an advisor copy missing the frozen row (or carrying the unratified
cross-cutting override note) now FAILS the suite; flipping the flag to True
(only once a maintainer marks a REVIEWS.md entry SIGNED OFF) is required
before the row may be dropped again.
"""

from __future__ import annotations

import pytest

from tests.test_rt002_a2ui_wire_shape_mirror_parity import (
    METADATA_CROSS_CUTTING_MARKER,
    ROUND_8_METADATA_ROW_REMOVAL_RATIFIED,
    STALE_TIME_SERIES_METADATA_ROW,
    _assert_metadata_row_present_or_fail,
)


def test_round_8_is_not_yet_ratified():
    """Guards against silently flipping the flag without a REVIEWS.md update."""
    assert ROUND_8_METADATA_ROW_REMOVAL_RATIFIED is False, (
        "ROUND_8_METADATA_ROW_REMOVAL_RATIFIED flipped to True — this must "
        "only happen alongside a REVIEWS.md entry marked SIGNED OFF by a "
        "maintainer, not as an incidental test edit"
    )


def test_missing_row_fails_while_unratified():
    text = "no frozen row here"
    with pytest.raises(AssertionError, match="missing the frozen"):
        _assert_metadata_row_present_or_fail(
            "fake/path.md", text, ratified=False
        )


def test_cross_cutting_override_fails_even_alongside_the_row_while_unratified():
    text = f"...\n{STALE_TIME_SERIES_METADATA_ROW}\n...\n{METADATA_CROSS_CUTTING_MARKER}\n..."
    with pytest.raises(AssertionError, match="unratified cross-cutting"):
        _assert_metadata_row_present_or_fail(
            "fake/path.md", text, ratified=False
        )


def test_present_row_with_no_override_is_silent_while_unratified():
    text = f"...\n{STALE_TIME_SERIES_METADATA_ROW}\n..."
    _assert_metadata_row_present_or_fail("fake/path.md", text, ratified=False)


def test_missing_row_is_authorized_once_ratified():
    text = "no frozen row here"
    _assert_metadata_row_present_or_fail("fake/path.md", text, ratified=True)
