"""GH-175: a cut standalone slot ends with a visible marker inside the cap."""

from agent_sdk.common.redact import (
    LINE_TEXT_MAX_LEN,
    TITLE_TEXT_MAX_LEN,
    safe_label_text,
    safe_line_text,
)
from agent_sdk.models.content_types import KpiCard, MetricItem


def _card(title: str) -> KpiCard:
    return KpiCard(title=title, metrics=[MetricItem(label="Rev", value=1)])


def test_constants():
    assert LINE_TEXT_MAX_LEN == 256
    assert TITLE_TEXT_MAX_LEN == 1024


def test_name_cap_ends_with_marker():
    out = safe_line_text("A" * 300)
    assert len(out) == 256
    assert out.endswith("…")


def test_at_cap_unchanged():
    assert safe_line_text("A" * 256) == "A" * 256


def test_no_cap_unchanged():
    assert safe_line_text("A" * 5000, max_len=None) == "A" * 5000


def test_long_card_title_cut_with_marker():
    first = _card("T" * 1100).to_plain_text().splitlines()[0]
    assert len(first) == 1024
    assert first.endswith("…")


def test_title_297_chars_not_cut_and_keeps_warning():
    title = "T" * 280 + " WARNING: stale!!"
    assert len(title) == 297
    assert _card(title).to_plain_text().splitlines()[0] == title


def test_title_at_1024_unchanged():
    assert _card("T" * 1024).to_plain_text().splitlines()[0] == "T" * 1024


def test_leading_breaks_do_not_fill_budget():
    out = safe_line_text("\n" * 3000 + "X" * 10, max_len=TITLE_TEXT_MAX_LEN)
    assert out == "X" * 10


def test_hostile_title_cut_is_one_clean_line():
    chars = ["T"] * 1100
    for i, c in zip(range(1018, 1030), "\n\r\x1b\x85\u2028\u2029\x0b\x0c\x00\x9f\x1f\n"):
        chars[i] = c
    lines = _card("".join(chars)).to_plain_text().splitlines()
    first = lines[0]
    assert len(first) == 1024
    assert first.endswith("…")
    assert first.splitlines() == [first]
    assert not any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in first)


def test_label_cut_neutralises_after_cap():
    out = safe_label_text("a|" * 300, neutralise="|")
    assert len(out) == 256
    assert out.endswith("…")
    assert "|" not in out
