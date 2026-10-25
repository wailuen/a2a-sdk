"""RT-005 / RT-010: FundPerformance card must not surface an opaque
upstream vendor id (``pbId``) as its human-readable title.

GH-149 removed ``FundPerformance.fund_name`` from the ContentModel
(agent_sdk/models/content_types.py) and from the LLM-teaching strings
(agent_sdk/a2ui/catalog.py). The admin-console renderer
(agent_sdk/console/static/a2ui.js) initially patched the resulting empty
title by falling back to ``Fund ${data.pbId}`` (RT-005), but ``pbId`` is
documented on the frozen Standard Profile v1 contract as a *source id*, not
a display name — RT-010 found that surfacing it as the card heading (e.g.
"Fund pb-acme-3") reads as a human-facing fund name when it is not one.

The fix: the title is the neutral literal "Fund performance" always;
``pbId``, when present, appears in the subtitle next to ``asOfDate`` where
an identifier reads as provenance rather than as a name.

These tests run the real renderFundPerformance()/card() functions straight
out of agent_sdk/console/static/a2ui.js under node — not a hand-copied
transcription — so a future edit to the renderer is checked against its
actual behavior, the same cross-check pattern used in test_a2ui_wire.py's
RT-002/RT-003 pointerSet sections.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_NODE_BIN = shutil.which("node")
_A2UI_JS_PATH = Path(__file__).resolve().parent.parent / "agent_sdk" / "console" / "static" / "a2ui.js"

_RENDER_FUND_PERFORMANCE_HARNESS = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const cardStart = src.indexOf("function card(title");
const cardEnd = src.indexOf("const ARROWS = ");
const rfpStart = src.indexOf("function renderFundPerformance");
const rfpEnd = src.indexOf("function renderEmailList");

class DomNode {
  constructor(tag) {
    this.tag = tag;
    this.className = "";
    this.attrs = {};
    this.childNodes = [];
  }
  appendChild(child) {
    this.childNodes.push(child);
    return child;
  }
}
class TextNode {
  constructor(text) {
    this.text = String(text);
  }
}
const document = {
  createElement: (tag) => new DomNode(tag),
  createTextNode: (text) => new TextNode(text),
};
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [name, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (name === "class") node.className = String(value);
      else node.attrs[name] = String(value);
    }
  }
  append(node, children);
  return node;
}
function append(node, child) {
  if (child === null || child === undefined || child === false) return;
  if (Array.isArray(child)) {
    for (const c of child) append(node, c);
  } else if (child instanceof DomNode || child instanceof TextNode) {
    node.appendChild(child);
  } else {
    node.appendChild(document.createTextNode(String(child)));
  }
}

// GH-215/GH-255 row-cap and text-clip helpers live outside the sliced
// ranges; load the real ones (exports turned into plain declarations).
eval(src.slice(src.indexOf("export const MAX_ROWS"), src.indexOf("function maxOf"))
  .replace(/export const /g, "var ").replace(/export function /g, "function "));
eval(src.slice(cardStart, cardEnd));
eval(src.slice(rfpStart, rfpEnd));

function textOf(node) {
  if (node instanceof TextNode) return node.text;
  if (!node.childNodes) return "";
  return node.childNodes.map(textOf).join("");
}

const data = JSON.parse(process.argv[2]);
const result = renderFundPerformance(data);
const titleNode = result.childNodes.find((c) => c instanceof DomNode && c.className === "a2ui-card-title");
const subNode = result.childNodes.find((c) => c instanceof DomNode && c.className === "a2ui-card-sub");
process.stdout.write(JSON.stringify({
  title: titleNode ? textOf(titleNode) : null,
  subtitle: subNode ? textOf(subNode) : null,
}));
"""


def _live_fund_performance_card(data: dict) -> dict:
    assert _NODE_BIN is not None, "caller must skip when node is unavailable"
    result = subprocess.run(
        [_NODE_BIN, "-e", _RENDER_FUND_PERFORMANCE_HARNESS, "--", str(_A2UI_JS_PATH), json.dumps(data)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_card_title_is_always_the_neutral_literal():
    """RT-010: pbId is a source id, not a display name — it must never
    appear in the card title, whether present or absent."""
    with_id = _live_fund_performance_card({"pbId": "pb-alpha-3", "irr": 0.185})
    without_id = _live_fund_performance_card({"irr": 0.185})
    assert with_id["title"] == "Fund performance"
    assert without_id["title"] == "Fund performance"


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_card_subtitle_carries_pb_id_as_provenance():
    """RT-010: when pbId is present, it belongs in the subtitle next to
    asOfDate — readable as provenance, not as the fund's name."""
    card = _live_fund_performance_card({"pbId": "pb-alpha-3", "asOfDate": "2026-06-30", "irr": 0.185})
    assert card["subtitle"] is not None
    assert "pb-alpha-3" in card["subtitle"]
    assert "2026-06-30" in card["subtitle"]


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_card_subtitle_omitted_when_no_identifiers():
    """RT-005: with neither pbId nor asOfDate, there is nothing to show in
    the subtitle — it must not render an empty sliver."""
    card = _live_fund_performance_card({"irr": 0.185})
    assert card["subtitle"] is None


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_card_never_reads_removed_fund_name_field():
    """RT-005: fundName is not on the frozen Standard Profile v1 wire contract
    (GH-149 removed it from content_types.py and catalog.py) — the renderer
    must not resurrect it anywhere on the card. A stray fundName in incoming
    data (e.g. from a stale client) must not silently become the title or
    subtitle; only the neutral literal and pbId/asOfDate may drive them."""
    card = _live_fund_performance_card({"fundName": "Alpha Fund III", "irr": 0.185})
    assert card["title"] == "Fund performance"
    assert card["subtitle"] is None
