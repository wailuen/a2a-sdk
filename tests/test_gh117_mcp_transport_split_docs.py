"""GH-117: DESIGN.md §5.5 and REVIEWS.md Round-1 disposition table must match
the transport-split MCP-Protocol-Version absent-header behavior shipped in
commit bbfe353 (mcp.py module docstring), not the earlier blanket rule.

Streamable HTTP (POST /mcp, non-initialize) — absent header → negotiated session version (GH-200).
Legacy SSE (POST /mcp/messages) — absent header → allowed, assume 2025-03-26.

ACs verified:
  1. DESIGN.md §5.5 explicitly distinguishes Streamable HTTP vs Legacy SSE
     absent-header behavior.
  2. REVIEWS.md's Round-1 MCP advisor disposition table row is updated to
     match (no longer states a blanket absent→2025-03-26 rule).
  3. `grep -n "assume 2025-03-26" DESIGN.md` shows transport-split language
     (the matching line is scoped to Legacy SSE), not a blanket rule.
"""

from __future__ import annotations

import re
from pathlib import Path

import agent_sdk.app as _app_module


def _repo_root() -> Path:
    return Path(_app_module.__file__).parent.parent


def _design_md_text() -> str:
    return (_repo_root() / "DESIGN.md").read_text()


def _reviews_md_text() -> str:
    return (_repo_root() / "REVIEWS.md").read_text()


def _section_5_5(content: str) -> str:
    start = content.index("### 5.5 MCP")
    end = content.index("### 5.6 Surface parity rule")
    return content[start:end]


def _protocol_version_bullet(section: str) -> str:
    start = section.index("`MCP-Protocol-Version` header")
    end = section.index("\n\n", start)
    return section[start:end]


# ---------------------------------------------------------------------------
# AC-1: DESIGN.md §5.5 distinguishes Streamable HTTP vs Legacy SSE
# ---------------------------------------------------------------------------


def test_design_md_section_5_5_mentions_streamable_http_and_legacy_sse_for_absent_header():
    bullet = _protocol_version_bullet(_section_5_5(_design_md_text()))
    assert "Streamable HTTP" in bullet, (
        "DESIGN.md §5.5's MCP-Protocol-Version bullet must name the "
        "Streamable HTTP transport explicitly"
    )
    assert "Legacy SSE" in bullet, (
        "DESIGN.md §5.5's MCP-Protocol-Version bullet must name the "
        "Legacy SSE transport explicitly"
    )


def test_design_md_streamable_http_absent_header_uses_session_version():
    bullet = _protocol_version_bullet(_section_5_5(_design_md_text()))
    idx = bullet.index("Streamable HTTP")
    end = bullet.index("Legacy SSE")
    window = bullet[idx:end]
    for needle in (
        "GH-200",
        "negotiated",
        "2025-03-26",
        "Present-but-unrecognized → 400",
    ):
        assert needle in window, (
            f"DESIGN.md §5.5 Streamable HTTP clause must contain {needle!r} "
            "(GH-200: absent header uses the session-negotiated version)"
        )
    assert not re.search(r"Streamable HTTP[^.]{0,40}400s? on absent", window)


def test_design_md_legacy_sse_absent_header_assumes_default_version():
    bullet = _protocol_version_bullet(_section_5_5(_design_md_text()))
    idx = bullet.index("Legacy SSE")
    window = bullet[idx: idx + 300]
    assert "2025-03-26" in window, (
        "DESIGN.md §5.5 must state that Legacy SSE absent-header requests "
        "assume 2025-03-26, in the same clause as 'Legacy SSE'"
    )


def test_design_md_no_longer_states_blanket_absent_rule():
    section = _section_5_5(_design_md_text())
    assert "absent → assume `2025-03-26`" not in section, (
        "DESIGN.md §5.5 must not state a blanket (transport-unqualified) "
        "absent-header rule; the old wording implied this applied to "
        "Streamable HTTP too, which uses the session-negotiated version (GH-200)"
    )


# ---------------------------------------------------------------------------
# AC-3: grep -n "assume 2025-03-26" DESIGN.md shows transport-split language
# ---------------------------------------------------------------------------


def test_grep_assume_2025_03_26_line_is_transport_scoped_to_legacy_sse():
    content = _design_md_text()
    matches = [line for line in content.splitlines() if "assume 2025-03-26" in line]
    assert matches, (
        "DESIGN.md must contain a literal 'assume 2025-03-26' line "
        "(grep -n \"assume 2025-03-26\" DESIGN.md must find it)"
    )
    for line in matches:
        assert "Legacy" in line or "SSE" in line, (
            f"Every DESIGN.md line containing 'assume 2025-03-26' must be "
            f"scoped to the Legacy SSE transport, not a blanket rule; got: {line!r}"
        )


# ---------------------------------------------------------------------------
# AC-2: REVIEWS.md Round-1 MCP disposition table updated to match
# ---------------------------------------------------------------------------


def _round_1_mcp_advisor_table(content: str) -> str:
    start = content.index("### MCP advisor")
    end = content.index("### Architecture / security")
    return content[start:end]


def test_reviews_md_round1_mcp_table_no_longer_states_blanket_rule():
    table = _round_1_mcp_advisor_table(_reviews_md_text())
    assert "absent→2025-03-26" not in table.replace(" ", ""), (
        "REVIEWS.md Round-1 MCP advisor table must not state the old "
        "blanket 'absent→2025-03-26' rule for the MCP-Protocol-Version row"
    )


def test_reviews_md_round1_mcp_table_reflects_transport_split():
    table = _round_1_mcp_advisor_table(_reviews_md_text())
    version_row = next(
        (line for line in table.splitlines() if "MCP-Protocol-Version header validation" in line),
        None,
    )
    assert version_row is not None, (
        "REVIEWS.md Round-1 MCP advisor table must have a row about "
        "MCP-Protocol-Version header validation"
    )
    assert re.search(r"Streamable", version_row), (
        f"REVIEWS.md Round-1 MCP-Protocol-Version row must mention the "
        f"Streamable HTTP transport; got: {version_row!r}"
    )
    assert re.search(r"Legacy", version_row), (
        f"REVIEWS.md Round-1 MCP-Protocol-Version row must mention the "
        f"Legacy SSE transport; got: {version_row!r}"
    )
    assert "GH-77" in version_row, (
        f"REVIEWS.md Round-1 MCP-Protocol-Version row should reference "
        f"GH-77; got: {version_row!r}"
    )
