"""Profile v1.1 (REVIEWS.md Round 11): the `TimeSeriesChart.metadata` row removal
is SIGNED OFF (#153). These tests pin the flag derivation, the reference format
and both branches of the advisor-state check in
`test_rt002_a2ui_wire_shape_mirror_parity`.
"""

from __future__ import annotations

import pytest

from tests.test_rt002_a2ui_wire_shape_mirror_parity import (
    METADATA_CROSS_CUTTING_MARKER,
    ROUND_8_METADATA_ROW_REMOVAL_RATIFIED,
    STALE_TIME_SERIES_METADATA_ROW,
    _assert_metadata_row_state,
    _read,
    round_11_checkable_reference_recorded,
)


def test_flag_is_derived_from_reviews_md_not_hardcoded():
    assert ROUND_8_METADATA_ROW_REMOVAL_RATIFIED is round_11_checkable_reference_recorded(
        _read("REVIEWS.md")
    )


def test_signed_off_text_requires_checkable_reference():
    text = _read("REVIEWS.md")
    section = text.split("## Round 11", 1)[1].split("\n## ", 1)[0]
    status = next((ln for ln in section.splitlines()[1:] if ln.strip()), "")
    if status.startswith("**SIGNED OFF**"):
        assert round_11_checkable_reference_recorded(text)


def test_pending_or_proposed_blocks_ratification():
    base = "## Round 11 x\n\n{}\nCheckable reference: {}\n"
    assert not round_11_checkable_reference_recorded(base.format("**PROPOSED**", "https://x/y"))
    assert not round_11_checkable_reference_recorded(base.format("**SIGNED OFF**", "**PENDING**"))
    assert not round_11_checkable_reference_recorded(base.format("**SIGNED OFF**", "none"))
    assert round_11_checkable_reference_recorded(
        base.format("**SIGNED OFF**", "https://github.com/wailuen/a2a-sdk/issues/999999")
    )


ROW = STALE_TIME_SERIES_METADATA_ROW
MARKER = METADATA_CROSS_CUTTING_MARKER


def test_ratified_state_rejects_row():
    with pytest.raises(AssertionError, match="still carries the typed"):
        _assert_metadata_row_state("fake.md", f"{ROW}\n{MARKER}", ratified=True)


def test_ratified_state_requires_marker():
    with pytest.raises(AssertionError, match="missing the cross-cutting"):
        _assert_metadata_row_state("fake.md", "nothing", ratified=True)


def test_ratified_state_passes_with_marker_and_no_row():
    _assert_metadata_row_state("fake.md", MARKER, ratified=True)


def test_pending_state_rejects_row_removal():
    with pytest.raises(AssertionError, match="dropped the frozen"):
        _assert_metadata_row_state("fake.md", MARKER, ratified=False)


def test_pending_state_rejects_marker():
    with pytest.raises(AssertionError, match="pending ratification"):
        _assert_metadata_row_state("fake.md", f"{ROW}\n{MARKER}", ratified=False)


def test_pending_state_passes_with_row_and_no_marker():
    _assert_metadata_row_state("fake.md", ROW, ratified=False)


def test_default_follows_the_reviews_md_flag():
    text = MARKER if ROUND_8_METADATA_ROW_REMOVAL_RATIFIED else ROW
    _assert_metadata_row_state("fake.md", text)


def test_round_11_is_signed_off_and_flag_is_true():
    assert ROUND_8_METADATA_ROW_REMOVAL_RATIFIED is True
