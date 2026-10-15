"""GH-177: DocumentItem emits Profile v1.1 contract keys only."""
from __future__ import annotations

import pytest

from agent_sdk.a2ui.catalog import _COMPACT_SCHEMAS
from agent_sdk.models.content_types import DocumentItem, DocumentList
from tests._compact_schema import parse_schema


def test_aliases_fill_contract_keys_and_are_not_emitted():
    doc = DocumentItem(id="1", name="n", web_url="u", last_modified="d", modified_by="m")
    assert doc.wire() == {"id": "1", "name": "n", "link": "u", "modified": "d", "modified_by": "m"}
    assert doc.last_modified == "d"
    assert doc.web_url == "u"


def test_explicit_contract_keys_win():
    doc = DocumentItem(id="1", name="n", link="L", modified="M", web_url="u", last_modified="d")
    assert doc.wire() == {"id": "1", "name": "n", "link": "L", "modified": "M"}


def test_nested_list_wire_uses_contract_keys():
    dl = DocumentList(documents=[DocumentItem(id="1", name="n", web_url="u", last_modified="d")])
    assert dl.wire()["documents"][0] == {"id": "1", "name": "n", "link": "u", "modified": "d"}


def test_plain_text_still_shows_date_and_modified_by():
    dl = DocumentList(documents=[DocumentItem(id="1", name="n", last_modified="2026-01-01", modified_by="Ann")])
    text = dl.to_plain_text()
    assert "2026-01-01" in text
    assert "Ann" in text


def test_text_shows_both_dates_when_both_set_and_differ():
    """w050 RT-002: the wire drops ``last_modified`` when ``modified`` is set
    (ruling 6187888894). A producer that sets both with different meanings
    (a period end and an upload date) must not lose the second date on every
    surface: the text fallback keeps it on its own line."""
    item = DocumentItem(id="1", name="n", modified="M-DATE", last_modified="L-DATE")
    text = DocumentList(documents=[item]).to_plain_text()
    assert item.wire()["modified"] == "M-DATE"
    assert "last_modified" not in item.wire()
    assert "    modified: M-DATE" in text
    assert "    last modified: L-DATE" in text


@pytest.mark.parametrize(
    "kwargs",
    [
        {"modified": "D"},
        {"last_modified": "D"},
        {"modified": "D", "last_modified": "D"},
    ],
)
def test_text_shows_one_date_when_only_one_is_set_or_both_equal(kwargs):
    text = DocumentList(documents=[DocumentItem(id="1", name="n", **kwargs)]).to_plain_text()
    assert "    modified: D" in text
    assert "last modified" not in text


def test_compact_schema_teaches_contract_keys_only():
    schema = parse_schema(_COMPACT_SCHEMAS["DocumentList"])
    item = {k.rstrip("?") for k in schema["documents?" if "documents?" in schema else "documents"][0]}
    assert item == {"id", "name", "type", "modified", "link", "size"}


# ── console renderer (a2ui.js) reads modified/link — w050 RT-003 ──
#
# Runs the REAL safeHttpUrl + renderDocumentList from a2ui.js under node
# (same live-source pattern as tests/test_rt004_console_renders_metadata_envelope.py).

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

_NODE_BIN = shutil.which("node")
_A2UI_JS = Path(__file__).resolve().parent.parent / "agent_sdk" / "console" / "static" / "a2ui.js"

_HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const start = src.indexOf("function safeHttpUrl");
const end = src.indexOf("const RENDERERS");
if (start < 0 || end < 0 || end <= start) throw new Error("renderer not found");
function el(tag, attrs, ...children) {
  const node = { tag, attrs: attrs || {}, children: [] };
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.children.push(typeof c === "object" ? c : { text: String(c) });
  }
  return node;
}
function card(title, sub, body) { return el("section", {}, body); }
function fmtNum(n) { return String(n); }
eval(src.slice(start, end));
process.stdout.write(JSON.stringify(renderDocumentList(JSON.parse(process.argv[2]))));
"""


def _render(docs: list[dict]) -> dict:
    out = subprocess.run(
        [_NODE_BIN, "-e", _HARNESS, "--", str(_A2UI_JS), json.dumps({"documents": docs})],
        capture_output=True, text=True, timeout=10, check=True,
    )
    return json.loads(out.stdout)


def _row_name(tree: dict) -> dict:
    # section > list div > row div > first child (the name node)
    return tree["children"][0]["children"][0]["children"][0]


def _texts(node: dict) -> list[str]:
    if "text" in node:
        return [node["text"]]
    return [t for c in node.get("children", []) for t in _texts(c)]


def test_console_source_reads_contract_keys():
    src = _A2UI_JS.read_text()
    body = src[src.index("function renderDocumentList"):src.index("const RENDERERS")]
    assert "d.modified ||" in body and "d.link" in body


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
@pytest.mark.parametrize("link", ["https://example.com/a?b=1", "http://example.com/x"])
def test_console_renders_http_link_as_anchor(link):
    name = _row_name(_render([{"id": "1", "name": "Deck", "link": link}]))
    assert name["tag"] == "a"
    assert name["attrs"]["href"].startswith(link.split("?")[0])
    assert name["attrs"]["rel"] == "noopener noreferrer"
    assert _texts(name) == ["Deck"]  # text node only, never markup


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        " JavaScript:alert(1)",
        "data:text/html,<b>x</b>",
        "vbscript:x",
        "/relative/path",
        "not a url",
        "",
        5,
    ],
)
def test_console_refuses_non_http_link(link):
    name = _row_name(_render([{"id": "1", "name": "<b>Deck</b>", "link": link}]))
    assert name["tag"] == "div"
    assert "href" not in name["attrs"]
    assert _texts(name) == ["<b>Deck</b>"]


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed")
def test_console_falls_back_to_old_keys():
    tree = _render([{"id": "1", "name": "n", "web_url": "https://e.com/", "last_modified": "L"}])
    name = _row_name(tree)
    assert name["tag"] == "a" and name["attrs"]["href"] == "https://e.com/"
    assert any("modified L" in t for t in _texts(tree))
    tree = _render([{"id": "1", "name": "n", "modified": "M", "last_modified": "L"}])
    assert any("modified M" in t for t in _texts(tree))


def test_transcript_fold_keeps_last_modified_and_web_url():
    # w050 RT-001 r8: the agent's own model copy keeps the model-side keys.
    from agent_sdk.agent.loop import fold_result_content
    from agent_sdk.models.content_types import DocumentItem, DocumentList

    doc = DocumentItem(
        id="1", name="n", modified="2025-12-31", last_modified="2026-02-03T10:00Z",
        web_url="https://x.example/d",
    )
    folded = fold_result_content(DocumentList(documents=[doc]))["json"]["documents"][0]
    assert folded["modified"] == "2025-12-31"
    assert folded["last_modified"] == "2026-02-03T10:00Z"
    assert folded["web_url"] == "https://x.example/d"
    wire = DocumentList(documents=[doc]).wire()["documents"][0]
    assert "last_modified" not in wire and "web_url" not in wire
    assert wire["link"] == "https://x.example/d"
