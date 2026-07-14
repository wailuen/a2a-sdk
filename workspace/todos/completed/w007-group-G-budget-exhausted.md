# Deferred: Wave w007 Group G — RESOLVED

- **Wave ID:** w007
- **Group:** G
- **Date:** 2026-06-14
- **Rounds completed:** 5 (budget exhausted)
- **Resolved:** 2026-07-14
- **Status:** All findings resolved — archive reconciled

---

## Findings (all resolved)

### RT-001 — medium — RESOLVED
**File:** `harness/skills/setup/SKILL.md`

The Azure OpenAI non-secret routing vars section omitted `AZURE_API_VERSION`.

**Fix applied:** Both Phase 0 step 5 and the Phase 3 write list now include `AZURE_API_VERSION` (e.g. `2025-01-01-preview`) alongside `AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_DEPLOYMENT`.

---

### RT-002 — low — RESOLVED
**File:** `harness/skills/upgrade/SKILL.md`

Step 10a stated the harness manifest "is written by `/new-agent` on first seed", omitting that `/setup` also initializes it via placeholder substitution.

**Fix applied:** Wording now reads "written by `/new-agent` (from scratch) or initialized by `/setup` (via placeholder substitution) on first seed" (both at step 10a and in the closing summary section).

---

### RT-003 — low — RESOLVED
**File:** `harness/skills/agent-verify/SKILL.md`

Phase 1 note undersold what `DEV_MODE` relaxes, omitting the per-request DNS-rebinding guard.

**Fix applied:** Parenthetical extended to "(DEV_MODE relaxes MASTER_KEY/PUBLIC_URL/secure-transport checks and the per-request DNS-rebinding guard in SourceAdapter — localhost adapter targets are valid only in DEV_MODE)".

---

### RT-004 — low — RESOLVED
**File:** `harness/skills/wave/SKILL.md`

The "Planning step" header overstated the skip scope ("runs once; skipped if plan.md + active/ waves already exist").

**Fix applied:** Header now reads "Planning step (runs once; plan generation (steps 6–9) skipped if plan.md + active/ waves already exist and user confirms \"use\")".

---

### W007-003 — AC wording imprecision (no code change) — RESOLVED (no action required)
**File:** `harness/reference/sdk-security-invariants.md` (SI-6 Prevention clause)

GH-12's AC referenced a nonexistent `python -m agent_sdk provision` CLI subcommand; the landed SI-6 Prevention text ("admin console credential form or the `/provision` skill") was already correct. No code or doc change required — confirmed still accurate.
