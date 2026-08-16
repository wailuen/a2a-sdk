"""Registry enforcement: component-name uniqueness, frozen-profile clean
registration, and re-registration idempotency (DESIGN.md §4.3)."""

from __future__ import annotations

import collections
import inspect
import re
import types
from typing import Annotated, Any, ClassVar, Literal, Union

import pytest
from pydantic import BaseModel, ValidationError

import agent_sdk.models.content_types as content_types_module

# RT-010: the separator alphabet lives in agent_sdk/common/redact.py (the C-007
# family) — import it from its real home. content_types.py used to re-import these
# three private names it never uses, solely so this file could import them from
# there; that pinned another module's private names across a package boundary and
# made production import structure a function of a test's import convenience.
from agent_sdk.common.redact import (
    _BARE_SEPARATORS,
    _SPACED_SEPARATORS,
    _STRUCTURAL_SEPARATORS,
)
from agent_sdk.models.content_types import (
    _NON_SEPARATOR_GLYPHS,
    _REGISTRY,
    PROFILE_TYPES,
    BarChart,
    BarItem,
    BriefingKpiItem,
    CalendarEvent,
    CalendarEvents,
    CategoryValue,
    ChartSection,
    ColumnDef,
    ComparisonTable,
    ContentModel,
    DateRange,
    DocumentItem,
    DocumentList,
    EmailList,
    EmailMessage,
    EntityItem,
    EntityList,
    EventLocation,
    FirstLastRange,
    FundPerformance,
    KpiCard,
    KpiRowSection,
    ManagerRef,
    MarketBriefing,
    MetricItem,
    MultiCategoryChart,
    MultiCategoryPeriod,
    MultiCategorySummary,
    NameEmail,
    TableSection,
    TextSection,
    TimeSeriesChart,
    TimeSeriesDataPoint,
    UserList,
    UserProfile,
    UserSummary,
    WaterfallChart,
    WaterfallSegment,
    register_content_type,
)


class _DomainCard(ContentModel):
    """Base for test domain cards — declares its own (non-Profile) catalog."""

    catalog_id: ClassVar[str] = "urn:test-catalog:v1"

    def to_plain_text(self) -> str:  # pragma: no cover - trivial fallback
        return ""


def test_duplicate_component_name_raises():
    """Two distinct classes claiming the same wire component name are rejected."""

    class CardA(_DomainCard):
        data_type: ClassVar[str] = "test_card_a"
        component: ClassVar[str] = "CollidingCard"

    class CardB(_DomainCard):
        data_type: ClassVar[str] = "test_card_b"   # distinct data_type
        component: ClassVar[str] = "CollidingCard"  # same wire name as CardA

    register_content_type(CardA)
    try:
        with pytest.raises(ValueError, match="CollidingCard"):
            register_content_type(CardB)
    finally:
        _REGISTRY.pop("test_card_a", None)
        _REGISTRY.pop("test_card_b", None)


def test_duplicate_component_across_catalogs_raises():
    """Global rule: a collision is rejected even across different catalog ids
    (A2UI resolves by bare componentType, not by catalogId)."""

    class CardC(_DomainCard):
        data_type: ClassVar[str] = "test_card_c"
        component: ClassVar[str] = "CrossCatalogCard"
        catalog_id: ClassVar[str] = "urn:catalog-one:v1"

    class CardD(_DomainCard):
        data_type: ClassVar[str] = "test_card_d"
        component: ClassVar[str] = "CrossCatalogCard"
        catalog_id: ClassVar[str] = "urn:catalog-two:v1"

    register_content_type(CardC)
    try:
        with pytest.raises(ValueError, match="CrossCatalogCard"):
            register_content_type(CardD)
    finally:
        _REGISTRY.pop("test_card_c", None)
        _REGISTRY.pop("test_card_d", None)


def test_domain_card_cannot_shadow_profile_component():
    """A domain card may not reuse a FROZEN Standard Profile component name."""

    class FakeKpi(_DomainCard):
        data_type: ClassVar[str] = "test_fake_kpi"   # unique data_type
        component: ClassVar[str] = "KpiCard"          # owned by the Profile

    try:
        with pytest.raises(ValueError, match="KpiCard"):
            register_content_type(FakeKpi)
    finally:
        _REGISTRY.pop("test_fake_kpi", None)


def test_frozen_profile_component_names_globally_unique():
    """The 14 FROZEN Profile types must have distinct wire component names —
    a regression here would mean the Profile itself is self-shadowing."""
    names = [cls.component for cls in PROFILE_TYPES]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"duplicate component names in PROFILE_TYPES: {dupes}"


def test_same_class_reregistration_is_noop():
    """Re-registering the identical class must not raise (idempotency preserved
    for both the data_type and the new component check)."""
    assert _REGISTRY.get("kpi_card") is KpiCard
    assert register_content_type(KpiCard) is KpiCard   # frozen type: must not raise
    assert _REGISTRY.get("kpi_card") is KpiCard

    class ReCard(_DomainCard):
        data_type: ClassVar[str] = "test_recard"
        component: ClassVar[str] = "ReCard"

    register_content_type(ReCard)
    try:
        assert register_content_type(ReCard) is ReCard   # second call: no-op
        assert _REGISTRY["test_recard"] is ReCard
    finally:
        _REGISTRY.pop("test_recard", None)


# ── MetricItem scalar validation (issue #1) ──────────────────────────────────

def test_metric_item_rejects_bool():
    """bool must not silently coerce to 0/1 — raises ValidationError."""
    with pytest.raises((ValueError, ValidationError)):
        MetricItem(label="flag", value=True)
    with pytest.raises((ValueError, ValidationError)):
        MetricItem(label="flag", value=False)


def test_metric_item_rejects_dict():
    """Nested dict must raise rather than crash the whole task."""
    with pytest.raises((ValueError, ValidationError)):
        MetricItem(label="gni", value={"structured_value": 42000, "currency": "USD"})


def test_metric_item_rejects_list():
    with pytest.raises((ValueError, ValidationError)):
        MetricItem(label="tags", value=["a", "b"])


def test_metric_item_accepts_scalars():
    assert MetricItem(label="price", value=42.5).value == 42.5
    assert MetricItem(label="count", value=7).value == 7
    assert MetricItem(label="name", value="BTC").value == "BTC"


def test_metric_item_from_any_returns_none_for_non_scalar():
    assert MetricItem.from_any(label="gni", value={"nested": 1}) is None
    assert MetricItem.from_any(label="flag", value=True) is None
    assert MetricItem.from_any(label="tags", value=["a", "b"]) is None


def test_metric_item_from_any_returns_item_for_scalars():
    m = MetricItem.from_any(label="price", value=99.9, unit="USD")
    assert m is not None
    assert m.value == 99.9
    assert m.unit == "USD"


def test_kpi_card_from_mixed_upstream_dict():
    """Simulates a wire() that uses from_any to project a mixed upstream API response."""
    upstream = {"price": 42.5, "meta": {"source": "bloomberg"}, "active": True, "count": 3}
    metrics = [
        m for m in (MetricItem.from_any(label=k, value=v) for k, v in upstream.items())
        if m is not None
    ]
    assert len(metrics) == 2
    labels = {m.label for m in metrics}
    assert labels == {"price", "count"}


# ── DocumentList.to_plain_text type rendering (GH #42) ───────────────────────

def test_document_list_plain_text_includes_type_when_set():
    """DocumentItem.type is rendered as '(pdf)' suffix when present."""
    docs = DocumentList(
        documents=[
            DocumentItem(id="1", name="Q4 Report", type="pdf", last_modified="2026-03-31"),
        ]
    )
    text = docs.to_plain_text()
    assert "Q4 Report (pdf)" in text
    assert "2026-03-31" in text


def test_document_list_plain_text_omits_type_when_none():
    """When DocumentItem.type is None, no parenthetical type suffix appears."""
    docs = DocumentList(
        documents=[
            DocumentItem(id="2", name="Budget Overview", type=None, last_modified="2026-01-15"),
        ]
    )
    text = docs.to_plain_text()
    assert "Budget Overview" in text
    assert "(None)" not in text
    # No type parenthetical — the only parens should be the modified date
    assert "(pdf)" not in text


# ── GH-63: metadata escape hatch on all 12 ContentModel subclasses ───────────

_COVERAGE_META = {"coverage_note": "analyst estimate", "source": "pitchbook"}


def test_kpi_card_metadata_wire_round_trip():
    card = KpiCard(
        metrics=[MetricItem(label="IRR", value=18.5, unit="%")],
        metadata=_COVERAGE_META,
    )
    w = card.wire()
    assert w["metadata"] == _COVERAGE_META


def test_kpi_card_metadata_none_excluded_from_wire():
    card = KpiCard(metrics=[MetricItem(label="IRR", value=18.5)])
    assert "metadata" not in card.wire()


def test_comparison_table_metadata_wire_round_trip():
    table = ComparisonTable(
        columns=[ColumnDef(key="fund", label="Fund")],
        rows=[{"fund": "ABC"}],
        metadata={"coverage_note": "preliminary"},
    )
    w = table.wire()
    assert w["metadata"]["coverage_note"] == "preliminary"


def test_bar_chart_metadata_wire_round_trip():
    chart = BarChart(
        bars=[BarItem(category="Q1", value=100.0)],
        metadata={"source": "internal"},
    )
    assert chart.wire()["metadata"] == {"source": "internal"}


def test_entity_list_metadata_wire_round_trip():
    el = EntityList(
        entity_type="company",
        items=[EntityItem(id="1", name="Acme")],
        metadata={"coverage_note": "draft"},
    )
    assert el.wire()["metadata"]["coverage_note"] == "draft"


def test_market_briefing_metadata_wire_round_trip():
    mb = MarketBriefing(
        title="Weekly Update",
        as_of="2026-06-18",
        metadata={"coverage_note": "final"},
    )
    assert mb.wire()["metadata"] == {"coverage_note": "final"}


def test_waterfall_chart_metadata_wire_round_trip():
    wc = WaterfallChart(
        title="Cash Flow",
        segments=[
            WaterfallSegment(label="Start", value=1000.0, type="initial", cumulative=1000.0),
        ],
        metadata={"source": "model"},
    )
    assert wc.wire()["metadata"] == {"source": "model"}


def test_multi_category_chart_metadata_wire_round_trip():
    mc = MultiCategoryChart(
        title="Spend by Category",
        periods=[
            MultiCategoryPeriod(
                period="2026-Q1",
                categories={"tech": CategoryValue(value=500.0)},
            )
        ],
        summary=MultiCategorySummary(
            by_category={"tech": CategoryValue(value=500.0)},
            period_count=1,
        ),
        date_range=FirstLastRange(first="2026-01-01", last="2026-03-31"),
        metadata={"coverage_note": "estimated"},
    )
    assert mc.wire()["metadata"]["coverage_note"] == "estimated"


def test_fund_performance_metadata_wire_round_trip():
    fp = FundPerformance(
        fundName="Alpha Fund III",
        irr=0.185,
        metadata={"coverage_note": "analyst estimate"},
    )
    w = fp.wire()
    assert w["metadata"] == {"coverage_note": "analyst estimate"}
    # camelCase fields are still serialised correctly alongside metadata
    assert w["fundName"] == "Alpha Fund III"


def test_email_list_metadata_wire_round_trip():
    msg = EmailMessage(
        id="m1",
        subject="Deal Update",
        preview="See attached...",
        **{"from": NameEmail(name="Alice", email="alice@example.com")},
        to_recipients=[NameEmail(name="Bob", email="bob@example.com")],
        received_at="2026-06-18T09:00:00Z",
        is_read=False,
        web_link="https://mail.example.com/m1",
    )
    el = EmailList(
        messages=[msg],
        total_count=1,
        has_more=False,
        metadata={"coverage_note": "inbox snapshot"},
    )
    assert el.wire()["metadata"]["coverage_note"] == "inbox snapshot"


def test_calendar_events_metadata_wire_round_trip():
    evt = CalendarEvent(
        id="e1",
        subject="Board Meeting",
        start="2026-06-18T10:00:00Z",
        end="2026-06-18T11:00:00Z",
        organizer=NameEmail(name="Alice", email="alice@example.com"),
        web_link="https://cal.example.com/e1",
    )
    ce = CalendarEvents(
        events=[evt],
        date_range=DateRange(start="2026-06-18", end="2026-06-18"),
        total_count=1,
        has_more=False,
        metadata={"coverage_note": "calendar sync"},
    )
    assert ce.wire()["metadata"]["coverage_note"] == "calendar sync"


def test_user_profile_metadata_wire_round_trip():
    up = UserProfile(
        id="u1",
        display_name="Alice Smith",
        email="alice@example.com",
        metadata={"coverage_note": "directory export"},
    )
    assert up.wire()["metadata"] == {"coverage_note": "directory export"}


def test_user_list_metadata_wire_round_trip():
    ul = UserList(
        users=[UserSummary(id="u1", display_name="Alice", email="alice@example.com")],
        total_count=1,
        has_more=False,
        metadata={"source": "azure_ad"},
    )
    assert ul.wire()["metadata"] == {"source": "azure_ad"}


def test_document_list_metadata_wire_round_trip():
    dl = DocumentList(
        documents=[DocumentItem(id="d1", name="Term Sheet")],
        metadata={"coverage_note": "draft version"},
    )
    assert dl.wire()["metadata"]["coverage_note"] == "draft version"


def test_metadata_none_excluded_for_multiple_types():
    """metadata=None must be excluded from wire() output for all 12 types."""
    # spot-check 3 types from different tiers
    assert "metadata" not in KpiCard(
        metrics=[MetricItem(label="x", value=1)]
    ).wire()
    assert "metadata" not in DocumentList(
        documents=[DocumentItem(id="1", name="Doc")]
    ).wire()
    assert "metadata" not in UserList(
        users=[UserSummary(id="u1", display_name="A", email="a@x.com")],
        total_count=1,
        has_more=False,
    ).wire()


def test_metadata_survives_wire_with_nested_dict():
    """Metadata with nested structure survives round-trip (wire returns JSON-safe dict)."""
    nested = {"flags": {"is_estimated": True, "confidence": 0.92}, "tags": ["analyst", "q2"]}
    card = KpiCard(
        metrics=[MetricItem(label="IRR", value=18.5)],
        metadata=nested,
    )
    w = card.wire()
    assert w["metadata"]["flags"]["confidence"] == 0.92
    assert w["metadata"]["tags"] == ["analyst", "q2"]


# ── finite-float validation (GH-95) ───────────────────────────────────────
# inf/nan silently split dual-part artifacts: model_dump_json() serializes
# them as JSON null while to_markdown()/to_plain_text() render "inf"/"nan"
# literally. These fields must reject non-finite floats at construction time.


def test_briefing_kpi_item_rejects_infinite_value():
    with pytest.raises((ValueError, ValidationError)):
        BriefingKpiItem(title="Revenue", value=float("inf"))


def test_briefing_kpi_item_rejects_nan_delta():
    with pytest.raises((ValueError, ValidationError)):
        BriefingKpiItem(title="Revenue", value=100.0, delta=float("nan"))


def test_briefing_kpi_item_rejects_negative_infinite_value():
    with pytest.raises((ValueError, ValidationError)):
        BriefingKpiItem(title="Revenue", value=float("-inf"))


def test_chart_section_rejects_nested_non_finite_float():
    with pytest.raises((ValueError, ValidationError)):
        ChartSection(chart_type="bar_chart", data={"nested": {"deep": [float("nan")]}})


def test_table_section_rejects_nested_non_finite_float():
    with pytest.raises((ValueError, ValidationError)):
        TableSection(data={"nested": {"deep": [float("inf")]}})


def test_chart_section_rejects_top_level_non_finite_float():
    with pytest.raises((ValueError, ValidationError)):
        ChartSection(chart_type="time_series", data={"max": float("nan")})


def test_briefing_kpi_item_accepts_finite_values_and_round_trips():
    item = BriefingKpiItem(title="Revenue", value=100.5, delta=-2.3)
    assert item.value == 100.5
    assert item.delta == -2.3
    dumped = item.model_dump_json()
    assert "100.5" in dumped
    assert "-2.3" in dumped


def test_chart_and_table_section_accept_finite_nested_payload():
    chart = ChartSection(chart_type="bar_chart", data={"nested": {"deep": [1.0, 2.5]}})
    table = TableSection(data={"nested": {"deep": [3.0]}})
    assert chart.data["nested"]["deep"] == [1.0, 2.5]
    assert table.data["nested"]["deep"] == [3.0]


def test_market_briefing_with_finite_sections_round_trips_consistently():
    mb = MarketBriefing(
        title="Weekly Update",
        as_of="2026-06-18",
        sections=[
            KpiRowSection(items=[BriefingKpiItem(title="Revenue", value=100.0, delta=1.5)]),
            ChartSection(chart_type="bar_chart", data={"title": "Q1", "values": [1.0, 2.0]}),
            TableSection(data={"title": "Table", "rows": [{"a": 1.0}]}),
        ],
    )
    text = mb.to_plain_text()
    assert "Revenue" in text
    json_dump = mb.model_dump_json()
    assert "Revenue" in json_dump


# ── finite-float validation is scoped to GH-95's AC, not SDK-wide (RT-001) ─
# GH-95's AC (workspace/todos/active/w029-gh-issues.md) names exactly four
# fields: BriefingKpiItem.value/.delta and ChartSection.data/TableSection.data.
# An earlier revision broadened the guard onto a _Wire-wide model_validator,
# which shipped a self-declared breaking change as a patch release — reverted
# here. Fields outside this family intentionally still accept inf/nan.


def test_metric_item_accepts_infinite_value_outside_market_briefing_scope():
    item = MetricItem(label="price", value=float("inf"))
    assert item.value == float("inf")


def test_bar_item_accepts_non_finite_value_outside_scope():
    bar = BarItem(category="Q1", value=float("-inf"))
    assert bar.value == float("-inf")


def test_waterfall_segment_accepts_non_finite_value_outside_scope():
    seg = WaterfallSegment(label="Start", value=float("inf"), type="initial", cumulative=0.0)
    assert seg.value == float("inf")


def test_comparison_table_accepts_non_finite_row_value_outside_scope():
    table = ComparisonTable(
        columns=[ColumnDef(key="v", label="Value")],
        rows=[{"v": float("inf")}],
    )
    assert table.rows[0]["v"] == float("inf")


def test_kpi_card_accepts_non_finite_metadata_value_outside_scope():
    """Free-form metadata dicts on non-MarketBriefing types are outside GH-95's
    AC — only ChartSection.data/TableSection.data are scoped in."""
    card = KpiCard(
        metrics=[MetricItem(label="price", value=1.0)],
        metadata={"confidence": float("nan")},
    )
    assert card.metadata is not None and card.metadata["confidence"] != card.metadata["confidence"]


def test_fund_performance_accepts_non_finite_irr_outside_scope():
    fp = FundPerformance(irr=float("inf"))
    assert fp.irr == float("inf")


def test_metric_item_accepts_finite_value_and_round_trips():
    item = MetricItem(label="price", value=42.5)
    assert item.value == 42.5
    assert "42.5" in item.model_dump_json()


def test_waterfall_segment_accepts_finite_values_and_round_trips():
    seg = WaterfallSegment(label="Start", value=10.0, type="initial", cumulative=10.0)
    assert seg.value == 10.0
    assert seg.cumulative == 10.0


# ── finite-float validation recurses into nested foreign BaseModel (RT-003) ─
# _assert_finite must not stop at dict/list/tuple nesting: a plain (non-_Wire)
# pydantic BaseModel value embedded inside ChartSection.data/TableSection.data
# must be walked too, or a NaN inside it reproduces the exact dual-part
# divergence GH-95 set out to eliminate.


class _ForeignPayload(BaseModel):
    score: float


def test_chart_section_rejects_non_finite_float_nested_in_foreign_basemodel():
    with pytest.raises((ValueError, ValidationError)):
        ChartSection(
            chart_type="bar_chart",
            data={"nested": _ForeignPayload(score=float("nan"))},
        )


def test_table_section_rejects_non_finite_float_nested_in_foreign_basemodel():
    with pytest.raises((ValueError, ValidationError)):
        TableSection(data={"nested": _ForeignPayload(score=float("inf"))})


# ── finite-float validation bounds recursion depth (RT-003) ─────────────────
# A cyclic or pathologically deep structure passed into ChartSection.data /
# TableSection.data must surface as a clean ValidationError, not an uncaught
# RecursionError (a RuntimeError pydantic does not convert).


def test_chart_section_rejects_cyclic_data_without_recursion_error():
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    with pytest.raises((ValueError, ValidationError)):
        ChartSection(chart_type="bar_chart", data=cyclic)


def test_table_section_rejects_cyclic_data_without_recursion_error():
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    with pytest.raises((ValueError, ValidationError)):
        TableSection(data=cyclic)


def test_chart_section_rejects_pathologically_deep_data_without_recursion_error():
    deep: dict[str, Any] = {}
    node = deep
    for _ in range(5000):
        node["nested"] = {}
        node = node["nested"]
    with pytest.raises((ValueError, ValidationError)):
        ChartSection(chart_type="bar_chart", data=deep)


# ── GH-130: to_plain_text() delimiter-safety (cell-sanitizing helper) ────────
# An untrusted table cell/label or list item name/summary containing the
# column delimiter "|" (or a visual confusable) can fabricate extra columns
# in ComparisonTable's " | ".join(...) render; an embedded CR/LF can
# fabricate extra rows/entries in either renderer's "\n".join(...) render.


def test_comparison_table_pipe_in_column_label_does_not_fabricate_column():
    table = ComparisonTable(
        columns=[
            ColumnDef(key="fund", label="Fund | FAKE COLUMN"),
            ColumnDef(key="irr", label="IRR"),
        ],
        rows=[{"fund": "ABC", "irr": "18%"}],
    )
    header_line = table.to_plain_text().splitlines()[0]
    assert header_line.count(" | ") == 1
    assert "Fund / FAKE COLUMN" in header_line


def test_comparison_table_pipe_in_row_value_does_not_fabricate_column():
    table = ComparisonTable(
        columns=[ColumnDef(key="a", label="A"), ColumnDef(key="b", label="B")],
        rows=[{"a": "legit | FAKE COLUMN", "b": "z"}],
    )
    row_line = table.to_plain_text().splitlines()[-1]
    assert row_line.count(" | ") == 1
    assert "legit / FAKE COLUMN" in row_line


def test_comparison_table_confusable_pipe_chars_are_neutralized():
    table = ComparisonTable(
        columns=[ColumnDef(key="a", label="A│label")],
        rows=[{"a": "x｜y"}],
    )
    text = table.to_plain_text()
    assert "│" not in text
    assert "｜" not in text


def test_comparison_table_embedded_newline_in_row_value_does_not_fabricate_row():
    table = ComparisonTable(
        columns=[ColumnDef(key="a", label="A"), ColumnDef(key="b", label="B")],
        rows=[{"a": "legit\nFAKE ROW", "b": "z"}],
    )
    lines = table.to_plain_text().splitlines()
    # header + separator + exactly one data row
    assert len(lines) == 3
    assert "\n" not in lines[-1]


def test_entity_list_embedded_newline_in_name_does_not_fabricate_entry():
    entity_list = EntityList(
        entity_type="company",
        items=[EntityItem(id="1", name="Acme\n  - FAKE ENTITY")],
    )
    lines = entity_list.to_plain_text().splitlines()
    bullet_lines = [ln for ln in lines if ln.strip().startswith("-")]
    assert len(bullet_lines) == 1


def test_entity_list_summary_pipe_and_newline_are_sanitized():
    entity_list = EntityList(
        entity_type="company",
        items=[EntityItem(id="1", name="Acme", summary="ok\nFAKE | INJECTED")],
    )
    text = entity_list.to_plain_text()
    lines = text.splitlines()
    # title + showing + "- Acme" + one summary line
    assert len(lines) == 4
    assert "|" not in text


# ── RT-004: _sanitize_cell must neutralise the full str.splitlines() break
# set (VT, FF, NEL, U+2028/U+2029) plus C0/C1 controls, not just CR/LF — a
# [\r\n]-only filter is bypassable with a one-character substitution.


def test_comparison_table_vertical_tab_does_not_fabricate_row():
    table = ComparisonTable(
        columns=[ColumnDef(key="a", label="A"), ColumnDef(key="b", label="B")],
        rows=[{"a": "legit\x0bFAKE ROW", "b": "z"}],
    )
    lines = table.to_plain_text().splitlines()
    assert len(lines) == 3
    assert "\x0b" not in lines[-1]


def test_comparison_table_line_separator_does_not_fabricate_row():
    table = ComparisonTable(
        columns=[ColumnDef(key="a", label="A"), ColumnDef(key="b", label="B")],
        rows=[{"a": "legit" + " " + "FAKE ROW", "b": "z"}],
    )
    lines = table.to_plain_text().splitlines()
    assert len(lines) == 3
    assert " " not in lines[-1]


def test_comparison_table_ansi_escape_is_neutralized():
    table = ComparisonTable(
        columns=[ColumnDef(key="a", label="A")],
        rows=[{"a": "\x1b[31mred\x1b[0m"}],
    )
    assert "\x1b" not in table.to_plain_text()


# ── RT-005: the GH-130 delimiter-safety contract must be enforced across
# ALL 14 Standard Profile renderers, not just ComparisonTable/EntityList.


def test_email_list_subject_and_preview_newline_do_not_fabricate_lines():
    msg = EmailMessage(
        id="m1",
        subject="Update\nFAKE ROW",
        preview="see attached\nFAKE ROW",
        **{"from": NameEmail(name="Alice", email="alice@example.com")},
        to_recipients=[],
        received_at="2026-06-18T09:00:00Z",
        is_read=True,
        web_link="https://mail.example.com/m1",
    )
    el = EmailList(messages=[msg], total_count=1, has_more=False)
    lines = el.to_plain_text().splitlines()
    # header + 1 message line + 1 preview line — no fabricated extra lines
    assert len(lines) == 3
    assert "\n" not in lines[1]
    assert "\n" not in lines[2]


def test_email_list_subject_pipe_does_not_fabricate_column():
    msg = EmailMessage(
        id="m1",
        subject="Update | FAKE COLUMN",
        preview="",
        **{"from": NameEmail(name="Alice", email="alice@example.com")},
        to_recipients=[],
        received_at="2026-06-18T09:00:00Z",
        is_read=True,
        web_link="https://mail.example.com/m1",
    )
    el = EmailList(messages=[msg], total_count=1, has_more=False)
    message_line = el.to_plain_text().splitlines()[1]
    assert message_line.count(" | ") == 2  # received_at | email | subject only


def test_bar_chart_category_pipe_and_newline_are_sanitized():
    chart = BarChart(bars=[BarItem(category="Q1\nFAKE | INJECTED", value=100.0)])
    lines = chart.to_plain_text().splitlines()
    assert len(lines) == 1
    assert "|" not in lines[0]


# RT-004: renderer-owned delimiters the earlier _PIPE_/_ANGLE_BRACKET_/etc.
# maps left uncovered — ", "/"=" (MultiCategoryChart's category join), the
# em dash job-title joiner (UserList), and the boolean-derived "[unread]"/
# "[online]" markers (EmailList/CalendarEvents), which an untrusted string
# field sitting next to them can forge.


def test_multi_category_chart_category_key_comma_equals_do_not_fabricate_pair():
    mc = MultiCategoryChart(
        title="Q1 breakdown",
        periods=[
            MultiCategoryPeriod(
                period="Q1",
                categories={"revenue, profit=999": CategoryValue(value=1)},
            )
        ],
        summary=MultiCategorySummary(by_category={}, period_count=1),
        date_range=FirstLastRange(first="Q1", last="Q1"),
    )
    line = mc.to_plain_text().splitlines()[-1]
    # only the trusted "=v" the renderer itself appends for the one real
    # category, and no fabricated ", " category join
    assert line.count("=") == 1
    assert ", " not in line


def test_multi_category_chart_compact_category_key_comma_does_not_fabricate_pair():
    """RT-010: the SPACED comma above ("revenue, profit=999") was already
    neutralised by the pre-existing whitespace-adjacency rule. A COMPACT
    comma — no adjacent whitespace on either side — was not: "a,b" survived
    untouched and "  P1: a,b=1, c=2" reads, to a naive comma-split reader
    (human or model), as three categories where two exist."""
    mc = MultiCategoryChart(
        title="Q1 breakdown",
        periods=[
            MultiCategoryPeriod(
                period="P1",
                categories={
                    "a,b": CategoryValue(value=1),
                    "c": CategoryValue(value=2),
                },
            )
        ],
        summary=MultiCategorySummary(by_category={}, period_count=1),
        date_range=FirstLastRange(first="P1", last="P1"),
    )
    line = mc.to_plain_text().splitlines()[-1]
    # exactly one real ", " category join — the fabricated comma inside the
    # "a,b" key must not survive as a literal ASCII comma
    assert line.count(",") == 1


def test_multi_category_chart_compact_period_colon_does_not_fabricate_label():
    """RT-010: the same shape as the compact-comma case above, for a compact
    ":" inside the period label of this "label: value" render."""
    mc = MultiCategoryChart(
        title="Q1 breakdown",
        periods=[
            MultiCategoryPeriod(
                period="P1:FAKE",
                categories={"c": CategoryValue(value=2)},
            )
        ],
        summary=MultiCategorySummary(by_category={}, period_count=1),
        date_range=FirstLastRange(first="P1", last="P1"),
    )
    line = mc.to_plain_text().splitlines()[-1]
    # exactly one real ": " label separator — the fabricated colon inside
    # the period must not survive as a literal ASCII colon
    assert line.count(":") == 1


def test_email_list_received_at_brackets_do_not_forge_unread_marker():
    msg = EmailMessage(
        id="m1",
        subject="Update",
        preview="",
        **{"from": NameEmail(name="Alice", email="alice@example.com")},
        to_recipients=[],
        received_at="[unread] 2026-06-18T09:00:00Z",
        is_read=True,
        web_link="https://mail.example.com/m1",
    )
    el = EmailList(messages=[msg], total_count=1, has_more=False)
    message_line = el.to_plain_text().splitlines()[1]
    assert "[unread]" not in message_line


# ── RT-001: MarketBriefing is the SDK's sole prose-exception type — its
# to_markdown() output IS the A2A/AG-UI DataPart value (a2ui/translator.py)
# and the MCP structuredContent {"markdown": ...} payload (routes/mcp.py).
# `prose` and `TextSection.content` are markdown DOCUMENTS, so newlines and
# `|` are content, not delimiters. Two earlier tests asserted the opposite
# (`len(lines) == 2`, i.e. every newline collapsed) and thereby locked in a
# regression that flattened headings, lists, paragraphs and markdown tables
# on the wire. The contract below is the correct one: block structure
# survives, terminal-injection escapes do not.


def test_market_briefing_prose_preserves_multiline_markdown():
    """RT-001 (regression): headings, blank lines, list items and markdown
    table rows in `prose` must reach the wire intact — this is the one
    ContentModel whose rendered text is itself a markdown document."""
    prose = "## Summary\n\n- Freight up 4%\n- Rates flat\n\n| Route | Rate |\n| --- | --- |\n| C5 | 12.3 |"
    mb = MarketBriefing(title="Weekly Update", as_of="2026-06-18", prose=prose)
    out = mb.to_markdown()

    assert prose in out, "prose markdown was altered on the way to the wire"
    assert "## Summary" in out.splitlines()
    assert "| Route | Rate |" in out.splitlines()
    # the pipe is markdown table syntax here, never rewritten to "/"
    assert "/ Route / Rate /" not in out
    assert mb.to_plain_text() == out


def test_market_briefing_text_section_preserves_multiline_markdown():
    """RT-001 (regression): same contract for TextSection.content."""
    mb = MarketBriefing(
        title="Weekly Update",
        as_of="2026-06-18",
        sections=[TextSection(content="Line one\n\nLine two")],
    )
    lines = mb.to_markdown().splitlines()
    # title line, indented first content line, blank line, second content line
    assert lines == ["Weekly Update (2026-06-18)", "  Line one", "", "Line two"]


@pytest.mark.parametrize(
    "payload,banned",
    [
        ("safe\x1b[31mRED", "\x1b"),  # ESC — ANSI escape introducer
        ("safe\x9b2Jclear", "\x9b"),  # CSI — single-byte ANSI introducer
        ("safe\x85nel", "\x85"),  # NEL
        ("safe\x00nul", "\x00"),
        ("safe ls", " "),
        ("safe ps", " "),
    ],
)
def test_market_briefing_prose_still_strips_terminal_injection_chars(payload, banned):
    """RT-001 must not weaken SI-2: preserving \\n as content is not licence
    to pass through escape introducers or the non-\\n line-break set."""
    mb = MarketBriefing(title="T", as_of="2026-06-18", prose=payload)
    out = mb.to_markdown()
    assert banned not in out
    assert "safe" in out


def test_market_briefing_prose_normalises_carriage_returns():
    """A bare CR rewrites the current terminal line (log-injection); CRLF must
    not become a double break. Both normalise to a single \\n."""
    mb = MarketBriefing(title="T", as_of="2026-06-18", prose="a\r\nb\rc")
    out = mb.to_markdown()
    assert "\r" not in out
    assert out.splitlines()[1:] == ["a", "b", "c"]


def test_gh130_all_profile_renderers_sanitize_before_joining():
    """Meta-test (RT-005): a to_plain_text()/to_markdown() implementation
    that joins untrusted values on " | " or "\\n" must call _sanitize_cell
    somewhere in its source — enforced across all 14 Standard Profile types
    so the delimiter-safety contract on ContentModel.to_plain_text cannot
    silently regress to covering only a subset of renderers again."""
    for cls in PROFILE_TYPES:
        source = inspect.getsource(cls.to_plain_text)
        if "to_markdown" in cls.__dict__ or hasattr(cls, "to_markdown"):
            to_markdown = getattr(cls, "to_markdown", None)
            if to_markdown is not None:
                source += inspect.getsource(to_markdown)
        joins_on_structural_delimiter = '" | "' in source or '"\\n"' in source
        if joins_on_structural_delimiter:
            assert "_sanitize_cell(" in source, (
                f"{cls.__name__}.to_plain_text joins on a structural "
                "delimiter without calling _sanitize_cell (GH-130/RT-005)"
            )


# ── RT-006: entity_type is free-form str (not enum/key), and the "titles are
# exempt" carve-out was applied inconsistently — some renderers already
# sanitize a title-shaped field (MarketBriefing's KpiRowSection item.title,
# chart/table data['title']) while eight others left top-level self.title raw.
# A newline in either fabricates an extra row exactly like the GH-130 case.


def test_entity_list_entity_type_embedded_newline_does_not_fabricate_header():
    entity_list = EntityList(
        entity_type="company\nFAKE HEADER",
        items=[EntityItem(id="1", name="Acme")],
    )
    lines = entity_list.to_plain_text().splitlines()
    assert lines[0] == "company FAKE HEADER list"
    assert len(lines) == 3  # header + showing + "- Acme"


def test_entity_list_title_embedded_newline_does_not_fabricate_header():
    entity_list = EntityList(
        entity_type="company",
        title="Top Accounts\nFAKE HEADER",
        items=[EntityItem(id="1", name="Acme")],
    )
    lines = entity_list.to_plain_text().splitlines()
    assert lines[0] == "Top Accounts FAKE HEADER"
    assert len(lines) == 3


def test_market_briefing_title_and_as_of_embedded_newline_do_not_fabricate_line():
    mb = MarketBriefing(title="Weekly\nFAKE LINE", as_of="2026-06-18\nFAKE LINE")
    lines = mb.to_plain_text().splitlines()
    assert len(lines) == 1
    assert "FAKE LINE" in lines[0]


def test_rt006_title_and_entity_type_fields_never_interpolated_raw():
    """Meta-test (RT-006): a presence-only check ('_sanitize_cell appears
    somewhere in this function') cannot catch a renderer that sanitizes one
    field and leaves another raw. For every known-untrusted free-form field
    (title, entity_type, as_of, prose) on a Standard Profile type, every
    source occurrence of the raw attribute access must either be inside a
    sanitiser call or a truthiness check — never bare-interpolated.
    ``prose`` was the RT-001 gap: MarketBriefing.to_markdown() appended it
    raw while every sibling free-form str in the same method was sanitized.

    RT-001: EITHER sanitiser satisfies this — ``_sanitize_cell`` for values
    joined into a delimited single-line render, ``_sanitize_block`` for a
    field whose contract is a markdown document (MarketBriefing.prose). The
    invariant this test owns is 'never interpolated raw'; WHICH helper is
    correct is a per-field judgement pinned by the behavioural tests above,
    not something a source-grep can decide. Hard-coding ``_sanitize_cell``
    here is what forced prose through the wrong sanitiser."""
    field_names = ("title", "entity_type", "as_of", "prose")
    sanitizers = ("_sanitize_cell", "_sanitize_block")
    for cls in PROFILE_TYPES:
        source = inspect.getsource(cls.to_plain_text)
        if "to_markdown" in cls.__dict__:
            source += inspect.getsource(cls.to_markdown)
        for field_name in field_names:
            if field_name not in cls.model_fields:
                continue
            raw = f"self.{field_name}"
            total = source.count(raw)
            if total == 0:
                continue
            # accepts both a bare `_sanitize_x(self.field)` call and the
            # field interpolated inside an f-string argument to it, e.g.
            # `_sanitize_cell(f"{self.field} list")` — no nested parens occur
            # in any of these renderers' title/entity_type/as_of call sites.
            sanitized = sum(
                len(
                    re.findall(
                        rf"{helper}\([^)]*\b{re.escape(raw)}\b[^)]*\)", source
                    )
                )
                for helper in sanitizers
            )
            truthy = source.count(f"if {raw}")
            assert total == sanitized + truthy, (
                f"{cls.__name__} interpolates {raw} outside a sanitiser call "
                "and outside a truthiness check (RT-006)"
            )
            assert sanitized >= 1, (
                f"{cls.__name__} never sanitizes {raw} before rendering (RT-006)"
            )


# ── RT-011: several to_plain_text() renderers layer a SECOND structural
# delimiter of their own on top of the universal " | "/"\n" contract that
# _sanitize_cell's pipe/newline neutralisation does not reach — UserProfile/
# UserList wrap an email in literal "<"/">" , DocumentList wraps a type in
# "("/")", CalendarEvents joins a time range on " – " and a location on
# " @ ". An untrusted value landing next to one of THOSE characters can
# fabricate a second fake pair/entry exactly like the original GH-130 pipe
# case, just through a delimiter the narrower fix didn't cover.


def test_user_profile_display_name_angle_brackets_do_not_fabricate_identity_pair():
    profile = UserProfile(id="1", display_name="a> <ceo@corp.com", email="attacker@evil.com")
    line = profile.to_plain_text().splitlines()[0]
    assert line.count("<") == 1
    assert line.count(">") == 1
    assert line.endswith("<attacker@evil.com>")


def test_user_profile_manager_angle_brackets_do_not_fabricate_identity_pair():
    profile = UserProfile(
        id="1",
        display_name="Alice",
        email="alice@corp.com",
        manager=ManagerRef(id="2", display_name="a> <ceo@corp.com", email="attacker@evil.com"),
    )
    manager_line = [ln for ln in profile.to_plain_text().splitlines() if "manager:" in ln][0]
    assert manager_line.count("<") == 1
    assert manager_line.count(">") == 1
    assert manager_line.endswith("<attacker@evil.com>")


def test_user_list_display_name_angle_brackets_do_not_fabricate_identity_pair():
    users = UserList(
        users=[
            UserSummary(id="1", display_name="a> <ceo@corp.com", email="attacker@evil.com")
        ],
        total_count=1,
        has_more=False,
    )
    line = users.to_plain_text().splitlines()[1]
    assert line.count("<") == 1
    assert line.count(">") == 1
    assert "<attacker@evil.com>" in line


def test_user_list_display_name_em_dash_does_not_fabricate_job_title():
    """RT-004: a user with no job_title carries a display_name containing the
    " — " sequence the renderer itself uses to join a REAL job_title — must
    not read as a forged title for a user who has none."""
    users = UserList(
        users=[
            UserSummary(id="1", display_name="Bob — Chief Executive", email="b@x.com")
        ],
        total_count=1,
        has_more=False,
    )
    line = users.to_plain_text().splitlines()[1]
    assert "—" not in line  # EM DASH — no fabricated " — <title>" join
    assert line.count("<") == 1
    assert line.count(">") == 1


def test_document_list_name_parens_do_not_fabricate_type_suffix():
    doc = DocumentItem(id="1", name="report) (malicious", type="pdf")
    dl = DocumentList(documents=[doc])
    line = dl.to_plain_text().splitlines()[-1]
    assert line.count("(") == 1
    assert line.count(")") == 1
    assert line.endswith("(pdf)")


def test_document_list_type_parens_do_not_break_out_of_suffix():
    doc = DocumentItem(id="1", name="report", type="pdf) (malicious")
    dl = DocumentList(documents=[doc])
    line = dl.to_plain_text().splitlines()[-1]
    assert line.count("(") == 1
    assert line.count(")") == 1


def test_document_list_last_modified_parens_do_not_fabricate_type_suffix():
    doc = DocumentItem(
        id="1", name="report", type="pdf", last_modified="2024-01-01 (verified by CEO)"
    )
    dl = DocumentList(documents=[doc])
    line = dl.to_plain_text().splitlines()[-1]
    assert line.count("(") == 1
    assert line.count(")") == 1
    assert "(pdf)" in line


# RT-002: a neighbouring field on the SAME rendered line as a renderer-owned
# delimiter pair must be neutralised too — not only the field the delimiter
# visually wraps. UserList/UserProfile interpolate job_title (and
# UserProfile's department) immediately after the literal "<email>" pair on
# one line; an unsanitised job_title/department can fabricate a second fake
# name<email> identity pair on that same line.


def test_user_list_job_title_angle_brackets_do_not_fabricate_identity_pair():
    users = UserList(
        users=[
            UserSummary(
                id="1",
                display_name="Alice",
                email="alice@x.com",
                job_title="Dev> <ceo@corp.com",
            )
        ],
        total_count=1,
        has_more=False,
    )
    line = users.to_plain_text().splitlines()[1]
    assert line.count("<") == 1
    assert line.count(">") == 1
    assert "<alice@x.com>" in line


def test_user_profile_job_title_angle_brackets_do_not_fabricate_identity_pair():
    profile = UserProfile(
        id="1",
        display_name="Alice",
        email="alice@corp.com",
        job_title="Dev> <ceo@corp.com",
    )
    text = profile.to_plain_text()
    assert text.count("<") == 1
    assert text.count(">") == 1
    assert "<alice@corp.com>" in text


def test_user_profile_department_angle_brackets_do_not_fabricate_identity_pair():
    profile = UserProfile(
        id="1",
        display_name="Alice",
        email="alice@corp.com",
        job_title="Dev",
        department="Eng> <ceo@corp.com",
    )
    text = profile.to_plain_text()
    assert text.count("<") == 1
    assert text.count(">") == 1
    assert "<alice@corp.com>" in text


def test_calendar_events_subject_delimiter_chars_do_not_fabricate_range_or_location():
    event = CalendarEvent(
        id="1",
        subject="Standup – 9:00 – 10:00 @ Fake Room",
        start="2026-06-18T09:00:00Z",
        end="2026-06-18T09:30:00Z",
        organizer=NameEmail(name="Bob", email="bob@example.com"),
        web_link="https://example.com/e1",
    )
    events = CalendarEvents(
        events=[event],
        date_range=DateRange(start="2026-06-18T00:00:00Z", end="2026-06-18T23:59:59Z"),
        total_count=1,
        has_more=False,
    )
    event_line = events.to_plain_text().splitlines()[-1]
    assert event_line.count(" – ") == 1
    assert " @ " not in event_line


def test_calendar_events_location_display_name_delimiter_chars_neutralized():
    event = CalendarEvent(
        id="1",
        subject="Standup",
        start="2026-06-18T09:00:00Z",
        end="2026-06-18T09:30:00Z",
        organizer=NameEmail(name="Bob", email="bob@example.com"),
        location=EventLocation(display_name="Room 1 @ Fake – Extra"),
        web_link="https://example.com/e1",
    )
    events = CalendarEvents(
        events=[event],
        date_range=DateRange(start="2026-06-18T00:00:00Z", end="2026-06-18T23:59:59Z"),
        total_count=1,
        has_more=False,
    )
    event_line = events.to_plain_text().splitlines()[-1]
    assert event_line.count(" @ ") == 1  # only the real "loc" separator
    assert event_line.count(" – ") == 1  # only the real start–end separator


def test_calendar_events_subject_brackets_do_not_forge_online_marker():
    event = CalendarEvent(
        id="1",
        subject="Standup [online] fake",
        start="2026-06-18T09:00:00Z",
        end="2026-06-18T09:30:00Z",
        organizer=NameEmail(name="Bob", email="bob@example.com"),
        web_link="https://example.com/e1",
        is_online=False,
    )
    events = CalendarEvents(
        events=[event],
        date_range=DateRange(start="2026-06-18T00:00:00Z", end="2026-06-18T23:59:59Z"),
        total_count=1,
        has_more=False,
    )
    event_line = events.to_plain_text().splitlines()[-1]
    assert "[online]" not in event_line


# ── RT-005: three renderers were left with the universal pipe/line-break
# treatment only, despite layering their own structural punctuation on top
# just like the RT-011 cases above — MarketBriefing's own "(as_of)" plus its
# CHART/TABLE section titles sharing that line, TimeSeriesChart's " @ "/"→"/
# "(...)" join, and WaterfallChart's segment label sharing a line with the
# segment's "(type)" pair.


def test_market_briefing_as_of_parens_do_not_fabricate_extra_header():
    mb = MarketBriefing(title="Weekly Briefing", as_of="2026-06-18) FAKE HEADER (ignored")
    line = mb.to_plain_text().splitlines()[0]
    assert line.count("(") == 1
    assert line.count(")") == 1
    assert line.endswith("ignored)")


def test_market_briefing_title_parens_do_not_fabricate_extra_header():
    mb = MarketBriefing(title="Weekly) FAKE (Briefing", as_of="2026-06-18")
    line = mb.to_plain_text().splitlines()[0]
    assert line.count("(") == 1
    assert line.count(")") == 1
    assert line.endswith("(2026-06-18)")


def test_market_briefing_chart_section_title_parens_do_not_fabricate_section():
    mb = MarketBriefing(
        title="Weekly",
        as_of="2026-06-18",
        sections=[
            ChartSection(chart_type="time_series", data={"title": "Real): CHART (bar_chart"}),
        ],
    )
    chart_line = next(
        line for line in mb.to_plain_text().splitlines() if line.strip().startswith("CHART")
    )
    assert chart_line.count("(") == 1
    assert chart_line.count(")") == 1


def test_market_briefing_table_section_title_parens_neutralized():
    mb = MarketBriefing(
        title="Weekly",
        as_of="2026-06-18",
        sections=[TableSection(data={"title": "Holdings (fabricated) suffix"})],
    )
    table_line = next(
        line for line in mb.to_plain_text().splitlines() if line.strip().startswith("TABLE")
    )
    assert "(" not in table_line
    assert ")" not in table_line


def test_time_series_chart_date_confusables_do_not_fabricate_extra_points():
    chart = TimeSeriesChart(
        chart_type="line",
        title="Revenue",
        data=[
            TimeSeriesDataPoint(date="2026-01-01) (999 points", value=1.0),
            TimeSeriesDataPoint(date="2026-06-01 @ Fake → 3", value=2.0),
        ],
    )
    line = chart.to_plain_text().splitlines()[-1]
    assert line.count("(") == 1
    assert line.count(")") == 1
    assert line.count(" @ ") == 2  # only the two real value/date separators
    assert line.count("→") == 1  # only the real first→last separator
    assert line.endswith("(2 points)")


def test_waterfall_chart_segment_label_parens_do_not_fabricate_type_suffix():
    chart = WaterfallChart(
        title="Bridge",
        segments=[
            WaterfallSegment(label="Opening) (loss", value=10.0, type="initial", cumulative=10.0),
        ],
    )
    line = chart.to_plain_text().splitlines()[-1]
    assert line.count("(") == 1
    assert line.count(")") == 1
    assert line.endswith("(initial)")


# ── GH-130 delimiter safety: class-closing enforcement ──────────────────────
#
# The two tests below replaced a growing list of hand-written
# one-renderer-one-delimiter cases. That list could only ever assert the
# instances someone had already thought of, which is why four consecutive
# review rounds each discovered one more uncovered renderer/delimiter pair
# (pipe → <>/()/–@ → @→() → ,=:[]—). These two close the CLASS: the first
# from the template side, the second from the call-site side. Neither
# enumerates a delimiter by hand.


def _renderer_template_punctuation() -> dict[str, set[str]]:
    """Every punctuation character appearing in a string literal inside a
    ``to_plain_text``/``to_markdown`` body in content_types.py, mapped to the
    literals it came from. Read from the AST so it cannot drift from source."""
    import ast

    source_path = inspect.getsourcefile(content_types_module)
    assert source_path is not None
    with open(source_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in ("to_plain_text", "to_markdown"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                for ch in sub.value:
                    if not ch.isalnum() and not ch.isspace():
                        found.setdefault(ch, set()).add(sub.value)
    return found


def test_every_renderer_separator_is_neutralised():
    """Template side: no renderer may insert a punctuation character that is
    neither neutralised by the separator maps nor listed in the
    documented _NON_SEPARATOR_GLYPHS allow-list.

    A future renderer introducing a new separator (say a "::" join or a "{}"
    pair) fails here at build time instead of shipping a fabrication hole for
    the next review round to find."""
    allowed = set(_STRUCTURAL_SEPARATORS) | set(_NON_SEPARATOR_GLYPHS)

    unaccounted = {
        ch: sorted(literals)
        for ch, literals in _renderer_template_punctuation().items()
        if ch not in allowed
    }
    assert not unaccounted, (
        "renderer template punctuation is neither neutralised nor "
        f"allow-listed: {unaccounted}. Either add the character to "
        "_BARE_SEPARATORS/_SPACED_SEPARATORS (if a value landing next to "
        "it could "
        "fabricate a field boundary) or to _NON_SEPARATOR_GLYPHS with a "
        "reason it cannot."
    )


def test_separator_replacements_do_not_map_onto_another_separator():
    """A neutralised character must not be rewritten INTO another separator,
    which would just move the fabrication one delimiter along."""
    pairs = [(chr(cp), r) for cp, r in _BARE_SEPARATORS.items()]
    pairs += list(_SPACED_SEPARATORS.items())
    for source, replacement in pairs:
        assert replacement is not None
        collisions = set(replacement) & set(_STRUCTURAL_SEPARATORS)
        assert not collisions, (
            f"{source!r} is neutralised to {replacement!r}, which "
            f"contains separator(s) {collisions}"
        )


# Fields whose declared contract is a markdown DOCUMENT, not a delimited
# cell — the RT-001 carve-out routed through _sanitize_block. Newlines and
# pipes are content there, so they are held benign in both renders rather
# than being exempted from the assertion.
_BLOCK_FIELDS = {("MarketBriefing", "prose"), ("TextSection", "content")}

_BENIGN = "AAA"

_SPACED = "".join(_SPACED_SEPARATORS)
# Several payloads, because one shape does not exercise the whole rule. A
# spaced separator is structural when whitespace sits on EITHER side of it,
# and the other half of that whitespace can come from the renderer's own
# template — so a value that merely ENDS with " \u2013" is as dangerous as one
# carrying " \u2013 " in the middle. A probe that only ever embeds separators
# mid-string would pass a sanitiser that wrongly required space on both sides
# within the value.
_HOSTILE_PAYLOADS = {
    # dense mid-string: every separator, plus the full str.splitlines() break
    # set and an ANSI introducer
    "midstring": (
        "x|y\u2502z\uff5cw <a@b> (c) [d] e:f g,h i=j k\u2013l m\u2014n o\u2192p"
        "\nq\rr\x0bs\x0ct\x1cu\x85v\u2028w\u2029x\x1b[31my"
    ),
    # leading boundary: value STARTS with a separator, template supplies the
    # preceding space
    "leading": "".join(f"{c} FAKE " for c in _SPACED),
    # trailing boundary: value ENDS with a separator, template supplies the
    # following space
    "trailing": "".join(f" FAKE {c}" for c in _SPACED),
    # the value is nothing but separators — both boundaries at once
    "bare": _SPACED,
}


def _build(annotation: Any, *, probe: str, owner: str, field: str) -> Any:
    """Construct a minimal valid value for a pydantic annotation, putting
    ``probe`` in every ``str`` slot. Generic so a newly registered
    ContentModel is covered without touching this test."""
    import typing

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is Annotated:
        return _build(args[0], probe=probe, owner=owner, field=field)
    if origin is Literal:
        return args[0]
    if origin in (Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        # prefer str so the slot is attacker-reachable; else first member
        for candidate in non_none:
            if candidate is str:
                return probe
        return _build(non_none[0], probe=probe, owner=owner, field=field)
    if origin in (list, tuple):
        inner = args[0] if args else str
        inner_args = typing.get_args(inner)
        # a discriminated-union list: build one element per member so every
        # branch of the renderer's isinstance chain is exercised
        if typing.get_origin(inner) is Annotated:
            base = inner_args[0]
            if typing.get_origin(base) in (Union, types.UnionType):
                return [
                    _build(m, probe=probe, owner=owner, field=field)
                    for m in typing.get_args(base)
                ]
        return [_build(inner, probe=probe, owner=owner, field=field)]
    if origin is dict:
        val_t = args[1] if len(args) > 1 else str
        if val_t is Any:
            # ChartSection/TableSection read data["title"]; keep the key
            # literal and attack the value
            return {"title": probe, probe: probe}
        return {probe: _build(val_t, probe=probe, owner=owner, field=field)}
    if annotation is Any:
        return probe
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _build_model(annotation, probe=probe)
    if annotation is str:
        return probe
    if annotation is bool:
        return False
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    return probe


def _build_model(model: type[BaseModel], *, probe: str) -> BaseModel:
    kwargs: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        # markdown-document fields stay benign in BOTH renders (RT-001)
        field_probe = _BENIGN if (model.__name__, name) in _BLOCK_FIELDS else probe
        kwargs[name] = _build(
            info.annotation, probe=field_probe, owner=model.__name__, field=name
        )
    return model(**kwargs)


def _separator_occurrences(text: str) -> "collections.Counter[str]":
    """Count RAW, UNCONDITIONAL occurrences of every structural separator
    character in a render — an oracle independent of whatever predicate
    ``safe_cell_text`` uses to decide what to neutralise (RT-010).

    The previous version re-derived ``_SPACED_SEPARATOR_RE``'s own
    whitespace-adjacency predicate character-for-character, so a compact
    separator neither implementation neutralised nor this oracle counted, by
    construction — the sanitiser and its own enforcement test agreed on the
    bug. A plain, unfiltered character count has no opinion on adjacency, so
    a compact separator the sanitiser fails to neutralise now shows up as a
    count mismatch instead of vanishing from both sides at once."""
    return collections.Counter(ch for ch in text if ch in _STRUCTURAL_SEPARATORS)


@pytest.mark.parametrize("payload", sorted(_HOSTILE_PAYLOADS))
@pytest.mark.parametrize(
    "model", sorted(_REGISTRY.values(), key=lambda m: m.__name__), ids=lambda m: m.__name__
)
def test_untrusted_value_cannot_alter_render_structure(model, payload):
    """Call-site side: for EVERY registered ContentModel, a hostile value in
    every string slot must not change how many separators the render
    contains. Separator counts come from the renderer's own template, which
    is identical across the two renders — so any difference means an
    untrusted value fabricated a field boundary.

    This is what makes forgetting _sanitize_cell on a new field a build
    failure rather than a finding for the next review round."""
    benign_text = _build_model(model, probe=_BENIGN).to_plain_text()
    hostile_text = _build_model(
        model, probe=_HOSTILE_PAYLOADS[payload]
    ).to_plain_text()

    benign_counts = _separator_occurrences(benign_text)
    hostile_counts = _separator_occurrences(hostile_text)

    # "@" is excluded: its compact form is a deliberate, documented residual
    # (RT-010) — a real email address must survive a render intact, and
    # safe_cell_text has no field-level information to tell a genuine compact
    # email apart from a hostile compact "@" elsewhere, so it is not
    # neutralised. That trade-off is pinned by dedicated tests instead
    # (test_user_profile_*/test_user_list_*/test_calendar_events_location_*
    # above, plus tests/test_redact.py's RT-010 block) rather than by this
    # generic parity loop. Every OTHER structural separator has no such
    # exception and must have identical raw counts under attack.
    for sep in sorted(_STRUCTURAL_SEPARATORS - {"@"}):
        assert hostile_counts[sep] == benign_counts[sep], (
            f"{model.__name__}.to_plain_text() leaked separator {sep!r}: "
            f"{benign_counts[sep]} in the benign render vs "
            f"{hostile_counts[sep]} under attack — an untrusted value "
            f"fabricated a field boundary.\nbenign:\n{benign_text}\n"
            f"hostile:\n{hostile_text}"
        )

    # line count is structure too: no untrusted value may invent a row
    assert len(hostile_text.splitlines()) == len(benign_text.splitlines()), (
        f"{model.__name__}.to_plain_text() fabricated a row under attack:\n"
        f"benign:\n{benign_text}\nhostile:\n{hostile_text}"
    )
