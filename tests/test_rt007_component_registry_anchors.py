"""RT-007: workspace/components/README.md must anchor components by symbol
name, never by `path:line` or `(line NNN)` literals — those drift silently
whenever an unrelated edit shifts line numbers elsewhere in the file (LRN-108),
and a hand-maintained line number becomes stale narrative the moment it does
(LRN-066). C-016's own body already states the intended contract ("Anchored
by symbol name rather than line number so this entry cannot drift on
unrelated edits to the file"); this test makes that contract mechanical
instead of aspirational."""

from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "workspace" / "components" / "README.md"

PATH_LINE_ANCHOR = re.compile(r"[\w./-]+\.(?:py|md|js):\d+")
PAREN_LINE_ANCHOR = re.compile(r"\(line \d+\)")


def test_component_registry_has_no_path_colon_line_anchors():
    text = README.read_text()
    matches = PATH_LINE_ANCHOR.findall(text)
    assert not matches, (
        "workspace/components/README.md must not anchor a component to a "
        f"bare path:line literal (RT-007/LRN-108); found: {matches}"
    )


def test_component_registry_has_no_parenthetical_line_anchors():
    text = README.read_text()
    matches = PAREN_LINE_ANCHOR.findall(text)
    assert not matches, (
        "workspace/components/README.md must not cite a call site by "
        f"'(line NNN)' (RT-007/LRN-108); found: {matches}"
    )
