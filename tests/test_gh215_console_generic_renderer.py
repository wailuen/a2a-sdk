"""GH-215: console generic renderer, fold isolation, row cap, catalog-id await.

Runs the REAL ``a2ui.js`` under node against a tiny fake DOM (stub ``api.js``).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_NODE = shutil.which("node")
_STATIC = Path(__file__).resolve().parent.parent / "agent_sdk" / "console" / "static"

pytestmark = pytest.mark.skipif(_NODE is None, reason="node not installed")

_STUB_API = """
export class FNode {
  constructor(tag, text) { this.tag = tag; this.text = text; this.cls = ""; this.children = []; this.parentNode = null; this.attrs = {}; }
  set className(v) { this.cls = v; }
  get className() { return this.cls; }
  get classList() { return { add: (c) => { this.cls = (this.cls + " " + c).trim(); } }; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = v; }
  replaceWith(n) { const p = this.parentNode; p.children[p.children.indexOf(this)] = n; n.parentNode = p; }
}
globalThis.document = {
  createElement: (t) => new FNode(t),
  createElementNS: (_ns, t) => new FNode(t),
  createTextNode: (t) => new FNode("#text", String(t)),
};
function append(node, child) {
  if (child === null || child === undefined || child === false) return;
  if (Array.isArray(child)) child.forEach((c) => append(node, c));
  else if (child instanceof FNode) node.appendChild(child);
  else node.appendChild(document.createTextNode(String(child)));
}
export function el(tag, attrs, ...children) {
  const n = new FNode(tag);
  if (attrs && attrs.class) n.cls = String(attrs.class);
  append(n, children);
  return n;
}
"""

_HARNESS = """
import { renderA2ui, MAX_ROWS } from "./a2ui.js";
const cases = JSON.parse(process.argv[2]);
function dump(n) {
  if (n.tag === "#text") return { text: n.text };
  return { tag: n.tag, cls: n.cls, children: n.children.map(dump) };
}
const out = [];
for (const c of cases) {
  const r = renderA2ui(c.messages, { fallbackText: "FALLBACK" });
  out.push({ nodes: r.nodes.map(dump), notes: r.notes, max: MAX_ROWS, polluted: ({}).x ?? null });
}
process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path: Path, cases: list[dict]) -> list[dict]:
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "api.js").write_text(_STUB_API)
    (tmp_path / "a2ui.js").write_text((_STATIC / "a2ui.js").read_text())
    (tmp_path / "h.js").write_text(_HARNESS)
    proc = subprocess.run(
        [_NODE, "h.js", json.dumps(cases)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _walk(n):
    yield n
    for c in n.get("children", []):
        yield from _walk(c)


def _text(n) -> str:
    return " ".join(x["text"] for x in _walk(n) if "text" in x)


def _surface(sid: str, component: str, data, path: str | None = None) -> list[dict]:
    root: dict = {"id": "root", "component": component}
    if path is not None:
        root["data"] = {"path": path}
    return [
        {"version": "v0.9.1", "createSurface": {"surfaceId": sid, "catalogId": "urn:x"}},
        {"version": "v0.9.1", "updateComponents": {"surfaceId": sid, "components": [root]}},
        {"version": "v0.9.1", "updateDataModel": {"surfaceId": sid, "path": "/", "value": data}},
    ]


def test_unknown_domain_type_renders_card_not_pre(tmp_path):
    data = {
        "name": "Fund III",
        "nav": 1234.5,
        "positions": [{"ticker": "AAA", "qty": 3}, {"ticker": "BBB", "qty": 4}],
    }
    [r] = _run(tmp_path, [{"messages": _surface("g1", "PortfolioSummary", data)}])
    node = r["nodes"][0]
    assert "a2ui-card" in node["cls"]
    assert "a2ui-fallback" not in node["cls"]
    text = _text(node)
    assert "Portfolio Summary" in text
    assert "Fund III" in text and "1,234.5" in text
    assert any(x.get("tag") == "table" and "a2ui-table" in x["cls"] for x in _walk(node))
    assert "AAA" in text and "BBB" in text
    pres = [x for x in _walk(node) if x.get("tag") == "pre"]
    assert len(pres) == 1
    details = [x for x in _walk(node) if x.get("tag") == "details"]
    assert details and pres[0] in list(_walk(details[0]))


def test_malformed_message_mid_array_still_paints_later_surfaces(tmp_path):
    messages = (
        _surface("ok1", "Thing", {"a": 1})
        + [
            {"version": "v0.9.1", "updateDataModel": {"surfaceId": "bad", "path": "/", "value": None}},
            {"version": "v0.9.1", "createSurface": {"surfaceId": "bad", "catalogId": "urn:x"}},
            {"version": "v0.9.1", "updateDataModel": {"surfaceId": "bad", "path": "/", "value": None}},
            {"version": "v0.9.1", "updateDataModel": {"surfaceId": "bad", "path": "/x/y", "value": 1}},
        ]
        + _surface("later", "OtherThing", {"b": 2})
    )
    [r] = _run(tmp_path, [{"messages": messages}])
    texts = [_text(n) for n in r["nodes"]]
    assert any("Other Thing" in t for t in texts)
    assert any("skipped" in n for n in r["notes"])


def test_relative_pointer_never_folds_to_model_root(tmp_path):
    msgs = _surface("rel", "Thing", {"a": 1}, path="a")
    msgs.append({"version": "v0.9.1", "updateDataModel": {"surfaceId": "rel", "path": "b", "value": 9}})
    [r] = _run(tmp_path, [{"messages": msgs}])
    assert any("relative" in n for n in r["notes"])
    assert all("Thing" not in _text(n) for n in r["nodes"])


def test_row_cap_applies_with_more_note(tmp_path):
    n = 130
    rows = [{"ticker": f"T{i}"} for i in range(n)]
    entity = {"items": [{"name": f"N{i}"} for i in range(n)], "entity_type": "x"}
    cases = [
        {"messages": _surface("g", "Whatever", {"rows": rows})},
        {"messages": _surface("e", "EntityList", entity)},
    ]
    res = _run(tmp_path, cases)
    cap = res[0]["max"]
    assert cap < n
    for r in res:
        node = r["nodes"][0]
        text = _text(node)
        assert f"{n - cap} more" in text
    generic_trs = [x for x in _walk(res[0]["nodes"][0]) if x.get("tag") == "tr"]
    assert len(generic_trs) == cap + 1
    rows_e = [x for x in _walk(res[1]["nodes"][0]) if "a2ui-list-row" in x.get("cls", "")]
    assert len(rows_e) == cap


def test_first_send_awaits_catalog_ids():
    src = (_STATIC / "chat.js").read_text()
    assert re.search(r"const catalogIdsReady = loadCatalogIds\(\)", src)
    for fn in ("sendA2a", "sendAgui"):
        body = src[src.index(f"async function {fn}("):]
        assert body.index("await catalogIdsReady") < body.index("state.catalogIds"), fn


def test_render_a2ui_messages_is_guarded():
    src = (_STATIC / "chat.js").read_text()
    start = src.index("function renderA2uiMessages")
    body = src[start : src.index("/* ── A2A mode", start)]
    assert "try {" in body and "catch" in body


@pytest.mark.parametrize("path", ["/__proto__/x", "/constructor/prototype/x", "/a/__proto__/x"])
def test_pointer_set_rejects_prototype_tokens(tmp_path, path):
    msgs = _surface("pp", "Thing", {"a": {}})
    msgs.append({"version": "v0.9.1", "updateDataModel": {"surfaceId": "pp", "path": path, "value": "yes"}})
    [r] = _run(tmp_path, [{"messages": msgs}])
    assert r["polluted"] is None
    assert any("skipped" in n for n in r["notes"])
