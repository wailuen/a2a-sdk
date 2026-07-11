# Deferred: w030 group G — RESOLVED

- **Wave ID:** w030
- **Group:** G
- **Date:** 2026-07-10
- **Rounds completed:** 5 (budget exhausted)
- **Resolved:** 2026-07-11
- **Status:** All findings resolved

---

## Findings (all resolved)

### RT-001 — low — RESOLVED
**File:** `agent_sdk/routes/mcp.py`

The leading comment block on the MCP structuredContent assembly (lines 416-419) asserted unconditionally that MarketBriefing's wire value "is a markdown string (to_markdown()), never the field dict (wire())" and cited DESIGN §4.3 — but that is true only for the AG-UI/A2A surface; on the MCP surface this same code path emits `{"markdown": <str>}`, an object. The correction only appeared in the GH-105 addendum four lines further down, so the leading sentence read as a false claim about the surface it documents.

**Fix applied:** Reworded the comment block so the AG-UI/A2A-scoped claim ("its wire value is a bare markdown string ... on the AG-UI/A2A wire") comes first, and the GH-105 addendum now explicitly opens with "on THIS (MCP) surface" before explaining the `{"markdown": ...}` object wrapping. Verified at `agent_sdk/routes/mcp.py:414-424`.

**sdkCandidate:** false

---

## Reconciliation note

Fix verified by re-reading `agent_sdk/routes/mcp.py:414-424` after edit — the
leading sentence is now scoped to the AG-UI/A2A wire and no longer makes an
unqualified claim about the surface the comment documents (MCP). No other
open findings remain for w030 group G. A resumed `/wave w030` will find no
open work in this group.
