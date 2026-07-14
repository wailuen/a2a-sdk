# Deferred: w032 group:G — RESOLVED

- **Wave:** w032
- **Group:** group:G
- **Date:** 2026-07-13
- **Rounds completed:** 5 (budget exhausted)
- **Resolved:** 2026-07-14
- **Status:** All findings resolved — archive reconciled

---

## Findings (all resolved)

### RT-001 — medium — RESOLVED
**File:** DESIGN.md

DESIGN.md §5.4 line 339 stated the route-resolved A2UI capability default is "Absent → tier=core, catalogs=[standard]", contradicting the landed fail-closed `_capabilities()` in both `agent_sdk/routes/ag_ui.py` and `agent_sdk/routes/a2a.py` (both return `tier="none"` when the client sends no opt-in signal) and LRN-115.

**Fix applied:** DESIGN.md §5.4 now states the route-level default is fail-closed (no opt-in signal → `tier="none"`, suppress A2UI); it clarifies that `tier="core"` is only the `A2uiCapabilities.from_metadata()` payload-parsing default for an already-scoped capabilities payload, not the raw-request absence default, and cross-references LRN-046/LRN-115.

---

### RT-002 — low — RESOLVED
**File:** tests/test_gh110_origin_allowlist.py

GH-110 AC requires regression tests asserting pass-through for "absent/allowed Origin, for both surfaces", but the A2A route tests only covered the absent-Origin case; no A2A route test sent an allowlisted Origin header.

**Fix applied:** `tests/test_gh110_origin_allowlist.py` now includes A2A allowlisted-origin pass-through tests (`test_message_send_allows_allowlisted_origin`, `test_message_stream_allows_allowlisted_origin`, `test_tasks_list_allows_allowlisted_origin`, `test_tasks_get_allows_allowlisted_origin`, `test_tasks_cancel_allows_allowlisted_origin`, `test_tasks_resubscribe_allows_allowlisted_origin`), matching the existing AG-UI coverage.

---

### RT-003 — low — RESOLVED
**File:** agent_sdk/routes/a2a.py

The fail-closed `tier="none"` default was duplicated between `agent_sdk/routes/a2a.py`'s `_capabilities` and `agent_sdk/routes/ag_ui.py`'s `_capabilities`; the C-006 `A2uiCapabilityGate` extraction that would define this fail-closed default once remained registered as "planned".

**Fix applied:** `A2uiCapabilities.gated(opted_in, raw)` is now implemented in `agent_sdk/a2ui/translator.py`; both routes' `_capabilities` compute their own transport-specific `opted_in`/`raw` and delegate to it. C-006 is registered "present" in `workspace/components/README.md`.

---

## Housekeeping note (2026-07-14)

Per LRN-100, swept `workspace/todos/deferred/` for other budget-exhausted markers whose findings had since been resolved:

- `w000-group-A-budget-exhausted.md` — all 3 findings verified resolved (G-A-002's overly-broad `except Exception` in `agent_sdk/credentials/crypto.py:decrypt()` was fixed in this same pass, narrowed to `except (InvalidTag, ValueError)` with a new RED→GREEN regression test in `tests/test_crypto.py`) — moved to `completed/`.
- `w007-group-G-budget-exhausted.md` — all findings verified resolved in `harness/skills/*/SKILL.md` — moved to `completed/`.
- `w015-group-A-budget-exhausted.md`, `w015-group-B-budget-exhausted.md`, `w015-group-group:A-budget-exhausted.md`, `w015-group-group:B-budget-exhausted.md` — spot-checked and found to still carry **open, unresolved** findings (e.g. RT-PARSE-400 and RT-DELETE-LEN-GUARD in `agent_sdk/routes/mcp.py`, RT-SAFE-GET-SI2-001 in `agent_sdk/common/http.py`, RT-JSON-POINTER-001 in `agent_sdk/a2ui/translator.py`, and multiple `harness/workflows/wave-cycle.js` items in the two `WC-*` files). These four remain in `deferred/` — moving them would itself violate LRN-100. They need a dedicated fix pass, out of scope for this cleanup.
