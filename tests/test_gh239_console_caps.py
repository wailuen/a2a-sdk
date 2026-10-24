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


def test_gh239_node_available_in_ci():
    if not _IN_CI:
        pytest.skip("not running in CI; local runs may lack node")
    assert _NODE is not None, "node is required in CI for the a2ui.js live tests"

_HARNESS = """
import { renderA2ui, resetSurfaces, MAX_ROWS } from "./a2ui.js";
const steps = JSON.parse(process.argv[2]);
function dump(n) {
  if (n.tag === "#text") return { text: n.text };
  return { tag: n.tag, cls: n.cls, children: n.children.map(dump) };
}
const out = [];
let last = [];
for (const s of steps) {
  if (s.reset) resetSurfaces();
  if (s.detach !== undefined && last[0]) last[0].isConnected = s.detach ? false : true;
  const r = renderA2ui(s.messages || [], { fallbackText: "FALLBACK" });
  last = r.nodes;
  out.push({ nodes: r.nodes.map(dump), notes: r.notes, max: MAX_ROWS });
}
process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path: Path, steps: list[dict]) -> list[dict]:
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "api.js").write_text(_STUB_API)
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
    assert res[1]["nodes"]
    assert "2" in _text(res[1]["nodes"][0]).split()


@needs_node
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


@needs_node
def test_no_spread_over_payload_arrays():
    src = (_STATIC / "a2ui.js").read_text()
    assert not re.search(r"Math\.(max|min)\(\s*\.\.\.", src)


@needs_node
def test_replayed_artifact_one_surface_no_error_notes(tmp_path):
    msgs = _surface("rep", "KpiCard", {"metrics": [{"label": "A", "value": 1}]})
    res = _run(tmp_path, [{"messages": msgs}, {"messages": msgs}])
    assert len(res[0]["nodes"]) == 1
    assert len(res[1]["nodes"]) == 1
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
