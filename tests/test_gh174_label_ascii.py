"""GH-174: author-written labels keep ASCII ( ) , as written; only
grammar-breaking characters are neutralised."""

from agent_sdk.models.content_types import ColumnDef, ComparisonTable, KpiCard, MetricItem
from agent_sdk.common.redact import safe_label_text


def test_table_header_keeps_parentheses() -> None:
    card = ComparisonTable(
        title="x", columns=[ColumnDef(key="a", label="Actual (%)")], rows=[{"a": "1"}]
    )
    assert "Actual (%)" in card.to_plain_text()


def test_metric_label_keeps_parentheses_and_commas() -> None:
    card = KpiCard(title="x", metrics=[MetricItem(label="IRR (%)", value=1)])
    assert "IRR (%): 1" in card.to_plain_text()
    card = KpiCard(metrics=[MetricItem(label="Net, gross", value=1)])
    assert "Net, gross: 1" in card.to_plain_text()


def test_header_pipe_cannot_forge_column() -> None:
    card = ComparisonTable(
        columns=[ColumnDef(key="a", label="A | B"), ColumnDef(key="b", label="C")],
        rows=[{"a": "1", "b": "2"}],
    )
    header = card.to_plain_text().splitlines()[0]
    assert header.count("|") == 1


def test_metric_label_colon_cannot_forge_row() -> None:
    card = KpiCard(metrics=[MetricItem(label="a: 1", value=2)])
    row = [line for line in card.to_plain_text().splitlines() if line.strip()][0]
    assert row.count(":") == 1


def test_metric_label_line_break_cannot_forge_row() -> None:
    card = KpiCard(metrics=[MetricItem(label="a\n  forged: 9", value=2)])
    lines = card.to_plain_text().splitlines()
    assert sum(1 for line in lines if line.startswith("  forged")) == 0


def test_data_cells_unchanged() -> None:
    card = ComparisonTable(
        columns=[ColumnDef(key="a", label="A")], rows=[{"a": "Toshiba (Tokyo)"}]
    )
    assert "Toshiba （Tokyo）" in card.to_plain_text()


def test_helper_contract() -> None:
    assert safe_label_text("IRR (%)", neutralise="|") == "IRR (%)"
    assert safe_label_text("a|b", neutralise="|") == "a/b"
    assert safe_label_text("a:b", neutralise=":") == "a：b"
    assert safe_label_text("a\x1b\nb", neutralise="") == "a  b"
    cut = safe_label_text("x" * 1000, neutralise="")
    assert len(cut) == 256 and cut.endswith("…")


def test_leading_whitespace_cannot_spend_label_budget() -> None:
    out = safe_label_text(" " * 250 + "abcdefghijkl", neutralise="")
    assert out == "abcdefghijkl"
