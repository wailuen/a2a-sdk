"""GH-239: bar-chart and generic scalar rows use the C-059 row cap; registry prunes detached nodes.

Runs the REAL ``a2ui.js`` under node against a tiny fake DOM (stub ``api.js``).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_gh215_console_generic_renderer import _STUB_API, _surface, _text, _walk

_NODE = shutil.which("node")
_STATIC = Path(__file__).resolve().parent.parent / "agent_sdk" / "console" / "static"

pytestmark = pytest.mark.skipif(_NODE is None, reason="node not installed")

_HARNESS = """
import { renderA2ui, MAX_ROWS } from "./a2ui.js";
const steps = JSON.parse(process.argv[2]);
function dump(n) {
  if (n.tag === "#text") return { text: n.text };
  return { tag: n.tag, cls: n.cls, children: n.children.map(dump) };
}
const out = [];
let last = [];
for (const s of steps) {
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


def test_bar_chart_caps_150_bars(tmp_path):
    bars = [{"category": f"C{i}", "value": i + 1} for i in range(150)]
    [r] = _run(tmp_path, [{"messages": _surface("b", "BarChart", {"bars": bars})}])
    cap = r["max"]
    node = r["nodes"][0]
    assert len([x for x in _walk(node) if x.get("tag") == "rect"]) == cap
    assert f"{150 - cap} more" in _text(node)


def test_generic_scalar_rows_capped(tmp_path):
    data = {f"k{i}": i for i in range(150)}
    [r] = _run(tmp_path, [{"messages": _surface("g", "Whatever", data)}])
    cap = r["max"]
    node = r["nodes"][0]
    kv = [x for x in _walk(node) if x.get("tag") == "table" and "tbl-kv" in x["cls"]]
    assert len([x for x in _walk(kv[0]) if x.get("tag") == "tr"]) == cap
    assert f"{150 - cap} more" in _text(node)


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


def test_registry_keeps_connected_surfaces(tmp_path):
    update = [{"version": "v0.9.1", "updateDataModel": {"surfaceId": "p", "path": "/a", "value": 2}}]
    res = _run(
        tmp_path,
        [
            {"messages": _surface("p", "Thing", {"a": 1})},
            {"detach": False, "messages": update},
        ],
    )
    assert res[1]["notes"] == [] or not any("dropped" in n for n in res[1]["notes"])
    assert res[1]["nodes"]


def test_registry_comment_names_real_fields():
    src = (_STATIC / "a2ui.js").read_text()
    m = re.search(r"/\* surfaceId -> \{([^}]*)\}", src)
    assert m
    assert "_componentMap" in m.group(1) and "components:" not in m.group(1)
