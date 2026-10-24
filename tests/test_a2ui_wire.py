"""Wire-conformance tests for Standard Profile v1 field contracts.

B1: KpiTrend collapses to direction string on the wire (MetricItem.trend).
B2: TimeSeriesChart emits no top-level `series` and no per-point `series`.
C1: translate() produces the canonical three-message open sequence.
D1: no deleteSurface is emitted (GH-214 ruling https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

from tests._compact_schema import top_level_keys

from agent_sdk.a2ui.translator import A2uiCapabilities, translate
from agent_sdk.models.content_types import (
    ContentModel,
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
    """Each data point on the wire must have exactly {{date, value, label?}}.
    ``value`` is required-but-nullable on the frozen contract — a data gap is
    a real point (``value: null``), not an absent key (LRN-110)."""
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
    assert pt1["value"] is None, "value=None must survive as a literal null, not an absent key"
    assert "label" not in pt1  # label absent is correctly excluded (genuinely optional)
    assert "series" not in pt1


# ── C1: translate() output structure ────────────────────────────────────────

def test_translate_output_structure():
    """translate() must return a list of >= 3 dicts, first element has
    type 'createSurface' with catalogId, and no 'deleteSurface' message is present (GH-214)."""
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

    # GH-214: the SDK never closes a surface in the artifact that created it
    assert not [m for m in result if isinstance(m, dict) and "deleteSurface" in m]

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


def test_translate_returns_three_messages():
    """translate() must return exactly 3 messages: createSurface, updateComponents,
    updateDataModel; no deleteSurface (GH-214 ruling
    https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762)."""
    payload = KpiCard(
        metrics=[MetricItem(label="NAV", value=250_000_000)],
    )
    result = translate(payload)
    assert result is not None
    assert len(result) == 3, f"expected 3 messages, got {len(result)}"

    assert "createSurface" in result[0]
    assert "updateComponents" in result[1]
    assert "updateDataModel" in result[2]
    assert not any("deleteSurface" in m for m in result)


def test_split_a2ui_delivery_is_removed():
    """GH-214: there is no open/close split any more."""
    import agent_sdk.a2ui.translator as translator_module

    assert not hasattr(translator_module, "split_a2ui_delivery")


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
    assert "Reference shapes of tool output" in section, (
        f"section must contain the reference-shapes heading; got:\n{section}"
    )
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


def test_apply_data_model_update_missing_deletes_key():
    """M3 (A2UI v0.9.1): Passing MISSING deletes the key at *pointer*."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {"title": "keep"}
    apply_data_model_update(model, "/title", MISSING)
    assert "title" not in model


def test_apply_data_model_update_missing_deletes_nonexistent_leaf_is_noop():
    """M3: Deleting an absent leaf key must not raise."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {"other": "value"}
    apply_data_model_update(model, "/title", MISSING)
    assert model == {"other": "value"}


def test_apply_data_model_update_missing_deletes_nested_path():
    """M3: Deleting a nested pointer removes only the leaf key, leaving
    intermediate containers and sibling keys intact."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {"metrics": {"label": "IRR", "value": 0.18}}
    apply_data_model_update(model, "/metrics/value", MISSING)
    assert model["metrics"] == {"label": "IRR"}


def test_apply_data_model_update_missing_scaffolds_absent_intermediate_path():
    """RT-001: Deleting a nested pointer whose parent segments are absent
    scaffolds those intermediate dicts, mirroring the console renderer's
    pointerSet unconditional-traverse-then-branch shape (a2ui.js) — server
    and renderer now converge on identical wire input. The leaf itself is
    still never created (pop on an absent key is a no-op)."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {}
    apply_data_model_update(model, "/a/b/c", MISSING)
    assert model == {"a": {"b": {}}}


def test_apply_data_model_update_empty_first_segment_writes_empty_string_key():
    """RT-EMPTY-SEGMENT-001 (round 5, corrects the over-broad "//" guard): a
    "//" prefix (empty FIRST segment) is NOT a component-root escape. Per RFC
    6901 it addresses the empty-string key — an ordinary key WITHIN the
    component-root model (model[""]), never the envelope or a parent. A prior
    revision rejected ONLY this one spelling while the helper accepted every
    equivalent spelling that reaches the same empty-string key ("/a//b",
    "/a/"), so the guard provided no boundary. "//"-prefixed pointers now
    converge with the renderer's pointerSet (which writes {"": {"bar": "X"}} —
    see the empty-segment convergence-table rows for the live cross-check).
    Genuine ".." parent-escape tokens remain rejected — see
    test_apply_data_model_update_still_rejects_genuine_dotdot_segment."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {}
    apply_data_model_update(model, "//bar", "X")
    assert model == {"": {"bar": "X"}}, (
        f"'//bar' must write the empty-string key, matching the renderer; got {model!r}"
    )


def test_apply_data_model_update_accepts_tilde_escaped_slash_as_literal_key():
    """RT-JSON-POINTER-001 (corrected): a ~1-encoded "/" is a literal key
    CHARACTER, never a path separator, so "/foo~1../bar" decodes to the two
    tokens ["foo/..", "bar"] — a legitimate RFC 6901 nested write to the
    literal key "foo/..", NOT a parent-escape. The prior revision rejected it
    via an over-broad `"/.." in t` / `t.startswith("../")` substring check
    that could only ever fire on such ~1-formed literal keys (a decoded "/"
    comes only from ~1); the check now rejects ONLY a decoded token EQUAL to
    "..". This helper must ACCEPT the pointer and set the literal key, matching
    the console renderer's pointerSet (which writes {"foo/..": {"bar": ...}} —
    see the live cross-check test below)."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {}
    apply_data_model_update(model, "/foo~1../bar", "X")
    assert model == {"foo/..": {"bar": "X"}}, (
        f"'/foo~1../bar' must set literal key 'foo/..', matching the renderer; got {model!r}"
    )


def test_apply_data_model_update_allows_keys_that_merely_contain_dotdot():
    """RT-002: the raw pre-decode check used a naive '/..' substring match
    that over-rejected legitimate RFC 6901 keys which merely CONTAIN '..'
    textually (e.g. '..foo', '..bar') as if they were a parent-escape
    segment. Only a genuine '..' PATH SEGMENT (a decoded token equal to
    '..') is a parent-escape attempt — the per-token check below the raw
    check already enforces that correctly. '..foo' and '..bar' must be
    settable, ordinary object keys."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {}
    apply_data_model_update(model, "/..foo", 1)
    assert model == {"..foo": 1}

    model2: dict = {}
    apply_data_model_update(model2, "/a/..bar", 1)
    assert model2 == {"a": {"..bar": 1}}


def test_apply_data_model_update_still_rejects_genuine_dotdot_segment():
    """RT-002: dropping the over-broad raw '/..' substring check must not
    reopen the real parent-escape hole — a genuine '..' path segment
    (/foo/../bar decodes to the token '..') is still rejected by the
    post-decode per-token check."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    with pytest.raises(ValueError, match="escapes"):
        apply_data_model_update({}, "/foo/../bar", "bad")

    with pytest.raises(ValueError, match="escapes"):
        apply_data_model_update({}, "/..", "bad")


def test_apply_data_model_update_rejects_non_root_pointer():
    """M2: Pointer not starting with / must raise ValueError."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    with pytest.raises(ValueError, match="root-relative"):
        apply_data_model_update({}, "title", "bad")


def test_apply_data_model_update_empty_pointer_replaces_whole_model():
    """RT-001 (corrects RT-003): A2UI v0.9.1 explicitly overrides RFC 6901 —
    "omit path or use / to replace the whole data model" — for BOTH the
    omitted/empty-string path and "/". A dict value replaces every existing
    key; nothing from the stale model survives."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {"stale": "keep-me-out"}
    apply_data_model_update(model, "", {"fresh": "value"})
    assert model == {"fresh": "value"}


def test_apply_data_model_update_slash_pointer_replaces_whole_model():
    """RT-001: "/" must behave IDENTICALLY to the omitted/empty-string form
    per the A2UI spec's explicit override of RFC 6901 — NOT as an ordinary
    one-segment pointer addressing model[""]. A prior revision matched the
    console renderer's pointerSet output for "/" (model[""]) instead of the
    spec; pointerSet itself is non-conformant here, so mirroring it just
    relocated the bug from the renderer to the server. See the pinned
    divergence tests below for the (intentional) pointerSet mismatch."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {"stale": "keep-me-out"}
    apply_data_model_update(model, "/", {"fresh": "value"})
    assert model == {"fresh": "value"}


def test_apply_data_model_update_empty_and_slash_pointer_are_symmetric():
    """RT-001: the two spec-named whole-model-replace spellings must produce
    byte-for-byte identical results from identical inputs."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    m_empty: dict = {"a": 1}
    m_slash: dict = {"a": 1}
    apply_data_model_update(m_empty, "", {"b": 2})
    apply_data_model_update(m_slash, "/", {"b": 2})
    assert m_empty == m_slash == {"b": 2}


def test_apply_data_model_update_empty_pointer_missing_value_is_noop():
    """RT-001: MISSING (omitted value) on a whole-model-replace pointer is a
    no-op, matching the console renderer's real pointerSet output —
    pointerSet(doc, "", undefined) returns doc unchanged (verified: the
    empty-tokens branch is `value === undefined ? doc : value`)."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {"a": 1}
    apply_data_model_update(model, "", MISSING)
    assert model == {"a": 1}


def test_apply_data_model_update_slash_pointer_missing_value_is_noop():
    """RT-001: "/" must match the "" MISSING no-op, by the same symmetry
    the spec requires for the set case."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {"a": 1}
    apply_data_model_update(model, "/", MISSING)
    assert model == {"a": 1}


def test_apply_data_model_update_empty_pointer_rejects_non_dict_value():
    """RT-001: this helper mutates *model* in place and cannot reassign the
    caller's reference, so a non-dict whole-model value (which pointerSet
    would happily return verbatim, replacing the reference wholesale) cannot
    be honored — raise a clear error instead of silently doing nothing or
    writing a nonsensical shape."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    with pytest.raises(ValueError, match="object"):
        apply_data_model_update({}, "", "not-a-dict")


def test_apply_data_model_update_slash_pointer_rejects_non_dict_value():
    """RT-001: "/" must reject non-dict whole-model values exactly like ""."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    with pytest.raises(ValueError, match="object"):
        apply_data_model_update({}, "/", ["not", "a", "dict"])


def test_apply_data_model_update_nested_path():
    """M2+M3: Nested pointer /a/b creates intermediate dicts and sets leaf."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {}
    apply_data_model_update(model, "/metrics/0", {"label": "IRR", "value": 0.18})
    assert model["metrics"]["0"] == {"label": "IRR", "value": 0.18}


def test_apply_data_model_update_numeric_token_is_dict_key_not_list_index():
    """RT-002: A numeric token is a literal string dict key, never a list
    index — this diverges from a2ui.js's pointerSet, which builds a JS array
    for a numeric segment. Documented, latent (translate() only ever emits
    the flat /root pointer), not a live bug."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {}
    apply_data_model_update(model, "/metrics/0/value", 0.18)
    assert model == {"metrics": {"0": {"value": 0.18}}}
    assert not isinstance(model["metrics"], list)


def test_apply_data_model_update_set_through_existing_list_node_raises():
    """RT-002: setting a value through a pre-existing list-valued node
    raises rather than splicing/indexing into it, unlike pointerSet."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {"metrics": [{"label": "IRR"}]}
    with pytest.raises(ValueError, match="dict"):
        apply_data_model_update(model, "/metrics/0/value", 0.18)


def test_apply_data_model_update_missing_through_existing_list_node_is_noop():
    """RT-002a: deleting through a pre-existing list-valued node is a silent
    no-op (same no-scaffolding-for-existing-non-dict-nodes rule), not a
    splice."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {"metrics": [{"label": "IRR"}]}
    apply_data_model_update(model, "/metrics/0/value", MISSING)
    assert model == {"metrics": [{"label": "IRR"}]}


def test_apply_data_model_update_set_through_scalar_intermediate_raises():
    """RT-002b: setting a value through a pre-existing SCALAR (non-dict,
    non-list) intermediate node raises here — unlike pointerSet, which
    overwrites the scalar with {} and continues (verified:
    pointerSet({"a": 5}, "/a/b/c", "X") -> {"a": {"b": {"c": "X"}}},
    discarding the 5)."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {"a": 5}
    with pytest.raises(ValueError, match="dict"):
        apply_data_model_update(model, "/a/b/c", "X")
    assert model == {"a": 5}, "a rejected set must not mutate the model"


def test_apply_data_model_update_missing_through_scalar_intermediate_preserves_value():
    """RT-002b: deleting through a pre-existing SCALAR intermediate node is a
    silent no-op here, preserving the scalar — unlike pointerSet, which is
    destructive even on delete: pointerSet({"a": 5}, "/a/b/c", undefined)
    overwrites the 5 with {} while walking, then no-ops the (now-absent)
    leaf, yielding {"a": {"b": {}}}. This is the scalar-node counterpart to
    test_apply_data_model_update_missing_scaffolds_absent_intermediate_path
    (which scaffolds only because the intermediate keys are ABSENT, not
    because a pre-existing value is overwritten)."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    model: dict = {"a": 5}
    apply_data_model_update(model, "/a/b/c", MISSING)
    assert model == {"a": 5}, "a no-op delete must not overwrite the pre-existing scalar"


# ── RT-001: A2UI spec whole-model-replace oracle (independent of pointerSet) ─
#
# Every test in the sections above and below checks apply_data_model_update
# for agreement with a SECOND implementation — the console renderer's
# pointerSet (a2ui.js). RT-002 fixed pointerSet's own non-conformance for
# "/" at the root (pointerTokens("/") now folds to the empty token list,
# same as pointerTokens("")), so the two implementations no longer merely
# happen to agree — they are both independently conformant to the spec
# (see harness a2ui-advisor.md's authoritative A2UI reference,
# `updateDataModel` section): "Omit `path` or use `"/"` to replace the whole
# data model." A suite that only checks renderer-convergence could stay
# fully green while both implementations violate the spec's literal words,
# with nothing ever asserting what the spec itself requires — exactly what
# let "/" handling churn through two reverted, pointerSet-anchored revisions
# (see translator.py's apply_data_model_update docstring, RT-002) with no
# spec anchor to settle the argument either way.
#
# The tests below assert the spec's literal semantics directly, as their own
# oracle, independent of pointerSet — and pin CONFORMANCE: both the
# omitted/empty-string path and "/" perform a genuine whole-model replace.


def test_apply_data_model_update_conforms_to_a2ui_spec_on_slash_whole_model_replace():
    """RT-001/RT-002: per the A2UI spec, path "/" must replace the whole data
    model. apply_data_model_update does this directly, as its own oracle
    independent of pointerSet — and, since RT-002 fixed pointerSet's own
    "/" handling too, this now also converges with the renderer (see the
    convergence-table section below). Supersedes the old
    "diverges_from_a2ui_spec" pin: the docstring on that test explicitly
    called for flipping it, not deleting it, once '/' becomes conformant."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {"a": 1, "b": 2}
    apply_data_model_update(model, "/", {"replaced": True})

    spec_conformant_whole_model_replace = {"replaced": True}
    assert model == spec_conformant_whole_model_replace, (
        f"'/' must replace the ENTIRE model, not address a child key; got {model!r}"
    )


def test_apply_data_model_update_conforms_to_a2ui_spec_on_omitted_path_whole_model_replace():
    """RT-001: per the A2UI spec, an omitted path must also replace the whole
    data model, identically to "/". apply_data_model_update no longer
    rejects it. Supersedes the old "diverges_from_a2ui_spec" pin for the
    same reason as the "/" counterpart above."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    model: dict = {"a": 1, "b": 2}
    apply_data_model_update(model, "", {"replaced": True})
    assert model == {"replaced": True}, (
        f"omitted path must replace the ENTIRE model; got {model!r}"
    )


def test_apply_data_model_update_whole_model_missing_is_noop_per_spec_no_key_at_path():
    """RT-002: the whole-model + omitted-value intersection is a no-op. The
    spec composes two independent rules — "omit path or use / to replace the
    whole data model" AND "omit value to delete the key AT PATH" — and that
    composition is genuinely ambiguous, not spec-decided: this SDK reads an
    updateDataModel with BOTH omitted as addressing the whole model, where
    there is no single key at path for the delete rule to target, so the
    delete has no referent and the operation no-ops. A spec-literal
    third-party peer could equally read the same composition as
    clear-the-whole-model, so this pin documents the SDK's CHOSEN reading of
    an ambiguous rule, not a spec oracle — it is NOT justified by pointerSet
    convergence (the way the _missing_value_is_noop tests above are); that
    convergence is a consequence of picking the same reading consistently
    across the SDK, not proof the spec mandates it. The SET whole-model case
    already had test_..._conforms_to_a2ui_spec_on_slash_whole_model_replace,
    but the MISSING case was previously pinned only against pointerSet's
    empty-tokens branch — the renderer-over-spec reasoning RT-001 set out to
    eliminate.

    Crucially, no-op here does NOT strand a caller who wants to CLEAR the model:
    the spec-supported clear is an explicit whole-model replace with an empty
    object (value={}), which is honored below. 'Omit value' means delete-a-key,
    not clear-the-model; the two are distinct operations on the wire."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    for pointer in ("", "/"):
        # Omit value on the whole-model path: no single key at path to delete → no-op.
        model: dict = {"kept": 1, "also": 2}
        apply_data_model_update(model, pointer, MISSING)
        assert model == {"kept": 1, "also": 2}, (
            f"whole-model MISSING ({pointer!r}) must no-op: the 'delete key at path' "
            f"rule has no single key when the path is the whole model; got {model!r}"
        )

        # The spec-supported way to CLEAR the model is an explicit empty-object
        # whole-model replace — honored, not silently dropped, so the no-op
        # above does not leave a would-be clear with no path.
        clearable: dict = {"kept": 1, "also": 2}
        apply_data_model_update(clearable, pointer, {})
        assert clearable == {}, (
            f"whole-model replace with an empty object ({pointer!r}) must clear "
            f"the model; got {clearable!r}"
        )


# ── RT-003: apply_data_model_update <-> pointerSet convergence table ─────────
#
# The tests above (and apply_data_model_update()'s docstring) repeatedly claim
# specific points of agreement/divergence with the console renderer's
# pointerSet (agent_sdk/console/static/a2ui.js). Nothing previously
# cross-checked those claims against the real renderer output, so a false
# convergence claim could ship with every test green (w037 RT-001 was exactly
# this: a "converges with the renderer" docstring/CHANGELOG claim for the "/"
# pointer that was, empirically, backwards).
#
# The expected values below are real pointerSet(...) outputs, not a
# hand-derived approximation — each was captured by extracting pointerTokens
# + pointerSet verbatim from a2ui.js and running it under node:
#
#   node -e '
#     const fs = require("fs");
#     const src = fs.readFileSync("agent_sdk/console/static/a2ui.js", "utf8");
#     const tokStart = src.indexOf("function pointerTokens");
#     const tokEnd = src.indexOf("export function pointerGet");
#     const setStart = src.indexOf("function pointerSet");
#     const setEnd = src.indexOf("/* ── fold + paint ── */");
#     eval(src.slice(tokStart, tokEnd) + src.slice(setStart, setEnd));
#     console.log(JSON.stringify(pointerSet(<doc>, "<pointer>", <value>)));
#   '
#
# Re-run that (swap in each row's doc/pointer/value) whenever a2ui.js's
# pointerSet changes, and update this table — that is the "keep the two
# implementations from silently drifting apart" contract this section pins.
# Single-sourced convergence rows (RT-001): the static reference table below
# and the live-node cross-check table further down BOTH parametrize over this
# one constant, so a row can only be added or edited once. Duplicating it would
# reintroduce exactly the static/live drift this whole section exists to guard
# against — add a row to one copy only and the other silently stops verifying
# it. Each `expected` is a real pointerSet(...) output (see the node snippet in
# the header comment). Callers copy `model` before mutating, so the shared
# dicts here are never mutated in place.
_POINTER_SET_CONVERGENCE_ROWS = [
    # /root set on {} — the one shape translate() actually emits.
    ("root-set", {}, "/root", "X", {"root": "X"}),
    # /a/b/c delete-scaffold on {} — absent intermediates are scaffolded
    # as empty dicts by both sides.
    ("delete-scaffold-absent", {}, "/a/b/c", "MISSING", {"a": {"b": {}}}),
    # "" set — pointerSet's empty-tokens branch returns *value* verbatim
    # (a real whole-model overwrite); model.clear()+update() converges.
    ("empty-set-dict", {"stale": 1}, "", {"fresh": True}, {"fresh": True}),
    # "" delete (MISSING) — pointerSet's empty-tokens branch is
    # `value === undefined ? doc : value`, i.e. a no-op; converges.
    ("empty-missing-noop", {"a": 1}, "", "MISSING", {"a": 1}),
    # "/" set — pointerTokens("/") now folds to the empty list too
    # (a2ui.js fix), so "/" converges with "" here exactly as the spec
    # requires: a genuine whole-model overwrite, not a write to model[""].
    ("slash-set-dict", {"stale": 1}, "/", {"fresh": True}, {"fresh": True}),
    # "/" delete (MISSING) — same empty-tokens no-op branch as "".
    ("slash-missing-noop", {"a": 1}, "/", "MISSING", {"a": 1}),
    # RT-JSON-POINTER-001: a ~1-encoded "/" is a literal key CHARACTER, so
    # "/foo~1../bar" is a nested write to the literal key "foo/.." — both
    # sides accept it (the earlier over-broad substring guard wrongly
    # rejected it server-side). pointerSet writes {"foo/..": {"bar": "X"}}.
    ("tilde-slash-literal-key", {}, "/foo~1../bar", "X", {"foo/..": {"bar": "X"}}),
    # RT-EMPTY-SEGMENT-001: an empty path segment addresses the RFC 6901
    # empty-string key (model[""]), NOT a component-root escape. All three
    # spellings converge with pointerSet — the earlier "//" prefix guard
    # rejected only the first while accepting the equivalent middle/trailing
    # forms, so it was no boundary at all.
    ("empty-first-segment", {}, "//bar", "X", {"": {"bar": "X"}}),
    ("empty-middle-segment", {}, "/a//b", "X", {"a": {"": {"b": "X"}}}),
    ("empty-trailing-segment", {}, "/a/", "X", {"a": {"": "X"}}),
]


@pytest.mark.parametrize(
    "label,model,pointer,value,expected", _POINTER_SET_CONVERGENCE_ROWS
)
def test_apply_data_model_update_converges_with_pointer_set_reference(
    label, model, pointer, value, expected
):
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    actual_value = MISSING if value == "MISSING" else value
    m = dict(model)
    apply_data_model_update(m, pointer, actual_value)
    assert m == expected, f"{label}: diverged from the verified pointerSet reference value"


def test_apply_data_model_update_diverges_from_pointer_set_reference_on_scalar_intermediate_delete():
    """RT-002b, pinned as a divergence row (not folded into the convergence
    table above): pointerSet({"a": 5}, "/a/b/c", undefined) really does
    return {"a": {"b": {}}} (verified via the node snippet in this section's
    header comment) — destroying the 5 — while apply_data_model_update()
    no-ops and preserves {"a": 5}. Documented, deliberate (see docstring
    RT-002b), not a bug: kept as its own pinned test so this specific
    divergence cannot silently re-converge (or silently widen) unnoticed."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    pointer_set_reference_result = {"a": {"b": {}}}  # verified via node, see header comment
    model: dict = {"a": 5}
    apply_data_model_update(model, "/a/b/c", MISSING)
    assert model == {"a": 5}
    assert model != pointer_set_reference_result


def test_apply_data_model_update_diverges_from_pointer_set_reference_on_whole_model_replace_non_dict():
    """RT-003 (redteam finding): a THIRD divergence, not previously enumerated
    or pinned — whole-model-replace with a non-dict value. pointerSet's
    empty-tokens branch (`value === undefined ? doc : value`) returns *value*
    verbatim: pointerSet({}, "/", "scalar") really does return "scalar"
    (verified via the node snippet in this section's header comment), so a
    caller assigning `entry.dataModel = pointerSet(...)` ends up with a
    non-object dataModel. apply_data_model_update() is stricter here and
    raises ValueError instead (see docstring RT-002c). Documented, deliberate
    (the server is safer, not just constrained by its in-place-mutator
    shape): kept as its own pinned test so this specific divergence cannot
    silently re-converge (or silently widen) unnoticed."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    pointer_set_reference_result = "scalar"  # verified via node, see header comment
    model: dict = {}
    with pytest.raises(ValueError, match="object"):
        apply_data_model_update(model, "/", pointer_set_reference_result)
    assert model == {}


# ── RT-002: live node cross-check of the pointerSet reference ────────────────
#
# The table and divergence test above assert hand-copied pointerSet(...)
# outputs, captured once by running the node snippet in the header comment
# and pasting the result in. Nothing executes against the live renderer at
# test time, so an edit to a2ui.js's pointerSet would not fail either test
# until a developer manually re-ran the snippet and updated the literals —
# both suites stay green while the two implementations silently diverge.
#
# The tests below close that gap: they extract pointerTokens + pointerSet
# from the real agent_sdk/console/static/a2ui.js source (the same slice the
# header comment documents) and run it under node AT TEST TIME, so a future
# pointerSet edit that changes behavior fails this suite automatically
# instead of drifting away from a stale snapshot.

_NODE_BIN = shutil.which("node")
_A2UI_JS_PATH = Path(__file__).resolve().parent.parent / "agent_sdk" / "console" / "static" / "a2ui.js"
_UNDEFINED_MARKER = "__a2ui_undefined__"

# RT-003: every live cross-check test below is skipif(_NODE_BIN is None), so a
# CI runner without node on PATH leaves all of them silently skipped — a green
# build with the convergence guarantee only conditionally closed, and only the
# hand-copied static reference table (test_apply_data_model_update_converges_
# with_pointer_set_reference, above) actually running. CI is the environment
# this matters for: it is expected to always provide node, so the skip there
# must be a loud failure, not a quiet pass. `CI` is the de facto standard env
# var set by GitHub Actions, GitLab CI, CircleCI, Travis, etc.
_IN_CI = os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def test_live_pointer_set_cross_check_available_in_ci():
    """RT-003: the live a2ui.js pointerSet cross-check tests must not be able
    to silently skip in CI. Locally (not CI), skip when node is absent —
    that's a legitimate dev-machine gap, closed by the hand-copied static
    reference table. In CI, node missing must fail loudly here instead of
    letting every skipif(_NODE_BIN is None) test below quietly disappear."""
    if not _IN_CI:
        pytest.skip("not running in CI; local runs may lack node")
    assert _NODE_BIN is not None, (
        "node is required in CI to run the live a2ui.js pointerSet "
        "cross-check (RT-003) — install node in the CI image; do not let "
        "the convergence guarantee silently skip"
    )

_POINTER_SET_NODE_HARNESS = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const tokStart = src.indexOf("function pointerTokens");
const tokEnd = src.indexOf("export function pointerGet");
const setStart = src.indexOf("function pointerSet");
const setEnd = src.indexOf("/* \\u2500\\u2500 fold + paint \\u2500\\u2500 */");
eval(src.slice(tokStart, tokEnd) + src.slice(setStart, setEnd));
const doc = JSON.parse(process.argv[2]);
const pointer = process.argv[3];
const rawValue = process.argv[4];
const value = rawValue === "__a2ui_undefined__" ? undefined : JSON.parse(rawValue);
process.stdout.write(JSON.stringify(pointerSet(doc, pointer, value)));
"""


def _live_pointer_set(model: dict, pointer: str, value):
    """Run the real a2ui.js pointerSet under node and return its output,
    computed fresh — not a hand-copied literal."""
    assert _NODE_BIN is not None, "caller must skip when node is unavailable"
    value_arg = _UNDEFINED_MARKER if value == "MISSING" else json.dumps(value)
    result = subprocess.run(
        [
            _NODE_BIN, "-e", _POINTER_SET_NODE_HARNESS, "--",
            str(_A2UI_JS_PATH), json.dumps(model), pointer, value_arg,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against a2ui.js")
@pytest.mark.parametrize(
    "label,model,pointer,value,expected", _POINTER_SET_CONVERGENCE_ROWS
)
def test_apply_data_model_update_converges_with_live_pointer_set_reference(
    label, model, pointer, value, expected
):
    """RT-002: recompute the pointerSet reference at test time and check it
    still matches both the hand-copied table above and this helper's output
    — so a pointerSet edit fails here rather than only going stale silently."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    live_reference = _live_pointer_set(dict(model), pointer, value)
    assert live_reference == expected, (
        f"{label}: the hand-copied convergence table has drifted from the "
        f"live a2ui.js pointerSet output ({live_reference!r}); update the table"
    )

    actual_value = MISSING if value == "MISSING" else value
    m = dict(model)
    apply_data_model_update(m, pointer, actual_value)
    assert m == live_reference, f"{label}: diverged from the live pointerSet reference"


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against a2ui.js")
def test_apply_data_model_update_diverges_from_live_pointer_set_reference_on_scalar_intermediate_delete():
    """RT-002: live counterpart of the pinned-divergence test above — recomputes
    the pointerSet reference at test time instead of trusting the hand-copied
    literal, then re-asserts the documented divergence against it."""
    from agent_sdk.a2ui.translator import MISSING, apply_data_model_update

    live_reference = _live_pointer_set({"a": 5}, "/a/b/c", "MISSING")
    assert live_reference == {"a": {"b": {}}}, (
        f"live a2ui.js pointerSet output has changed; got {live_reference!r}"
    )

    model: dict = {"a": 5}
    apply_data_model_update(model, "/a/b/c", MISSING)
    assert model == {"a": 5}
    assert model != live_reference


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against a2ui.js")
def test_apply_data_model_update_diverges_from_live_pointer_set_reference_on_whole_model_replace_non_dict():
    """RT-003: live counterpart of the RT-002c pinned-divergence test above —
    recomputes the pointerSet reference at test time instead of trusting the
    hand-copied literal, then re-asserts the documented divergence against
    it. This is the exact gap RT-003 flagged: a server/renderer divergence on
    identical wire input (whole-model-replace with a non-dict value) that was
    only described in prose, never cross-checked against the live renderer."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    live_reference = _live_pointer_set({}, "/", "scalar")
    assert live_reference == "scalar", (
        f"live a2ui.js pointerSet output has changed; got {live_reference!r}"
    )

    model: dict = {}
    with pytest.raises(ValueError, match="object"):
        apply_data_model_update(model, "/", "scalar")
    assert model == {}
    assert model != live_reference


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against a2ui.js")
def test_apply_data_model_update_diverges_from_live_pointer_set_reference_on_numeric_token():
    """RT-001/RT-002a: live counterpart of the numeric-token divergence pin.

    Before this test, RT-002a was the ONE enumerated divergence
    (RT-002a/RT-002b/RT-002c) with no live node cross-check — it was asserted
    only against a Python-side literal
    (test_apply_data_model_update_numeric_token_is_dict_key_not_list_index),
    while RT-002b and RT-002c each recompute the pointerSet reference at test
    time. The CHANGELOG's 'Each is pinned by a live node cross-check' claim was
    therefore false for RT-002a, and the numeric-token divergence could drift
    silently if a2ui.js's pointerSet numeric handling changed. This closes that
    gap: recompute the renderer reference live and re-assert the divergence.

    The renderer treats a numeric token as a LIST INDEX and builds a JS array
    for that segment; apply_data_model_update treats it as a literal string
    dict key. Documented, latent (translate() only ever emits the flat /root
    pointer), not a live bug."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    live_reference = _live_pointer_set({}, "/metrics/0/value", 0.18)
    assert live_reference == {"metrics": [{"value": 0.18}]}, (
        f"live a2ui.js pointerSet must build a JS array for a numeric token; "
        f"got {live_reference!r}"
    )
    assert isinstance(live_reference["metrics"], list), (
        "the renderer's numeric-token segment must be a JS array"
    )

    model: dict = {}
    apply_data_model_update(model, "/metrics/0/value", 0.18)
    assert model == {"metrics": {"0": {"value": 0.18}}}
    assert isinstance(model["metrics"], dict), (
        "this helper must treat the numeric token as a literal dict key"
    )
    assert model != live_reference


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against a2ui.js")
@pytest.mark.parametrize(
    "pointer,renderer_literal_key_result",
    [
        # A genuine ".." token: RFC 6901 has no parent semantics, so the
        # renderer treats ".." as an ordinary literal key and writes it —
        # pointerSet({}, "/foo/../bar", "X") -> {"foo": {"..": {"bar": "X"}}},
        # pointerSet({}, "/..", "bad") -> {"..": "bad"}. apply_data_model_update
        # DIVERGES here: it conservatively rejects any decoded ".." token as a
        # parent-escape (a deliberate, security-motivated stricter-than-renderer
        # guard — see the docstring's RT-JSON-POINTER-001 note). This pins the
        # divergence RT-JSON-POINTER-001 flagged as previously undocumented, and
        # cross-checks it against the LIVE renderer so it cannot silently drift.
        ("/foo/../bar", {"foo": {"..": {"bar": "X"}}}),
        ("/..", {"..": "X"}),
    ],
)
def test_apply_data_model_update_diverges_from_live_pointer_set_reference_on_genuine_dotdot_token(
    pointer, renderer_literal_key_result
):
    """RT-JSON-POINTER-001: the renderer accepts a ".." token as a literal key;
    this helper rejects it. Deliberate divergence, cross-checked live."""
    from agent_sdk.a2ui.translator import apply_data_model_update

    live_reference = _live_pointer_set({}, pointer, "X")
    assert live_reference == renderer_literal_key_result, (
        f"live a2ui.js pointerSet treats '..' as a literal key; got {live_reference!r}"
    )

    with pytest.raises(ValueError, match="escapes"):
        apply_data_model_update({}, pointer, "X")


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against a2ui.js")
@pytest.mark.parametrize(
    "label,model,pointer,value,expected",
    [
        # RT-002: A2UI v0.9.1's updateDataModel section reads "Omit `path`
        # or use `/` to replace the whole data model" — "/" must behave
        # IDENTICALLY to the omitted "" path: a genuine whole-model replace,
        # not the RFC-6901-literal child key model[""].
        ("slash-whole-model-set", {"a": 1, "b": 2}, "/", {"replaced": True}, {"replaced": True}),
        ("empty-whole-model-set", {"a": 1, "b": 2}, "", {"replaced": True}, {"replaced": True}),
        ("slash-whole-model-delete-noop", {"a": 1}, "/", "MISSING", {"a": 1}),
        ("empty-whole-model-delete-noop", {"a": 1}, "", "MISSING", {"a": 1}),
    ],
)
def test_pointer_set_slash_is_whole_model_replace_matching_omitted_path(
    label, model, pointer, value, expected
):
    """RT-002 (redteam finding, root non-conformance): prior to this fix,
    pointerSet("/", ...) addressed model[""] like any other one-segment
    pointer, diverging from pointerSet("", ...) — which already correctly
    whole-model-replaces — even though the spec names them as the SAME
    operation. pointerTokens("/") must now fold to the empty token list,
    exactly like pointerTokens("")."""
    live_reference = _live_pointer_set(dict(model), pointer, value)
    assert live_reference == expected, (
        f"{label}: pointerSet({pointer!r}, ...) must whole-model-replace "
        f"like the omitted path does, got {live_reference!r}"
    )


# ── SC-C7 (A2UI path): MarketBriefing prose-exception on the A2UI translator ──

def test_market_briefing_translate_value_is_string_not_dict():
    """SC-C7 (A2UI path): translate() for MarketBriefing must place the
    to_markdown() string — not the raw wire() dict — as the updateDataModel
    value.  Pins the prose-exception contract on the A2UI path the same way
    SC-C7 pins it on the MCP path."""
    from agent_sdk.models.content_types import MarketBriefing

    briefing = MarketBriefing(
        title="Morning Brief",
        as_of="2026-06-17",
        prose="Markets open mixed.",
    )
    result = translate(briefing)
    assert result is not None, "translate() must not gate off MarketBriefing (core type)"
    assert len(result) == 3, f"expected 3 messages, got {len(result)}"

    update = result[2]
    assert "updateDataModel" in update, f"message[2] must be updateDataModel; keys: {list(update.keys())}"

    value = update["updateDataModel"]["value"]
    assert isinstance(value, str), (
        f"updateDataModel value for MarketBriefing must be a string (markdown), "
        f"not {type(value).__name__!r}. Got: {value!r}"
    )
    # The markdown string must contain the title and as_of, confirming it is
    # to_markdown() output and not an empty string or an unrelated serialization.
    assert "Morning Brief" in value, (
        f"markdown value must include the briefing title; got: {value!r}"
    )
    assert "2026-06-17" in value, (
        f"markdown value must include as_of date; got: {value!r}"
    )
    # Explicit negative: the raw wire dict would have keys like 'title', 'as_of',
    # 'prose', 'sections' — none of those should appear as top-level JSON keys.
    assert not isinstance(value, dict), "value must never be a dict"


# ── RT-008: catalog string drift guard ──────────────────────────────────────
#
# _FEW_SHOT_EXAMPLES and _COMPACT_SCHEMAS (agent_sdk/a2ui/catalog.py) are
# hand-maintained JSON string literals teaching the LLM each component's wire
# shape. Nothing previously bound them to the actual registered ContentModel
# field contracts — GH-149's fundName lived in both catalog strings and the
# model, outside the frozen profile, and was only caught by a human reading
# the advisor doc. These tests close that gap: a field added, renamed, or
# removed on a registered model without updating the matching catalog string
# now fails CI instead of silently teaching the LLM a wrong wire shape.


def _declared_wire_keys(cls: type) -> set[str]:
    """Field names AND aliases accepted as valid top-level wire keys for
    *cls* — populate_by_name=True means either spelling is legitimate input,
    and wire() emits the alias when one is declared."""
    keys: set[str] = set()
    for name, info in cls.model_fields.items():
        keys.add(name)
        if info.alias:
            keys.add(info.alias)
    return keys


def test_few_shot_examples_keys_match_registered_model_fields():
    """RT-008: every key in each _FEW_SHOT_EXAMPLES JSON literal (besides the
    'component' discriminator) must be a declared field name or alias on that
    component's registered ContentModel — catches a catalog string that
    still teaches a renamed, removed, or typo'd field (the GH-149 drift
    class: fundName lived in both the catalog strings and the model, outside
    the frozen profile, caught only by a human reading the advisor doc)."""
    from agent_sdk.a2ui.catalog import _FEW_SHOT_EXAMPLES
    from agent_sdk.models.content_types import registered_content_types

    by_component = {cls.component: cls for cls in registered_content_types().values()}

    for component, example in _FEW_SHOT_EXAMPLES.items():
        cls = by_component.get(component)
        assert cls is not None, (
            f"_FEW_SHOT_EXAMPLES has an entry for {component!r} but no "
            f"ContentModel is registered under that component name"
        )
        payload = json.loads(example)
        assert "component" not in payload, (
            f"_FEW_SHOT_EXAMPLES[{component!r}] must show the resolved data "
            f"object only, with no sibling 'component' key (GH-179)"
        )
        declared = _declared_wire_keys(cls)
        for key in payload:
            if key == "component":
                continue
            assert key in declared, (
                f"_FEW_SHOT_EXAMPLES[{component!r}] teaches key {key!r} which "
                f"is not a declared field or alias on {cls.__name__} "
                f"(declared: {sorted(declared)}) — catalog string has drifted "
                f"from the model (GH-149 drift class)"
            )


def test_compact_schemas_cover_every_registered_component():
    """RT-008: every registered component must have a _COMPACT_SCHEMAS entry
    — a newly registered type with no compact schema silently falls back to
    the verbose _field_summary() rendering in the LLM system prompt, which is
    a real (if soft) drift the catalog string set should track deliberately,
    not by omission."""
    from agent_sdk.a2ui.catalog import _COMPACT_SCHEMAS
    from agent_sdk.models.content_types import registered_content_types

    for cls in registered_content_types().values():
        assert cls.component in _COMPACT_SCHEMAS, (
            f"{cls.component!r} ({cls.__name__}) is registered but has no "
            f"_COMPACT_SCHEMAS entry in agent_sdk/a2ui/catalog.py"
        )


def test_compact_schemas_keys_match_registered_model_fields():
    """RT-007: every top-level key taught by a _COMPACT_SCHEMAS string must be
    a declared field name or alias on that component's registered
    ContentModel. _COMPACT_SCHEMAS is the larger surface — every registered
    component gets one, versus the handful covered by _FEW_SHOT_EXAMPLES — so
    without this, a stale/renamed/removed field in a compact schema string
    still teaches the LLM a wrong wire shape with no CI signal (the GH-149
    drift class: fundName lived in catalog.py:139 until a human read the
    advisor doc)."""
    from agent_sdk.a2ui.catalog import _COMPACT_SCHEMAS
    from agent_sdk.models.content_types import registered_content_types

    by_component = {cls.component: cls for cls in registered_content_types().values()}

    for component, schema in _COMPACT_SCHEMAS.items():
        cls = by_component.get(component)
        assert cls is not None, (
            f"_COMPACT_SCHEMAS has an entry for {component!r} but no "
            f"ContentModel is registered under that component name"
        )
        declared = _declared_wire_keys(cls)
        for key in top_level_keys(schema):
            assert key in declared, (
                f"_COMPACT_SCHEMAS[{component!r}] teaches key {key!r} which "
                f"is not a declared field or alias on {cls.__name__} "
                f"(declared: {sorted(declared)}) — catalog string has drifted "
                f"from the model (GH-149 drift class)"
            )


# ── RT-004 (catalog.py fix): FundPerformance few-shot must not fabricate pbId ─
#
# GH-149's AC said only "drop fundName" from _FEW_SHOT_EXAMPLES["FundPerformance"],
# but the example was also given a "pbId":"pb-acme-3" literal that was never in
# the original. pbId is the upstream source-system id — provenance the LLM has
# no legitimate way to know, it can only echo a value a tool result actually
# supplied. Leading the sole few-shot example for this type with a fabricable
# identifier teaches the model to invent one, and that invented value is then
# displayed to the end user as real provenance on two surfaces (the console
# card subtitle and FundPerformance.to_plain_text(), both "source <pbId>") —
# the inverse of RT-010's own finding that pbId must never be surfaced as a
# display name.


def test_few_shot_examples_fund_performance_omits_pbid():
    """The FundPerformance few-shot example must demonstrate only metrics the
    model can legitimately produce (irr/tvpi/dpi/rvpi/netIrr/grossIrr/moic/
    asOfDate/nav/asOfQuarter/asOfYear) — never a fabricated pbId value."""
    from agent_sdk.a2ui.catalog import _FEW_SHOT_EXAMPLES

    payload = json.loads(_FEW_SHOT_EXAMPLES["FundPerformance"])
    assert "pbId" not in payload, (
        "_FEW_SHOT_EXAMPLES['FundPerformance'] must not teach a fabricated "
        f"pbId literal; got payload={payload!r}"
    )


def test_system_prompt_warns_against_inventing_pbid():
    """The FundPerformance line in the LLM system prompt must tell the model
    pbId is upstream provenance to be emitted only when a tool result
    supplied one, never invented — so the compact schema's bare
    '"pbId?":str' shape does not itself invite fabrication now that the
    few-shot example no longer demonstrates one."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section

    section = get_system_prompt_section()
    fp_line = next(
        line for line in section.splitlines() if line.startswith("- FundPerformance")
    )
    assert "pbId" in fp_line and "invent" in fp_line.lower(), (
        f"FundPerformance schema line must warn against inventing pbId; got: {fp_line!r}"
    )


# ── RT-005 (catalog.py fix): _field_summary must not name-match "metadata" ───
#
# _field_summary's skip matched the literal string "metadata" rather than "is
# a field inherited from ContentModel". A domain card that deliberately
# redeclares its OWN metadata field with different (possibly required)
# semantics was silently omitted from the LLM teaching string — the exact
# class of teaching-surface gap LRN-117 was written for, since _field_summary
# is the fallback for every registered type with no _COMPACT_SCHEMAS entry.


class _NoOwnMetadataCard(ContentModel):
    data_type: ClassVar[str] = "test_no_own_metadata_card"
    component: ClassVar[str] = "TestNoOwnMetadataCard"

    title: str

    def to_plain_text(self) -> str:  # pragma: no cover - trivial fallback
        return self.title


class _OwnMetadataCard(ContentModel):
    data_type: ClassVar[str] = "test_own_metadata_card"
    component: ClassVar[str] = "TestOwnMetadataCard"

    title: str
    metadata: str  # deliberately redeclared, required, different type than the base

    def to_plain_text(self) -> str:  # pragma: no cover - trivial fallback
        return self.title


def test_field_summary_excludes_inherited_contentmodel_metadata():
    """A card that does NOT redeclare metadata itself keeps the base-class
    out-of-band field out of the teaching string (RT-003's original intent)."""
    from agent_sdk.a2ui.catalog import _field_summary

    summary = _field_summary(_NoOwnMetadataCard)
    assert "metadata" not in summary, (
        f"inherited ContentModel.metadata must not appear in the summary; got {summary!r}"
    )
    assert "title" in summary


def test_field_summary_includes_own_declared_metadata_field():
    """A card that redeclares metadata as its OWN required domain field must
    have it appear in the teaching string — the name-match skip previously
    dropped it regardless of who declared it."""
    from agent_sdk.a2ui.catalog import _field_summary

    summary = _field_summary(_OwnMetadataCard)
    assert "metadata" in summary, (
        f"own-declared metadata field must appear in the summary; got {summary!r}"
    )
    assert "title" in summary


# ── RT-008 (catalog.py fix): declared-here check must walk the MRO ───────────
#
# The skip keyed on `name not in cls.__annotations__`, which only looks at
# the class's OWN annotations, not any inherited from a domain-declaring
# parent. A two-level subclass of `_OwnMetadataCard` that does not itself
# redeclare `metadata` still owns a domain-declared (not ContentModel-declared)
# `metadata` field via inheritance, and it must not vanish from the summary.


class _OwnMetadataGrandchildCard(_OwnMetadataCard):
    data_type: ClassVar[str] = "test_own_metadata_grandchild_card"
    component: ClassVar[str] = "TestOwnMetadataGrandchildCard"

    def to_plain_text(self) -> str:  # pragma: no cover - trivial fallback
        return self.title


def test_field_summary_includes_domain_metadata_two_levels_deep():
    """A subclass of a card that redeclares metadata, which does not itself
    redeclare it again, must still surface the domain-declared field — the
    MRO walk must not stop at the immediate class's own __annotations__."""
    from agent_sdk.a2ui.catalog import _field_summary

    summary = _field_summary(_OwnMetadataGrandchildCard)
    assert "metadata" in summary, (
        f"domain-declared metadata (inherited two levels) must appear in the "
        f"summary; got {summary!r}"
    )
    assert "title" in summary


# ── RT-001 (catalog.py fix): declared-here check must not silently go blind
# on Python 3.14 (PEP 649) ────────────────────────────────────────────────
#
# The RT-008 test above and its sibling both pass on every interpreter only
# because THIS module carries `from __future__ import annotations`, which
# forces eager stringified annotations at class-creation time regardless of
# Python version — masking the exact gap RT-001 found. A raw
# `vars(klass).get("__annotations__", {})` read returns `{}` on 3.14 for any
# class whose OWN module lacks that future import, so `declared_here` was
# always False there and a domain card's own redeclared `metadata` field was
# silently dropped. The card under test here is defined in a helper module
# that deliberately omits the future import, so this regression cannot be
# masked the way the RT-008 tests above are.


def test_field_summary_includes_own_declared_metadata_field_without_future_annotations():
    """Same contract as test_field_summary_includes_own_declared_metadata_field,
    but the card is declared in a module with no `from __future__ import
    annotations` — the shape that was silently broken on Python 3.14."""
    from agent_sdk.a2ui.catalog import _field_summary
    from tests._rt001_catalog_no_future_annotations_card import (
        OwnMetadataCardNoFutureAnnotations,
    )

    summary = _field_summary(OwnMetadataCardNoFutureAnnotations)
    assert "metadata" in summary, (
        f"own-declared metadata field must appear in the summary even when "
        f"its module has no `from __future__ import annotations`; got {summary!r}"
    )
    assert "title" in summary


def test_system_prompt_forbids_model_written_component_json():
    """GH-169: cards come only from tools with emits=; the section must not
    tell the model to wrap data itself, and must say not to write JSON."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section

    section = get_system_prompt_section()
    assert "wrap it as" not in section.lower()
    assert "do not write component json" in section.lower()
    assert "automatically" in section
    assert "only values" in section
    assert "Examples:" not in section
    assert "never invent" in section


def test_system_prompt_component_shapes_match_registered_models():
    """GH-169 / C-020: every component line in the reworded section teaches only
    keys the registered ContentModel declares."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section
    from agent_sdk.models.content_types import registered_content_types

    by_component = {cls.component: cls for cls in registered_content_types().values()}
    seen = 0
    for line in get_system_prompt_section().splitlines():
        if not line.startswith("- "):
            continue
        name = line[2:].split(":", 1)[0].split(" [", 1)[0].strip()
        cls = by_component.get(name)
        assert cls is not None, f"section lists {name!r} with no registered model"
        schema = line.split(": ", 1)[1].strip()
        declared = _declared_wire_keys(cls)
        for key in top_level_keys(schema):
            assert key in declared, f"{name} section teaches undeclared key {key!r}"
        seen += 1
    assert seen >= len(by_component) - 1


def test_system_prompt_allowed_components_still_filters():
    from agent_sdk.a2ui.catalog import get_system_prompt_section

    section = get_system_prompt_section(["KpiCard"])
    assert "- KpiCard" in section
    assert "- FundPerformance" not in section
