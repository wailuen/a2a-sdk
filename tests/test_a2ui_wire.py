"""Wire-conformance tests for Standard Profile v1 field contracts.

B1: KpiTrend collapses to direction string on the wire (MetricItem.trend).
B2: TimeSeriesChart emits no top-level `series` and no per-point `series`.
C1: translate() produces the canonical four-message sequence.
"""

from __future__ import annotations

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities, translate
from agent_sdk.models.content_types import (
    KpiCard,
    KpiTrend,
    MetricItem,
    TimeSeriesChart,
    TimeSeriesDataPoint,
)


# ── B1: KpiTrend wire field ──────────────────────────────────────────────────

def test_kpi_trend_wire_is_string_when_kpi_trend_object():
    """MetricItem.wire()['trend'] must be a direction string — never a dict —
    even when the Python-side trend is a KpiTrend object."""
    item = MetricItem(
        label="Revenue",
        value=1_000_000,
        trend=KpiTrend(direction="up", delta_pct=12.3, period="QoQ"),
    )
    wire = item.wire()
    assert "trend" in wire, "trend key must be present when trend is set"
    trend_val = wire["trend"]
    assert isinstance(trend_val, str), (
        f"MetricItem.wire()['trend'] must be a string, got {type(trend_val).__name__}: {trend_val!r}"
    )
    assert trend_val in {"up", "down", "flat"}, (
        f"trend string must be 'up', 'down', or 'flat'; got {trend_val!r}"
    )


def test_kpi_trend_wire_direction_matches_kpi_trend_direction():
    """The serialized direction string must match the KpiTrend.direction value."""
    for direction in ("up", "down", "flat"):
        item = MetricItem(
            label="test",
            value=42,
            trend=KpiTrend(direction=direction),
        )
        wire = item.wire()
        assert wire["trend"] == direction, (
            f"expected wire trend '{direction}', got {wire['trend']!r}"
        )


def test_kpi_trend_wire_is_string_when_already_string():
    """Plain string trends must pass through unchanged."""
    for direction in ("up", "down", "flat"):
        item = MetricItem(label="x", value=1, trend=direction)
        wire = item.wire()
        assert wire["trend"] == direction


def test_kpi_trend_wire_absent_when_none():
    """trend=None must result in no 'trend' key on the wire (exclude_none)."""
    item = MetricItem(label="x", value=1, trend=None)
    wire = item.wire()
    assert "trend" not in wire


def test_kpi_trend_wire_never_dict():
    """Exhaustive: no matter what KpiTrend fields are set, wire() must not emit
    a dict for the trend key."""
    combos = [
        KpiTrend(direction="up"),
        KpiTrend(direction="down", delta=5.0),
        KpiTrend(direction="flat", delta_pct=0.0, period="MoM"),
        KpiTrend(direction="up", delta_pct=-3.5, period="YoY"),
    ]
    for kt in combos:
        item = MetricItem(label="m", value=99, trend=kt)
        wire = item.wire()
        assert not isinstance(wire.get("trend"), dict), (
            f"trend must not be a dict; KpiTrend={kt!r}, wire={wire!r}"
        )


def test_kpi_card_wire_metrics_trend_is_string():
    """End-to-end: KpiCard.wire() metrics[] items must have string trends."""
    card = KpiCard(
        title="Portfolio",
        metrics=[
            MetricItem(label="IRR", value=0.18, trend=KpiTrend(direction="up", delta_pct=2.0)),
            MetricItem(label="TVPI", value=1.8, trend="flat"),
            MetricItem(label="DPI", value=0.9, trend=None),
        ],
    )
    wire = card.wire()
    metrics = wire["metrics"]
    assert isinstance(metrics[0]["trend"], str), "KpiTrend object must serialize to string"
    assert metrics[0]["trend"] == "up"
    assert metrics[1]["trend"] == "flat"
    assert "trend" not in metrics[2], "None trend must be absent on wire"


# ── B2: TimeSeriesChart series exclusion ─────────────────────────────────────

def test_time_series_wire_no_top_level_series():
    """TimeSeriesChart.wire() must not include a top-level 'series' key."""
    from agent_sdk.models.content_types import SeriesMeta

    chart = TimeSeriesChart(
        chart_type="line",
        title="Price history",
        data=[
            TimeSeriesDataPoint(date="2026-01-01", value=100.0),
            TimeSeriesDataPoint(date="2026-02-01", value=105.0),
        ],
        series=[SeriesMeta(name="AAPL", points=[])],
    )
    wire = chart.wire()
    assert "series" not in wire, (
        f"top-level 'series' must not appear on wire; keys present: {list(wire.keys())}"
    )


def test_time_series_wire_no_series_in_data_points():
    """TimeSeriesDataPoint.wire() must not include a 'series' key — Profile v1
    data points are {{date, value, label?}} only."""
    chart = TimeSeriesChart(
        chart_type="area",
        title="Multi-series",
        data=[
            TimeSeriesDataPoint(date="2026-01-01", value=10.0, series="A"),
            TimeSeriesDataPoint(date="2026-01-01", value=20.0, series="B"),
        ],
    )
    wire = chart.wire()
    for i, pt in enumerate(wire["data"]):
        assert "series" not in pt, (
            f"data[{i}] must not have 'series' key; got {list(pt.keys())}"
        )


def test_time_series_wire_data_keys_conform_to_profile():
    """Each data point on the wire must have exactly {{date, value}} (label is
    optional but date and value are always present for non-null values)."""
    chart = TimeSeriesChart(
        chart_type="line",
        title="T",
        data=[
            TimeSeriesDataPoint(date="2026-03-01", value=42.0, label="peak"),
            TimeSeriesDataPoint(date="2026-04-01", value=None),
        ],
    )
    wire = chart.wire()
    pt0 = wire["data"][0]
    assert "date" in pt0
    assert "value" in pt0
    assert "label" in pt0  # label is present and not None
    assert "series" not in pt0

    pt1 = wire["data"][1]
    assert "date" in pt1
    # value=None is excluded by exclude_none; that's spec-conformant
    assert "series" not in pt1


# ── C1: translate() output structure ────────────────────────────────────────

def test_translate_output_structure():
    """translate() must return a list of >= 3 dicts, first element has
    type 'createSurface' with catalogId, and a 'deleteSurface' message is present."""
    payload = KpiCard(
        title="Test",
        metrics=[MetricItem(label="Revenue", value=1_000_000, unit="USD")],
    )
    caps = A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])
    result = translate(payload, capabilities=caps)

    assert result is not None, "translate() must not return None for a gated-on type"
    assert isinstance(result, list), "translate() must return a list"
    assert len(result) >= 3, f"expected >= 3 messages, got {len(result)}"

    # First message must be createSurface with catalogId
    first = result[0]
    assert isinstance(first, dict), "first element must be a dict"
    assert "createSurface" in first, f"first element must have createSurface; keys: {list(first.keys())}"
    create = first["createSurface"]
    assert "catalogId" in create, f"createSurface must have catalogId; keys: {list(create.keys())}"
    assert "surfaceId" in create, "createSurface must have surfaceId"

    # Must contain a deleteSurface message
    delete_msgs = [m for m in result if isinstance(m, dict) and "deleteSurface" in m]
    assert delete_msgs, "result must contain a deleteSurface message"

    # All messages must have 'version'
    for i, msg in enumerate(result):
        assert "version" in msg, f"message[{i}] missing 'version' key"


def test_translate_gated_type_returns_none():
    """translate() returns None when the content type is not in the client's
    capabilities (e.g. extended type with core-only capabilities)."""
    from agent_sdk.models.content_types import WaterfallChart, WaterfallSegment

    payload = WaterfallChart(
        title="Waterfall",
        segments=[
            WaterfallSegment(label="Start", value=100.0, type="initial", cumulative=100.0),
        ],
    )
    caps = A2uiCapabilities(tier="core")  # extended=False
    result = translate(payload, capabilities=caps)
    assert result is None, "extended type must be gated off for core-only client"


def test_translate_returns_four_messages():
    """translate() must return exactly 4 messages: createSurface, updateComponents,
    updateDataModel, deleteSurface — per the translator docstring."""
    payload = KpiCard(
        metrics=[MetricItem(label="NAV", value=250_000_000)],
    )
    result = translate(payload)
    assert result is not None
    assert len(result) == 4, f"expected 4 messages, got {len(result)}"

    assert "createSurface" in result[0]
    assert "updateComponents" in result[1]
    assert "updateDataModel" in result[2]
    assert "deleteSurface" in result[3]


def test_translate_update_data_model_carries_wire_value():
    """The updateDataModel message value must be the wire() output of the payload."""
    payload = KpiCard(
        title="Check",
        metrics=[MetricItem(label="IRR", value=0.18, trend=KpiTrend(direction="up"))],
    )
    result = translate(payload)
    assert result is not None
    update = result[2]["updateDataModel"]
    wire_value = update["value"]
    # trend must be a string in the wire value, not an object
    metrics = wire_value.get("metrics", [])
    assert metrics, "wire value must have metrics"
    assert isinstance(metrics[0].get("trend"), str), (
        f"trend in translate wire value must be a string; got {metrics[0].get('trend')!r}"
    )


# ── D1: get_system_prompt_section() ─────────────────────────────────────────

def test_get_system_prompt_section_returns_string_always():
    """get_system_prompt_section() must always return a str — never raises,
    even with an empty registry."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section

    result = get_system_prompt_section()
    assert isinstance(result, str)


def test_get_system_prompt_section_nonempty_when_types_registered():
    """When A2UI content types are registered the section must be non-empty,
    contain an 'A2UI' heading, and list at least one component name.

    The standard Profile types are registered at import time (content_types.py
    module-level loop), so importing KpiCard above already seeds the registry.
    If for any reason the registry is empty the test simply verifies the empty-
    string contract and skips the content assertions."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section
    from agent_sdk.models.content_types import registered_content_types

    section = get_system_prompt_section()
    assert isinstance(section, str)

    if registered_content_types():
        assert section, "section must be non-empty when content types are registered"
        assert "A2UI" in section, f"section must contain 'A2UI'; got:\n{section}"
        # At least one component name must appear (e.g. 'KpiCard')
        assert "KpiCard" in section, (
            f"section must list KpiCard (always registered); got:\n{section}"
        )


# ── H2: get_system_prompt_section() schema + examples ───────────────────────

def test_get_system_prompt_section_includes_examples():
    """H2: section must include a few-shot example block when common types are registered."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section
    from agent_sdk.models.content_types import registered_content_types

    section = get_system_prompt_section()
    if not registered_content_types():
        return  # registry empty in bare test env — skip
    assert "Examples:" in section, f"section must contain 'Examples:'; got:\n{section}"
    assert "KpiCard" in section


def test_get_system_prompt_section_has_compact_schema_for_kpicard():
    """H2: KpiCard entry must show a compact schema, not just a plain field list."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section
    from agent_sdk.models.content_types import registered_content_types

    section = get_system_prompt_section()
    if not registered_content_types():
        return
    # Compact schema has metrics key
    assert "metrics" in section, f"compact schema for KpiCard must mention 'metrics'; got:\n{section}"


# ── M1: SurfaceRegistry duplicate createSurface warning ──────────────────────

def test_surface_registry_open_warns_on_duplicate():
    """M1: Opening an already-open surface must emit a UserWarning."""
    import warnings
    from agent_sdk.a2ui.translator import SurfaceRegistry

    reg = SurfaceRegistry()
    reg.open("surf-1")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reg.open("surf-1")
    assert len(caught) == 1
    assert issubclass(caught[0].category, UserWarning)
    assert "surf-1" in str(caught[0].message)


def test_surface_registry_open_no_warn_for_new_surface():
    """M1: Opening a fresh surface must not emit any warning."""
    import warnings
    from agent_sdk.a2ui.translator import SurfaceRegistry

    reg = SurfaceRegistry()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reg.open("surf-new")
    assert not caught


def test_surface_registry_reopen_after_close_no_warn():
    """M1: Closing then re-opening a surface must not warn."""
    import warnings
    from agent_sdk.a2ui.translator import SurfaceRegistry

    reg = SurfaceRegistry()
    reg.open("surf-x")
    reg.close("surf-x")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reg.open("surf-x")
    assert not caught


# ── M2 + M3: apply_data_model_update ────────────────────────────────────────

def test_apply_data_model_update_sets_value():
    """M3: Passing a value sets the field in the model dict."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {}
    apply_data_model_update(model, "/title", "Hello")
    assert model["title"] == "Hello"


def test_apply_data_model_update_explicit_none_sets_null():
    """M3: Passing None (explicit null) sets the field to None — not a no-op."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {"title": "existing"}
    apply_data_model_update(model, "/title", None)
    assert "title" in model
    assert model["title"] is None


def test_apply_data_model_update_missing_is_noop():
    """M3: Passing MISSING leaves the field unchanged."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {"title": "keep"}
    apply_data_model_update(model, "/title", MISSING)
    assert model["title"] == "keep"


def test_apply_data_model_update_rejects_escape_pointer():
    """M2: Pointer starting with // or containing /.. must raise ValueError."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    with pytest.raises(ValueError, match="escapes"):
        apply_data_model_update({}, "//escape", "bad")

    with pytest.raises(ValueError, match="escapes"):
        apply_data_model_update({}, "/foo/../bar", "bad")


def test_apply_data_model_update_rejects_non_root_pointer():
    """M2: Pointer not starting with / must raise ValueError."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    with pytest.raises(ValueError, match="root-relative"):
        apply_data_model_update({}, "title", "bad")


def test_apply_data_model_update_nested_path():
    """M2+M3: Nested pointer /a/b creates intermediate dicts and sets leaf."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {}
    apply_data_model_update(model, "/metrics/0", {"label": "IRR", "value": 0.18})
    assert model["metrics"]["0"] == {"label": "IRR", "value": 0.18}
