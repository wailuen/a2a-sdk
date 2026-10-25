"""GH-239: bar-chart and generic scalar rows use the C-059 row cap; registry prunes detached nodes.

Runs the REAL ``a2ui.js`` under node against a tiny fake DOM (stub ``api.js``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_gh215_console_generic_renderer import _STUB_API, _surface, _text, _walk

_NODE = shutil.which("node")
_STATIC = Path(__file__).resolve().parent.parent / "agent_sdk" / "console" / "static"

_IN_CI = os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}
needs_node = pytest.mark.skipif(_NODE is None, reason="node not installed")


_CONNECTED_STUB = """
Object.defineProperty(FNode.prototype, "isConnected", {
  get() { let n = this; while (n.parentNode) n = n.parentNode; return n.isRoot === true; },
});
"""


def test_gh239_node_available_in_ci():
    if not _IN_CI:
        pytest.skip("not running in CI; local runs may lack node")
    assert _NODE is not None, "node is required in CI for the a2ui.js live tests"

_HARNESS = """
import { renderA2ui, resetSurfaces, MAX_ROWS, MAX_TEXT, capRows, moreNote, clip } from "./a2ui.js";
import { FNode } from "./api.js";
const transcript = new FNode("div");
transcript.isRoot = true;
const steps = JSON.parse(process.argv[2]);
function dump(n) {
  if (n.tag === "#text") return { text: n.text };
  return { tag: n.tag, cls: n.cls, attrs: n.attrs, children: n.children.map(dump) };
}
const out = [];
for (const s of steps) {
  if (s.reset) resetSurfaces();
  if (s.detach) {
    for (const c of transcript.children) c.parentNode = null;
    transcript.children = [];
  }
  const r = renderA2ui(s.messages || [], { fallbackText: s.fallback === undefined ? "FALLBACK" : s.fallback });
  r.nodes.forEach((n) => transcript.appendChild(n));
  out.push({
    nodes: r.nodes.map(dump),
    notes: r.notes,
    max: MAX_ROWS,
    mounted: transcript.children.map(dump),
    connected: transcript.children.map((c) => c.isConnected),
  });
}
process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path: Path, steps: list[dict]) -> list[dict]:
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "api.js").write_text(_STUB_API + _CONNECTED_STUB)
    (tmp_path / "a2ui.js").write_text((_STATIC / "a2ui.js").read_text())
    (tmp_path / "h.js").write_text(_HARNESS)
    proc = subprocess.run(
        [_NODE, "h.js", json.dumps(steps)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@needs_node
def test_bar_chart_caps_150_bars(tmp_path):
    bars = [{"category": f"C{i}", "value": i + 1} for i in range(150)]
    [r] = _run(tmp_path, [{"messages": _surface("b", "BarChart", {"bars": bars})}])
    cap = r["max"]
    node = r["nodes"][0]
    assert len([x for x in _walk(node) if x.get("tag") == "rect"]) == cap
    assert f"{150 - cap} more" in _text(node)


@needs_node
def test_generic_scalar_rows_capped(tmp_path):
    data = {f"k{i}": i for i in range(150)}
    [r] = _run(tmp_path, [{"messages": _surface("g", "Whatever", data)}])
    cap = r["max"]
    node = r["nodes"][0]
    kv = [x for x in _walk(node) if x.get("tag") == "table" and "tbl-kv" in x["cls"]]
    assert len([x for x in _walk(kv[0]) if x.get("tag") == "tr"]) == cap
    assert f"{150 - cap} more" in _text(node)


@needs_node
def test_registry_prunes_detached_surfaces(tmp_path):
    update = [{"version": "v0.9.1", "updateDataModel": {"surfaceId": "p", "path": "/a", "value": 2}}]
    res = _run(
        tmp_path,
        [
            {"messages": _surface("p", "Thing", {"a": 1})},
            {"detach": True, "messages": update},
        ],
    )
    assert any("unknown/closed surface p" in n for n in res[1]["notes"])
    assert res[0]["connected"] == [True]
    assert res[1]["mounted"] == []


@needs_node
def test_registry_keeps_connected_surfaces(tmp_path):
    update = [{"version": "v0.9.1", "updateDataModel": {"surfaceId": "p", "path": "/a", "value": 2}}]
    res = _run(
        tmp_path,
        [
            {"messages": _surface("p", "Thing", {"a": 1})},
            {"detach": False, "messages": update},
        ],
    )
    assert not any("unknown/closed surface p" in n for n in res[1]["notes"])
    assert res[1]["connected"] == [True]
    assert len(res[1]["mounted"]) == 1
    assert "2" in _text(res[1]["mounted"][0]).split()


def test_registry_comment_names_real_fields():
    src = (_STATIC / "a2ui.js").read_text()
    m = re.search(r"/\* surfaceId -> \{([^}]*)\}", src)
    assert m
    assert "_componentMap" in m.group(1) and "components:" not in m.group(1)


@needs_node
def test_waterfall_caps_segments(tmp_path):
    n = 105
    segs = [{"label": f"S{i}", "value": 1, "cumulative": i + 1, "type": "delta"} for i in range(n)]
    [r] = _run(tmp_path, [{"messages": _surface("w", "WaterfallChart", {"segments": segs})}])
    cap = r["max"]
    node = r["nodes"][0]
    assert len([x for x in _walk(node) if x.get("tag") == "rect"]) == cap
    assert f"{n - cap} more" in _text(node)


@needs_node
def test_multi_category_caps_periods_and_categories(tmp_path):
    n = 105
    periods = [{"period": f"P{i}", "categories": {"a": {"value": 1}}} for i in range(n)]
    [r] = _run(tmp_path, [{"messages": _surface("m", "MultiCategoryChart", {"periods": periods})}])
    cap = r["max"]
    node = r["nodes"][0]
    assert len([x for x in _walk(node) if x.get("tag") == "rect"]) == cap
    assert f"{n - cap} more" in _text(node)

    cats = {f"c{i}": {"value": 1} for i in range(n)}
    [r] = _run(tmp_path, [{"messages": _surface("m2", "MultiCategoryChart", {"periods": [{"period": "P", "categories": cats}]})}])
    node = r["nodes"][0]
    assert len([x for x in _walk(node) if x.get("tag") == "rect"]) == cap
    assert f"{n - cap} more" in _text(node)


@needs_node
def test_time_series_caps_points(tmp_path):
    n = 105
    pts = [{"date": f"d{i}", "value": i} for i in range(n)]
    data = {"data": pts, "chart_type": "bar"}
    [r] = _run(tmp_path, [{"messages": _surface("t", "TimeSeriesChart", data)}])
    cap = r["max"]
    node = r["nodes"][0]
    assert len([x for x in _walk(node) if x.get("tag") == "rect"]) == cap
    assert f"{n - cap} more" in _text(node)


@needs_node
def test_comparison_table_caps_columns_at_10(tmp_path):
    cols = [{"key": f"k{i}", "label": f"L{i}"} for i in range(15)]
    data = {"columns": cols, "rows": [{f"k{i}": i for i in range(15)}]}
    [r] = _run(tmp_path, [{"messages": _surface("c", "ComparisonTable", data)}])
    node = r["nodes"][0]
    assert len([x for x in _walk(node) if x.get("tag") == "th"]) == 10
    assert len([x for x in _walk(node) if x.get("tag") == "td"]) == 10
    assert "5 more" in _text(node)


def test_no_spread_over_payload_arrays():
    src = (_STATIC / "a2ui.js").read_text()
    assert not re.search(r"Math\.(max|min)\(\s*\.\.\.", src)


@needs_node
def test_replayed_artifact_one_surface_no_error_notes(tmp_path):
    msgs = _surface("rep", "KpiCard", {"metrics": [{"label": "A", "value": 1}]})
    res = _run(tmp_path, [{"messages": msgs}, {"messages": msgs}])
    assert len(res[0]["mounted"]) == 1
    assert len(res[1]["mounted"]) == 1
    assert res[1]["connected"] == [True]
    assert res[1]["notes"] == []


@needs_node
def test_reset_surfaces_closes_known_surface(tmp_path):
    update = [{"version": "v0.9.1", "updateDataModel": {"surfaceId": "S", "path": "/a", "value": 2}}]
    res = _run(
        tmp_path,
        [
            {"messages": _surface("S", "Thing", {"a": 1})},
            {"reset": True, "messages": update},
        ],
    )
    assert any("unknown/closed surface S" in n for n in res[1]["notes"])


def test_duplicate_create_warning_text_is_not_protocol_error():
    src = (_STATIC / "a2ui.js").read_text()
    assert "duplicate createSurface for open surface ignored (replay)" in src
    assert "protocol error: duplicate" not in src


_UNIT = """
import { capRows, moreNote, clip, MAX_TEXT } from "./a2ui.js";
const items = Array.from({ length: 25 }, (_, i) => i);
const note = moreNote(5, "columns");
const none = moreNote(0, "columns");
const bare = moreNote(3);
const text = (n) => (n ? n.children.map((c) => c.text).join("") : null);
process.stdout.write(JSON.stringify({
  capped: capRows(items, 10).length,
  default_cap: capRows(Array.from({ length: 150 }, (_, i) => i)).length,
  note: text(note), none: none, bare: text(bare),
  clipped: clip("x".repeat(10000), 50).length,
  short: clip("abc", 50),
  num: clip(12345, 50),
  nul: clip(null, 50),
  pair: clip("a".repeat(48) + String.fromCharCode(0xd83d, 0xde00) + "b".repeat(10), 50),
  max_text: MAX_TEXT,
}));
"""


def _run_unit(tmp_path: Path) -> dict:
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "api.js").write_text(_STUB_API)
    (tmp_path / "a2ui.js").write_text((_STATIC / "a2ui.js").read_text())
    (tmp_path / "u.js").write_text(_UNIT)
    proc = subprocess.run([_NODE, "u.js"], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _texts(node) -> list[str]:
    return [x["text"] for x in _walk(node) if "text" in x]


def _rects(node) -> list[dict]:
    return [x for x in _walk(node) if x.get("tag") == "rect"]


@needs_node
def test_clip_and_parameterised_helpers(tmp_path):
    u = _run_unit(tmp_path)
    assert u["capped"] == 10
    assert u["default_cap"] == 100
    assert u["note"] == "5 more columns"
    assert u["none"] is None
    assert u["bare"] == "3 more"
    assert u["clipped"] == 50
    assert u["short"] == "abc"
    assert u["num"] == "12345"
    assert u["nul"] == ""
    assert len(u["pair"]) <= 50
    assert u["pair"] == "a" * 48 + "…"


def test_more_columns_note_removed():
    src = (_STATIC / "a2ui.js").read_text()
    assert "moreColumnsNote" not in src


_BIG = "N" * 10000


def _big_cases() -> list[tuple[str, dict]]:
    return [
        ("KpiCard", {"title": _BIG, "metrics": [{"label": _BIG, "value": 1, "unit": _BIG}]}),
        ("EntityList", {"title": _BIG, "entity_type": _BIG, "items": [{"name": _BIG, "summary": _BIG}]}),
        ("BarChart", {"title": _BIG, "bars": [{"category": _BIG, "value": 1}]}),
        ("WaterfallChart", {"title": _BIG, "entity_name": _BIG, "segments": [{"label": _BIG, "value": 1, "cumulative": 1, "type": "delta"}]}),
        ("MultiCategoryChart", {"title": _BIG, "periods": [{"period": _BIG, "categories": {_BIG: {"value": 1}}}]}),
        ("TimeSeriesChart", {"title": _BIG, "data": [{"date": _BIG, "value": 1}, {"date": _BIG, "value": 2}]}),
        ("ComparisonTable", {"title": _BIG, "columns": [{"key": "a", "label": _BIG, "unit": _BIG}], "rows": [{"a": _BIG}]}),
        ("EmailList", {"messages": [{"subject": _BIG, "preview": _BIG, "from": {"name": _BIG}}]}),
        ("CalendarEvents", {"events": [{"subject": _BIG, "start": _BIG, "location": {"display_name": _BIG}}]}),
        ("UserList", {"users": [{"display_name": _BIG, "email": _BIG}]}),
        ("DocumentList", {"documents": [{"name": _BIG, "type": _BIG}]}),
        ("UserProfile", {"display_name": _BIG, "email": _BIG}),
    ]


@needs_node
@pytest.mark.parametrize("component,data", _big_cases(), ids=[c for c, _ in _big_cases()])
def test_long_strings_are_clipped_in_every_dedicated_renderer(tmp_path, component, data):
    [r] = _run(tmp_path, [{"messages": _surface("L", component, data)}])
    texts = _texts(r["nodes"][0])
    assert texts
    longest = max(len(t) for t in texts)
    assert longest <= 2000, (component, longest)
    assert 256 in {len(t) for t in texts}, component


@needs_node
def test_prose_is_clipped(tmp_path):
    [r] = _run(tmp_path, [{"messages": _surface("P", "MarketBriefing", "p" * 200000)}])
    assert max(len(t) for t in _texts(r["nodes"][0])) <= 20000


@needs_node
def test_multi_category_survives_null_period(tmp_path):
    periods = [None, {"period": "P1", "categories": {"a": {"value": 2}}}, {"period": "P2"}]
    [r] = _run(tmp_path, [{"messages": _surface("n", "MultiCategoryChart", {"periods": periods})}])
    assert r["nodes"]
    assert "a2ui-fallback" not in r["nodes"][0]["cls"]
    assert not any("paint failed" in n for n in r["notes"])


@needs_node
def test_multi_category_totals_use_shown_categories_and_abs(tmp_path):
    cats = {f"c{i:03d}": {"value": 0} for i in range(150)}
    cats["c000"] = {"value": 5}
    cats["c149"] = {"value": 1000000}
    [r] = _run(tmp_path, [{"messages": _surface("t1", "MultiCategoryChart", {"periods": [{"period": "P", "categories": cats}]})}])
    first = _rects(r["nodes"][0])[0]
    assert float(first["attrs"]["height"]) == pytest.approx(128.0)

    neg = {"a": {"value": -5}, "b": {"value": 5}}
    [r] = _run(tmp_path, [{"messages": _surface("t2", "MultiCategoryChart", {"periods": [{"period": "P", "categories": neg}]})}])
    heights = [float(x["attrs"]["height"]) for x in _rects(r["nodes"][0])]
    assert heights == [pytest.approx(64.0), pytest.approx(64.0)]


@needs_node
def test_multi_category_cells_capped_at_1000_and_notes_labelled(tmp_path):
    cats = {f"c{i}": {"value": 1} for i in range(50)}
    periods = [{"period": f"P{i}", "categories": cats} for i in range(100)]
    [r] = _run(tmp_path, [{"messages": _surface("cap", "MultiCategoryChart", {"periods": periods})}])
    node = r["nodes"][0]
    assert len(_rects(node)) <= 1000
    assert "40 more categories" in _text(node)

    many = [{"period": f"P{i}", "categories": {"a": {"value": 1}}} for i in range(105)]
    [r] = _run(tmp_path, [{"messages": _surface("cap2", "MultiCategoryChart", {"periods": many})}])
    assert "5 more periods" in _text(r["nodes"][0])


@needs_node
def test_time_series_keeps_newest_points(tmp_path):
    pts = [{"date": f"d{i}", "value": i} for i in range(105)]
    [r] = _run(tmp_path, [{"messages": _surface("ts", "TimeSeriesChart", {"data": pts, "chart_type": "line"})}])
    texts = _texts(r["nodes"][0])
    assert "d104" in texts
    assert "d5" in texts
    assert "d4" not in texts


@needs_node
def test_generic_sections_capped(tmp_path):
    data = {f"s{i}": [{"a": 1}] for i in range(40)}
    [r] = _run(tmp_path, [{"messages": _surface("gs", "Whatever", data)}])
    node = r["nodes"][0]
    tables = [x for x in _walk(node) if x.get("tag") == "table" and "a2ui-table" in x["cls"]]
    assert len(tables) == 10
    assert "30 more sections" in _text(node)


@needs_node
def test_create_after_delete_is_ignored(tmp_path):
    delete = [{"version": "v0.9.1", "deleteSurface": {"surfaceId": "D"}}]
    res = _run(
        tmp_path,
        [
            {"messages": _surface("D", "Thing", {"a": 1})},
            {"messages": delete},
            {"messages": _surface("D", "Thing", {"a": 2})},
        ],
    )
    assert res[0]["nodes"]
    assert res[2]["nodes"] == []
    assert any("createSurface rejected" in n for n in res[2]["notes"])


# GH-263 items 2 and 5: every wire value goes through clip(); inline slices, tombstones, ARROWS.
_HUGE = "Z" * 5000


def _lone_surrogates(text: str) -> bool:
    return re.search("[\ud800-\udfff]", text) is not None


@needs_node
def test_notes_clip_wire_surface_ids_and_component_names(tmp_path):
    huge_msg = lambda m: [{"version": "v0.9.1", **m}]  # noqa: E731
    steps = [
        {"messages": huge_msg({"updateComponents": {"surfaceId": _HUGE, "components": []}})},
        {"messages": huge_msg({"updateDataModel": {"surfaceId": _HUGE, "path": "/", "value": {}}})},
        {"messages": _surface("U", _HUGE, 5), "fallback": ""},
        {"messages": _surface("G", _HUGE, {"a": 1})},
    ]
    res = _run(tmp_path, steps)
    for r in res:
        assert r["notes"], r
        assert all(len(n) < 400 for n in r["notes"]), r["notes"]
    fallback = res[2]["nodes"][0]
    assert max(len(t) for t in _texts(fallback)) <= 256


@needs_node
def test_fallback_text_lines_are_clipped(tmp_path):
    steps = [{"messages": _surface("F", "Thing", 5), "fallback": "x" * 30000 + "\nshort"}]
    [r] = _run(tmp_path, steps)
    lens = [len(t) for t in _texts(r["nodes"][0])]
    assert max(lens) <= 20000 and "short" in _texts(r["nodes"][0])


@needs_node
def test_inline_label_truncation_goes_through_clip_without_lone_surrogates(tmp_path):
    label = "A" * 10 + "\U0001F600\U0001F600"
    seg = [{"label": label, "value": 5, "cumulative": 5, "type": "delta"}]
    [r] = _run(tmp_path, [{"messages": _surface("W", "WaterfallChart", {"segments": seg})}])
    texts = _texts(r["nodes"][0])
    assert "A" * 10 + "\u2026" in texts
    assert not any(_lone_surrogates(t) for t in texts)
    periods = [{"period": label, "categories": {"a": {"value": 1}}}]
    [r] = _run(tmp_path, [{"messages": _surface("M", "MultiCategoryChart", {"periods": periods})}])
    texts = _texts(r["nodes"][0])
    assert "A" * 9 + "\u2026" in texts
    assert not any(_lone_surrogates(t) for t in texts)


@needs_node
def test_compact_text_cap_is_200_characters_including_the_ellipsis(tmp_path):
    [r] = _run(tmp_path, [{"messages": _surface("C", "Whatever", {"blob": {"k": "v" * 500}})}])
    cells = [t for t in _texts(r["nodes"][0]) if t.startswith('{"k"') and t.endswith("\u2026")]
    assert len(cells) == 1 and len(cells[0]) == 200 and cells[0].endswith("\u2026")


@needs_node
def test_time_series_still_keeps_newest_points_and_notes_older_ones(tmp_path):
    pts = [{"date": f"d{i}", "value": i} for i in range(105)]
    [r] = _run(tmp_path, [{"messages": _surface("ts2", "TimeSeriesChart", {"data": pts, "chart_type": "line"})}])
    texts = _texts(r["nodes"][0])
    assert "5 more older points" in texts
    assert texts.index("d5") < texts.index("d104")
    assert "d4" not in texts


@needs_node
def test_trend_direction_is_not_looked_up_on_the_prototype(tmp_path):
    metrics = [{"label": "L", "value": 1, "trend": name} for name in ("constructor", "toString", "__proto__", "up")]
    [r] = _run(tmp_path, [{"messages": _surface("K", "KpiCard", {"metrics": metrics})}])
    text = _text(r["nodes"][0])
    assert "function" not in text and "native code" not in text
    assert "\u25b2" in text


@needs_node
def test_closed_surface_tombstones_are_bounded(tmp_path):
    close = lambda sid: [{"version": "v0.9.1", "deleteSurface": {"surfaceId": sid}}]  # noqa: E731
    steps = [{"messages": _surface(f"s{i}", "Thing", {"a": i}) + close(f"s{i}")} for i in range(250)]
    steps.append({"messages": _surface("s249", "Thing", {"a": 1})})
    steps.append({"messages": _surface("s0", "Thing", {"a": 1})})
    res = _run(tmp_path, steps)
    assert res[250]["nodes"] == [] and any("createSurface rejected" in n for n in res[250]["notes"])
    assert res[251]["nodes"] and not any("rejected" in n for n in res[251]["notes"])
