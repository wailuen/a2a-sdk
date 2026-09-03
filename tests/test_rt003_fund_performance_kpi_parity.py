"""RT-003: renderFundPerformance() must render the same fields as
FundPerformance.to_plain_text() (agent_sdk/models/content_types.py).

RT-004's comment on to_plain_text() states the invariant: "keep pace with
every field the wire can carry — a field present on the card but absent
here silently vanishes for that client". RT-003 found that invariant
broken in the opposite direction: to_plain_text() renders dryPowderPct,
distributedPlusRemaining and asOfQuarter/asOfYear, but the admin console's
KPI grid (renderFundPerformance in agent_sdk/console/static/a2ui.js) never
did — so the A2UI-capable admin console showed strictly less than the
text-only fallback for the same card.

These tests run the real renderFundPerformance()/card() functions straight
out of agent_sdk/console/static/a2ui.js under node, the same cross-check
pattern used in test_rt005_fund_performance_title.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_sdk.models.content_types import FundPerformance, Money

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

eval(src.slice(cardStart, cardEnd));
eval(src.slice(rfpStart, rfpEnd));

function textOf(node) {
  if (node instanceof TextNode) return node.text;
  if (!node.childNodes) return "";
  return node.childNodes.map(textOf).join("");
}

function findClass(node, cls) {
  return (node.childNodes || []).find((c) => c instanceof DomNode && c.className === cls);
}

const data = JSON.parse(process.argv[2]);
const result = renderFundPerformance(data);
const subNode = findClass(result, "a2ui-card-sub");
const grid = findClass(result, "a2ui-kpi-grid");
const entries = (grid ? grid.childNodes : []).map((kpi) => {
  const label = findClass(kpi, "a2ui-kpi-label");
  const value = findClass(kpi, "a2ui-kpi-value mono");
  return [label ? textOf(label) : null, value ? textOf(value) : null];
});
process.stdout.write(JSON.stringify({
  subtitle: subNode ? textOf(subNode) : null,
  entries,
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
def test_fund_performance_grid_renders_dry_powder_pct():
    card = _live_fund_performance_card({"irr": 0.185, "dryPowderPct": 0.234})
    labels = dict(card["entries"])
    assert "Dry powder %" in labels
    assert labels["Dry powder %"] == "23.4%"


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_grid_renders_distributed_plus_remaining():
    card = _live_fund_performance_card(
        {"irr": 0.185, "distributedPlusRemaining": {"amount": 4200000, "currency": "USD"}}
    )
    labels = dict(card["entries"])
    assert "Distributed + remaining" in labels
    assert labels["Distributed + remaining"] == "4,200,000 USD"


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_subtitle_carries_as_of_quarter_and_year():
    card = _live_fund_performance_card(
        {"irr": 0.185, "asOfQuarter": 2, "asOfYear": 2026, "asOfDate": "2026-06-30"}
    )
    assert card["subtitle"] is not None
    assert "Q2 2026" in card["subtitle"]
    assert "2026-06-30" in card["subtitle"]


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_subtitle_carries_as_of_quarter_without_year():
    card = _live_fund_performance_card({"irr": 0.185, "asOfQuarter": 2})
    assert card["subtitle"] is not None
    assert "Q2" in card["subtitle"]


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_grid_omits_missing_new_fields():
    card = _live_fund_performance_card({"irr": 0.185})
    labels = dict(card["entries"])
    assert "Dry powder %" not in labels
    assert "Distributed + remaining" not in labels


# RT-009: the spot-checks above name three fields plus one negative — every
# prior parity break in this file's history (RT-004, then RT-002) was a
# field the spot-check simply didn't know to ask about. The fixtures and
# tests below instead enumerate FundPerformance.model_fields itself, so the
# next field added to the model fails loudly here instead of silently
# vanishing from one side.
#
# `metadata` (ContentModel, RT-006) is the SDK-wide out-of-band envelope,
# deliberately absent from the frozen Standard Profile v1 per-type field
# table — it is the only field named here that is NOT expected to appear in
# either to_plain_text() or the rendered card, and it is named explicitly so
# that exclusion can never be assumed for anything else.
_DELIBERATELY_EXCLUDED_FIELDS = {"metadata"}

_FIELD_VALUES: dict[str, object] = {
    "pb_id": "PB-TEST-1",
    "as_of_date": "2031-06-30",
    "irr": 0.11,
    "tvpi": 1.4,
    "dpi": 1.5,
    "rvpi": 1.6,
    "net_irr": 0.12,
    "gross_irr": 0.13,
    "moic": 1.7,
    "quartile": 1,
    "nav": Money(amount=1_000_000, currency="USD"),
    "as_of_quarter": 2,
    "as_of_year": 2031,
    "called_down_pct": 0.55,
    "dry_powder": Money(amount=2_000_000, currency="USD"),
    "dry_powder_pct": 0.66,
    "distributed": Money(amount=3_000_000, currency="USD"),
    "remaining_value": Money(amount=4_000_000, currency="USD"),
    "distributed_plus_remaining": Money(amount=7_000_000, currency="USD"),
}

# What to_plain_text() must say for each field above (content_types.py's
# FundPerformance.to_plain_text()).
_FIELD_TEXT_MARKERS: dict[str, str] = {
    "pb_id": "source PB-TEST-1",
    "as_of_date": "as of 2031-06-30",
    "irr": "IRR=11.0%",
    "tvpi": "TVPI=1.40x",
    "dpi": "DPI=1.50x",
    "rvpi": "RVPI=1.60x",
    "net_irr": "Net IRR=12.0%",
    "gross_irr": "Gross IRR=13.0%",
    "moic": "MOIC=1.70x",
    "quartile": "Quartile=Q1",
    "nav": "NAV=1,000,000 USD",
    "as_of_quarter": "Q2 2031",
    "as_of_year": "Q2 2031",
    "called_down_pct": "Called down=55.0%",
    "dry_powder": "Dry powder=2,000,000 USD",
    "dry_powder_pct": "Dry powder pct=66.0%",
    "distributed": "Distributed=3,000,000 USD",
    "remaining_value": "Remaining value=4,000,000 USD",
    "distributed_plus_remaining": "Distributed+remaining=7,000,000 USD",
}

# Fields renderFundPerformance() puts in the KPI grid, by their grid label...
_FIELD_KPI_LABELS: dict[str, str] = {
    "irr": "IRR",
    "net_irr": "Net IRR",
    "gross_irr": "Gross IRR",
    "tvpi": "TVPI",
    "dpi": "DPI",
    "rvpi": "RVPI",
    "moic": "MOIC",
    "quartile": "Quartile",
    "nav": "NAV",
    "dry_powder": "Dry powder",
    "distributed": "Distributed",
    "remaining_value": "Remaining value",
    "distributed_plus_remaining": "Distributed + remaining",
    "called_down_pct": "Called down",
    "dry_powder_pct": "Dry powder %",
}

# ...and the rest, which it folds into the card subtitle instead.
_FIELD_SUBTITLE_MARKERS: dict[str, str] = {
    "pb_id": "source PB-TEST-1",
    "as_of_date": "as of 2031-06-30",
    "as_of_quarter": "Q2",
    "as_of_year": "2031",
}


def test_declared_field_fixtures_cover_every_model_field():
    """Guards the enumeration itself: if FundPerformance ever grows a field
    without the fixtures above being updated, this fails first — before
    either parity test below gets a chance to pass on a stale, incomplete
    field set."""
    declared = set(FundPerformance.model_fields) - _DELIBERATELY_EXCLUDED_FIELDS
    assert declared == set(_FIELD_VALUES)
    assert declared == set(_FIELD_TEXT_MARKERS)
    assert declared == set(_FIELD_KPI_LABELS) | set(_FIELD_SUBTITLE_MARKERS)


def test_fund_performance_to_plain_text_covers_every_declared_field():
    fp = FundPerformance(**_FIELD_VALUES)
    text = fp.to_plain_text()
    for field, marker in _FIELD_TEXT_MARKERS.items():
        assert marker in text, f"{field} left no trace in to_plain_text(): {text!r}"


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot run the live a2ui.js renderer")
def test_fund_performance_card_covers_every_declared_field():
    fp = FundPerformance(**_FIELD_VALUES)
    card = _live_fund_performance_card(fp.wire())
    labels = dict(card["entries"])
    for field, label in _FIELD_KPI_LABELS.items():
        assert label in labels, f"{field} has no KPI grid entry (expected label {label!r})"
    assert card["subtitle"] is not None
    for field, marker in _FIELD_SUBTITLE_MARKERS.items():
        assert marker in card["subtitle"], (
            f"{field} left no trace in the card subtitle: {card['subtitle']!r}"
        )
