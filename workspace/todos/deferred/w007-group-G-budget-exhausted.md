# Deferred: Wave w007 Group G — Budget Exhausted

wave_id: w007
group: G
date: 2026-06-14
rounds: 5
reason: budget exhausted

## Findings

### RT-001 — medium
**File:** harness/skills/setup/SKILL.md

The Azure OpenAI non-secret routing vars section (Phase 0 step 5 and Phase 3 step 2) lists only AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT but omits AZURE_API_VERSION. The actual SDK config (agent_sdk/config.py:61) has `azure_api_version: str | None = Field(default=None, alias='AZURE_API_VERSION')` and the template .env.example recommends `AZURE_API_VERSION=2025-01-01-preview`. The openai.AsyncAzureOpenAI client receives this as api_version=None when not set, which causes Azure API calls to fail at runtime because Azure OpenAI requires the api-version query parameter.

**Fix:** Add AZURE_API_VERSION to the Azure OpenAI routing-vars list in Phase 0 step 5 (with example value e.g. 2025-01-01-preview) and to the Phase 3 step 2 write list alongside AZURE_OPENAI_ENDPOINT= and AZURE_OPENAI_DEPLOYMENT=.

---

### RT-002 — low
**File:** harness/skills/upgrade/SKILL.md

Step 10a states 'This file is written by /new-agent on first seed'. This is incomplete: /setup also initializes the manifest by performing placeholder substitution on the template's .claude/.harness-manifest.json (which ships with {{SDK_SHA}} placeholders). Agents bootstrapped via /setup — not /new-agent — will have a manifest initialized by /setup, not /new-agent. The fallback logic ('If the manifest is absent ... fall back to current_sha') will work, but the explanation misleads operators who used /setup.

**Fix:** Change 'written by /new-agent on first seed' to 'written by /new-agent (from scratch) or initialized by /setup (via placeholder substitution) on first seed'.

---

### RT-003 — low
**File:** harness/skills/agent-verify/SKILL.md

Phase 1 note states '(DEV_MODE relaxes only the MASTER_KEY/PUBLIC_URL/secure-transport checks)'. This is incomplete. DEV_MODE also relaxes the per-request DNS-rebinding guard in agent_sdk/sources.py:99 — the guard that re-resolves the hostname at request time and rejects private/link-local IPs is skipped in DEV_MODE to allow localhost adapters during development. The omission could lead reviewers to believe the DNS-rebinding check always runs, masking a known attack surface difference between dev and prod.

**Fix:** Extend the parenthetical to include the per-request DNS-rebinding guard: '(DEV_MODE relaxes MASTER_KEY/PUBLIC_URL/secure-transport checks and the per-request DNS-rebinding guard in SourceAdapter — localhost adapter targets are valid only in DEV_MODE)'.

---

### RT-004 — low
**File:** harness/skills/wave/SKILL.md

The 'Planning step' header reads 'runs once; skipped if plan.md + active/ waves already exist', implying the entire planning step is bypassed. However, steps 1-4 (reading PRD, ADR, learning, components) always execute before step 5 checks for an existing plan. Only the plan generation and redteam legs (steps 6-9) are conditionally skipped when the user answers 'use'. The header overstates the skip scope.

**Fix:** Change the header to 'runs once; plan generation (steps 6-9) skipped if plan.md + active/ waves already exist and user confirms use'.

---

### W007-003 — AC wording imprecision (no code change)
**File:** harness/reference/sdk-security-invariants.md (SI-6 Prevention clause)

The GH-12 acceptance criterion references `python -m agent_sdk provision` as the provisioning path, but `provision` is not a real SDK CLI subcommand (the SDK only exposes `rotate-master-key` and `bump-patch`). The implemented SI-6 Prevention text correctly reads "admin console credential form or the `/provision` skill", which is more accurate than the AC wording.

**Resolution:** No code or doc change required to sdk-security-invariants.md. The implementation is correct. The AC wording in GH-12 was imprecise; the `/provision` skill (not a CLI subcommand) is the right path. Auditors checking the literal AC string `python -m agent_sdk provision` will not find it — this is expected and acceptable.
