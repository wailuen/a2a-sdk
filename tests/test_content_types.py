"""Registry enforcement: component-name uniqueness, frozen-profile clean
registration, and re-registration idempotency (DESIGN.md §4.3)."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from pydantic import BaseModel, ValidationError

from agent_sdk.models.content_types import (
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
    FirstLastRange,
    FundPerformance,
    KpiCard,
    KpiRowSection,
    MarketBriefing,
    MetricItem,
    MultiCategoryChart,
    MultiCategorySummary,
    MultiCategoryPeriod,
    NameEmail,
    TableSection,
    UserList,
    UserProfile,
    UserSummary,
    WaterfallChart,
    WaterfallSegment,
    _REGISTRY,
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
