# w019 — GitHub issues #58, #60, #62, #63, #65, #66

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: v0.5.16.

---

- [x] `GH-66` CLAUDE.md states ADR-001-* credential files are gitignored but no .gitignore glob exists — silent security gap ‖ group:G
  - Creates: `harness/.gitignore`
  - Reads: `/Users/wailuen/Development/a2a-sdk/.gitignore`
  - Severity: critical
  - Root cause: There is no `harness/.gitignore` at all. The root `.gitignore` also lacks both `workspace/adr/ADR-000-*-credentials.md` and `workspace/adr/ADR-001-*-credentials.md` globs. `CLAUDE.md` (line 209) explicitly states both are gitignored. Any credential inventory file written by `/provision` (ADR-001-<env>-credentials.md) is silently committable.
  - AC:
    - `harness/.gitignore` is created containing both `workspace/adr/ADR-000-*-credentials.md` and `workspace/adr/ADR-001-*-credentials.md`
    - Running `git check-ignore -v workspace/adr/ADR-001-dev-credentials.md` from within an agent repo using this harness returns a match (not untracked)
    - No existing committed credential files exist in `workspace/adr/` (audit + confirm clean)
  - GH: https://github.com/wailuen/a2a-sdk/issues/66

- [x] `GH-60` /provision does not verify Storage Table Data Contributor RBAC before booting Azure Table Storage backend ‖ group:G
  - Modifies: `harness/skills/provision/SKILL.md`
  - Reads: `harness/skills/provision/SKILL.md`
  - Severity: high
  - Root cause: Phase 1b (Account name path) only asks the user to self-confirm the RBAC role — no programmatic check. Missing the role causes a silent boot failure when DefaultAzureCredential can't access the table. `az storage table list --account-name <name> --auth-mode login` can serve as a lightweight RBAC probe (403 = role absent, 200/empty = confirmed).
  - AC:
    - After collecting the storage account name in Phase 1b, the skill includes an `az storage table list --account-name <name> --auth-mode login` probe step
    - A 403/AuthorizationPermissionMismatch result halts the skill with the exact `az role assignment create` fix command and the identity being checked (`az ad signed-in-user show` or `az account show`)
    - A successful probe (200 or empty list) prints "RBAC confirmed" and continues
    - If `az` is not authenticated or not found, the skill degrades gracefully (warn + continue rather than halt)
  - GH: https://github.com/wailuen/a2a-sdk/issues/60

- [x] `GH-58` acceptance-api.js uses globalThis.crypto.randomUUID() — unavailable in Node.js < 19 ‖ group:G
  - Modifies: `harness/workflows/acceptance-api.js`
  - Reads: `harness/workflows/acceptance-api.js`
  - Severity: medium
  - Root cause: `harness/workflows/acceptance-api.js:70` uses `globalThis.crypto.randomUUID()` which is only available from Node.js 19+. Node 18 LTS throws `TypeError: globalThis.crypto.randomUUID is not a function`. Fix: replace with `require('crypto').randomUUID()` (available Node 15.6+).
  - AC:
    - Line 70 of `harness/workflows/acceptance-api.js` uses `require('crypto').randomUUID()` not `globalThis.crypto.randomUUID()`
    - No other `globalThis.crypto` usages exist in any `harness/workflows/*.js` or `.claude/workflows/*.js` file
  - GH: https://github.com/wailuen/a2a-sdk/issues/58

- [x] `GH-65` sdk-wave.js redteam prompts missing explicit Dimension 5 (no stubs/placeholders AC check) ‖ group:G
  - Modifies: `.claude/workflows/sdk-wave.js`
  - Reads: `.claude/workflows/sdk-wave.js`, `.claude/agents/core/redteam.md`
  - Severity: medium
  - Root cause: `sdk-wave.js` unit and phase redteam prompts enumerate specific dimensions (spec/protocol, type correctness, test coverage, etc.) but omit Dimension 5 — "No partial implementations, stubs, TODOs, placeholder returns". `wave-cycle.js` correctly instructs "Run all 8 dimensions from agents/core/redteam.md", but `sdk-wave.js` uses an inline list that silently drops the AC/placeholder check.
  - AC:
    - The unit redteam prompt in `sdk-wave.js` includes an explicit Dimension 5 instruction: no partial implementations, stubs, TODOs, or placeholder returns; every AC in the todo body must be met in the landed code
    - The phase redteam prompt in `sdk-wave.js` includes the same Dimension 5 mandate
    - The existing dimension list is preserved (Dimension 5 is added, not substituted)
  - GH: https://github.com/wailuen/a2a-sdk/issues/65

- [x] `GH-62` AzureTableCredentialStore boot crash error message omits pyproject.toml fix path ‖ group:G
  - Modifies: `agent_sdk/contrib/azure_utils.py`
  - Reads: `agent_sdk/contrib/azure_utils.py`, `agent_sdk/credentials/azure_table.py`, `agent_sdk/app.py`
  - Severity: medium
  - Root cause: `_INSTALL_HINT` in `azure_utils.py:34` says `"pip install agent-sdk[azure]"` only. Agents using `pyproject.toml` + `uv` need to add `agent-sdk[azure]` to their dependencies list, not run pip directly. The error message gives no hint of this, making the fix non-obvious.
  - AC:
    - `_INSTALL_HINT` in `azure_utils.py` mentions both the pip form and the pyproject.toml form: e.g. `"pip install agent-sdk[azure]  # or add 'agent-sdk[azure]' to pyproject.toml dependencies"`
    - The error message raised in `require_azure_packages()` reflects the updated hint
    - Existing test coverage for the ImportError path (if any) still passes
  - GH: https://github.com/wailuen/a2a-sdk/issues/62

- [x] `GH-63` ContentModel subclasses missing metadata escape hatch — domain disclosure fields silently dropped ‖ group:G
  - Modifies: `agent_sdk/models/content_types.py`
  - Reads: `agent_sdk/models/content_types.py`
  - Severity: medium
  - Root cause: `_Wire` ConfigDict has no `extra=` setting (Pydantic v2 defaults to `extra='ignore'`), so passing `coverage_note=` or any unknown field to any ContentModel subclass silently drops it. The non-breaking fix is to add `metadata: dict[str, Any] | None = None` to the 12 ContentModel subclasses that currently lack it (KpiCard, ComparisonTable, BarChart, EntityList, MarketBriefing, WaterfallChart, MultiCategoryChart, FundPerformance, EmailList, CalendarEvents, UserProfile, UserList, DocumentList) — mirroring the existing pattern on TimeSeriesChart and CategoryValue. Do NOT add `extra='forbid'` (breaking change).
  - AC:
    - All 12 listed ContentModel subclasses gain `metadata: dict[str, Any] | None = None` field
    - `wire()` serialises `metadata` when non-None (round-trip test)
    - Unknown non-metadata kwargs are still silently dropped (no regression — extra='ignore' stays)
    - Tests added: metadata round-trips through `wire()` for at least 2 representative types; `coverage_note` passed via `metadata={"coverage_note": "..."}` survives serialisation
  - GH: https://github.com/wailuen/a2a-sdk/issues/63
