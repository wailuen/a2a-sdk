# Deferred: w022 group:G — RESOLVED

- **Wave ID:** w022
- **Group:** group:G
- **Date:** 2026-06-15
- **Rounds completed:** 5 (budget exhausted)
- **Resolved:** 2026-07-10
- **Status:** All findings resolved — archive reconciled

---

## Findings (all resolved)

### RT-001 — low — RESOLVED (superseded by design decision)
**File:** `tests/test_mcp_gh77_absent_version_header.py`

GH-77's fix was extended to the legacy POST /mcp/messages path (mcp.py:706-716) for consistency, but the new test file only exercised the Streamable HTTP path (POST /mcp); the legacy SSE-pair absent-header branch had no integration test.

**Resolution:** A later commit (`bbfe353`, w022 phase-redteam RT-004) locked the actual design: the legacy SSE path deliberately does **not** enforce GH-77's 400-on-absent-header rule — per MCP spec §10 "SHOULD" (not MUST), absent `MCP-Protocol-Version` on `POST /mcp/messages` is allowed and assumes `2025-03-26`, documented in `agent_sdk/routes/mcp.py`'s module docstring. `tests/test_mcp_legacy_initialize.py::test_legacy_non_initialize_absent_version_header_returns_202` now covers exactly this path and asserts the correct (202, not 400) behavior. The original fix instruction (assert 400) is obsolete against the locked design; the coverage gap it flagged is closed by the existing 202 assertion.

---

### RT-002 — low — RESOLVED (documented as deliberate; finding was a false positive)
**File:** `agent_sdk/routes/a2a.py:364`

`tasks_get` returns `A2A_UNSUPPORTED_OPERATION` (-32004 -> HTTP 501) when `':'` appears in `task_id` (e.g. a client GETs `/v1/tasks/{id}:cancel`). The finding read this as inconsistent with DESIGN §5.1's "unknown id -> 404 + -32001" contract.

**Resolution:** This was already the deliberate, locked behavior from `GH-25` AC-3 (w012, commit `b8d4a04`, "eliminating flip-flopping root causes"): a colon-bearing `task_id` is a wrong-HTTP-verb-on-a-mutation-path miss (`GET` on the shape of `/v1/tasks/{id}:cancel`), not a genuinely unknown task — returning -32001 there would misleadingly claim "no such task" when the real problem is the verb. This is independently codified and passing at `tests/test_a2a_error_envelope.py::test_task_id_with_colon_returns_unsupported_operation`, which predates this finding (landed in w012, GH issue #25) and explicitly asserts -32004, not -32001, for this exact case. RT-002 missed that prior lock. Per the finding's own second option ("...or document the deliberate 501 choice with a spec citation in the handler"), a citation comment was added at `agent_sdk/routes/a2a.py:364-366` referencing GH-25 AC-3 so a future pass doesn't re-flag this. No behavior change; DESIGN §5.1's "unknown id" language governs ids that are plausibly real task ids, not colon-shaped sub-resource paths — worth a future DESIGN.md clarification but out of scope for this housekeeping pass.

Full suite: `.venv/bin/pytest -q tests/` green (see reconciliation run below).
