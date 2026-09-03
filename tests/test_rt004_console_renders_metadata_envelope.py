"""RT-004: the console must render the SDK-wide ``metadata`` envelope.

``metadata`` is declared on ``ContentModel`` itself, so no per-component
renderer owns it -- and before this fix none of ``a2ui.js``'s 14 renderers read
it, meaning the SDK's own admin console (the surface ``/acceptance --ux``
inspects) was blind to the entire GH-63 disclosure envelope.

That is load-bearing, not cosmetic. GH-149 removed ``FundPerformance.fundName``
and replaced the ``fundName``-derived card title with the fixed string "Fund
performance"; the CHANGELOG entry shipped alongside it names
``metadata={"fund": "Fund III"}`` as one of three supported ways to carry fund
identity instead, and asserts that N identically-titled cards is a bug in the
calling agent. An agent that follows that instruction to the letter still saw N
cards titled "Fund performance" with nothing distinguishing them -- the
prescribed migration path was unrenderable on the only renderer the SDK ships.

These tests run the REAL ``appendMetadataFootnote`` from
``agent_sdk/console/static/a2ui.js`` under node (same live-source pattern as the
``pointerSet`` cross-check in ``tests/test_a2ui_wire.py``), so an edit that drops
metadata rendering fails here instead of drifting away from a hand-copied
snapshot.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_NODE_BIN = shutil.which("node")
_A2UI_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "agent_sdk" / "console" / "static" / "a2ui.js"
)
_CSS_PATH = (
    Path(__file__).resolve().parent.parent
    / "agent_sdk" / "console" / "static" / "console.css"
)
_IN_CI = os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}

# Minimal el()/DOM stubs matching api.js's text-node-only contract: children
# are appended as text, never parsed as markup. The harness slices the real
# appendMetadataFootnote out of a2ui.js and evals it against these stubs, then
# prints the footnote's rendered text so the test can assert on it.
_NODE_HARNESS = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const start = src.indexOf("function appendMetadataFootnote");
const end = src.indexOf("function fallbackNode");
if (start < 0 || end < 0 || end <= start) {
  throw new Error("appendMetadataFootnote not found in a2ui.js");
}
function mkNode(cls) {
  return { cls: cls || "", children: [], appendChild(c) { this.children.push(c); } };
}
function el(tag, attrs, ...children) {
  const node = mkNode(attrs && attrs.class);
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    node.appendChild(typeof c === "object" ? c : { text: String(c) });
  }
  return node;
}
eval(src.slice(start, end));
const root = mkNode("a2ui-surface");
appendMetadataFootnote(root, JSON.parse(process.argv[2]));
function dump(n) {
  if (n.text !== undefined) return { text: n.text };
  return { cls: n.cls, children: n.children.map(dump) };
}
process.stdout.write(JSON.stringify(root.children.map(dump)));
"""


def _footnote(data) -> list:
    assert _NODE_BIN is not None, "caller must skip when node is unavailable"
    result = subprocess.run(
        [_NODE_BIN, "-e", _NODE_HARNESS, "--", str(_A2UI_JS_PATH), json.dumps(data)],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(result.stdout)


def _texts(nodes) -> list[str]:
    out: list[str] = []
    for n in nodes:
        if "text" in n:
            out.append(n["text"])
        else:
            out.extend(_texts(n["children"]))
    return out


def test_live_metadata_footnote_cross_check_available_in_ci():
    """Mirrors the RT-003 guard on the pointerSet cross-check: in CI a missing
    node must fail loudly rather than let every test below silently skip."""
    if not _IN_CI:
        pytest.skip("not running in CI; local runs may lack node")
    assert _NODE_BIN is not None, (
        "node is required in CI to run the live a2ui.js metadata-footnote "
        "cross-check (RT-004)"
    )


def test_source_has_no_hardcoded_metadata_free_renderer():
    """The point of RT-004 is that metadata is read ONCE, generically -- not
    that some renderer happens to mention it. Assert the dispatch point calls
    the shared helper, so a refactor that inlines it per-component is caught."""
    src = _A2UI_JS_PATH.read_text()
    assert "appendMetadataFootnote(resolved)" in src or re.search(
        r"appendMetadataFootnote\(\s*node\s*,\s*resolved\s*\)", src
    ), "paintSurface must apply the metadata footnote at the single dispatch point"


def test_metadata_footnote_css_class_is_styled():
    """A footnote rendered into a class the stylesheet never defines is
    invisible in practice -- which is the bug this closes."""
    css = _CSS_PATH.read_text()
    assert ".a2ui-meta" in css


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_fund_identity_carried_in_metadata_is_rendered():
    """The exact CHANGELOG-prescribed GH-149 migration: two FundPerformance
    cards that differ only by metadata must be distinguishable."""
    a = _texts(_footnote({"irr": 0.18, "metadata": {"fund": "Fund III"}}))
    b = _texts(_footnote({"irr": 0.18, "metadata": {"fund": "Fund IV"}}))
    assert any("Fund III" in t for t in a), a
    assert any("Fund IV" in t for t in b), b
    assert a != b


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_disclosure_annotation_is_rendered():
    texts = _texts(_footnote({"metadata": {"coverage_note": "Partial: 5 of 20 funds"}}))
    assert any("coverage_note" in t and "Partial: 5 of 20 funds" in t for t in texts), texts


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"irr": 0.18},
        {"metadata": None},
        {"metadata": {}},
        {"metadata": "not-an-object"},
        {"metadata": ["not", "an", "object"]},
        "market briefing prose string",
        None,
    ],
    ids=[
        "empty", "no-metadata", "null", "empty-dict",
        "string-metadata", "list-metadata", "prose-string-value", "null-value",
    ],
)
def test_no_footnote_when_there_is_nothing_to_show(data):
    """No stray empty row -- and MarketBriefing's prose exception binds a bare
    string rather than an object, which must not throw out of the renderer."""
    assert _footnote(data) == []


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_object_valued_metadata_is_json_not_object_object():
    texts = _texts(_footnote({"metadata": {"source": {"system": "pb", "id": 7}}}))
    assert not any("[object Object]" in t for t in texts), texts
    assert any('"system"' in t and '"pb"' in t for t in texts), texts


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_metadata_values_land_as_text_not_markup():
    """Untrusted-output invariant: metadata is caller-/tool-supplied, so a value
    containing markup must survive as literal text (el() uses createTextNode),
    never be interpreted."""
    payload = '<img src=x onerror="alert(1)">'
    texts = _texts(_footnote({"metadata": {"note": payload}}))
    assert any(payload in t for t in texts), texts


# ── RT-008: appendMetadataFootnote must carry the SAME bounds as the Python
# mirror, content_types.py's _metadata_suffix() -- per-field 256-char cap
# (_METADATA_SUFFIX_FIELD_MAX_LEN), a 4096-char cap on the assembled footnote
# (_METADATA_SUFFIX_MAX_LEN), and a control-char strip (sanitize_text) --
# rather than rendering a caller-/tool-supplied metadata dict unbounded.


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_metadata_value_is_capped_at_field_max_len():
    """RT-006: byte-matches Python's sanitize_text -- ``s[:max_len].translate(...)``
    -- which slices to exactly 256 chars and never appends an ellipsis."""
    value = "x" * 500
    texts = _texts(_footnote({"metadata": {"note": value}}))
    assert len(texts) == 1, texts
    assert texts[0].startswith("note: "), texts
    value_part = texts[0][len("note: "):]
    assert "x" * 500 not in value_part, value_part
    assert value_part == "x" * 256, value_part


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_metadata_key_is_capped_at_field_max_len():
    """RT-006: byte-matches Python's sanitize_text -- no ellipsis, exact
    256-char slice."""
    key = "k" * 500
    texts = _texts(_footnote({"metadata": {key: "v"}}))
    assert len(texts) == 1, texts
    key_part = texts[0].split(": ", 1)[0]
    assert "k" * 500 not in key_part, key_part
    assert key_part == "k" * 256, key_part


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_metadata_control_chars_are_stripped():
    texts = _texts(_footnote({"metadata": {"note": "bell\x07esc\x1binjected\x00tail"}}))
    assert len(texts) == 1, texts
    assert "\x07" not in texts[0]
    assert "\x1b" not in texts[0]
    assert "\x00" not in texts[0]
    assert "bell esc injected tail" in texts[0], texts


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_metadata_footnote_total_length_is_capped():
    meta = {f"key{i}": "v" * 200 for i in range(50)}
    texts = _texts(_footnote({"metadata": meta}))
    total_len = sum(len(t) for t in texts)
    assert total_len <= 4096, total_len
    assert len(texts) < 50, "unbounded metadata dict must not render every entry"


