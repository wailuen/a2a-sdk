# w005 — Template, docs, and CHANGELOG

Mostly parallel after W4 complete. Items in group:E are independent file
edits with no intra-wave file dependency. P5-05 (CHANGELOG) should be last
as it summarizes what changed, but it has no code dependency on P5-00..P5-04.

All items ‖ group:E (parallel within wave). P5-05 may be done last for
completeness but has no code dependency on the others.

---

- [ ] `P5-00` Add `a002-azure-table-store.md` ADR to template workspace ‖ group:E
  - Creates: `template/workspace/adr/a002-azure-table-store.md`
  - Reads: `template/workspace/adr/a001-credential-model.md` (format reference)
  - Depends: W4 complete (P4-06)
  - AC: ADR follows the format of `a001-credential-model.md`. Contains: `id: ADR-002`, `title: Azure Table Storage persistence backends`, `status: accepted`, `date: 2026-06-14`. Sections: Context (Azure Files mount workaround was broken, multi-replica incompatibility), Decision (three Azure backends, auto-detection logic, encryption envelope preserved, ETag at-most-once for commitments), Consequences (multi-replica enabled, Azure Files eliminated, `[azure]` extra required, MASTER_KEY required same as SQLite, migrate-store CLI for migration), Anti-patterns (never store plaintext credentials in Table Storage, never log connection string). References SI-4 and SI-6.

- [ ] `P5-01` Update `template/.env.example` with Azure Storage vars ‖ group:E
  - Creates: (modifies `template/.env.example`)
  - Reads: `template/.env.example`
  - Depends: W4 complete (P4-06)
  - SI: SI-6
  - AC: `.env.example` gains a new section `# ── Azure Storage (optional; enables multi-replica deployments) ───────────────`. Contains: `# AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...` (commented out; note says "treat as secret — do not commit"), `# AZURE_STORAGE_ACCOUNT_NAME=` (commented out; note says "use with managed identity; omit connection string"), `# AZURE_STORAGE_TABLE_PREFIX=agent` (commented out; default shown). A comment block explains: "Set ONE of the above — never both. When set, credentials, commitments, and subscription state are stored in Azure Table Storage instead of local SQLite files, enabling multi-replica Azure Container Apps deployments." The word "secret" appears next to `AZURE_STORAGE_CONNECTION_STRING` in the comment (SI-6 awareness).

- [ ] `P5-02` Update `template/CLAUDE.md` credential model table ‖ group:E
  - Creates: (modifies `template/CLAUDE.md`)
  - Reads: `template/CLAUDE.md`
  - Depends: W4 complete (P4-06)
  - AC: The "Credential model" table in `template/CLAUDE.md` gains a new row: `| Azure Storage connection string | `.env` — operational infra config (treat as secret; use managed identity in prod) | `AZURE_STORAGE_CONNECTION_STRING` env var (read by SDK, not by adapter code) | Azure Table Storage | `. A note below the table clarifies: "AZURE_STORAGE_CONNECTION_STRING is the one exception to the 'no secrets in .env' rule — it is infrastructure plumbing, not an upstream API key. Prefer managed identity (AZURE_STORAGE_ACCOUNT_NAME only, no key) in production ACA deployments."

- [ ] `P5-03` Update `docs/deployment.md` — Azure Container Apps + Table Storage guide ‖ group:E
  - Creates: (modifies `docs/deployment.md`)
  - Reads: `docs/deployment.md`
  - Depends: W4 complete (P4-06)
  - AC: `docs/deployment.md` gains a new top-level section `## Azure Container Apps + multi-replica`. Contents: (1) Overview: why Azure Files mounts failed (no atomic SQLite writes across replicas) and how Azure Table Storage solves it. (2) Prerequisites: `pip install agent-sdk[azure]`, an Azure Storage account. (3) Configuration: two auth modes — connection string (dev/test) vs managed identity (production ACA). (4) Table naming: `{AZURE_STORAGE_TABLE_PREFIX}credentials`, `...commitments`, `...subscriptions`. (5) Migration from SQLite: `python -m agent_sdk migrate-store --data-dir ./data` command with `--dry-run` and `--force` flags explained. (6) Replicas: set `replicas: 2+` in ACA YAML; `WEB_CONCURRENCY` stays 1 per replica. (7) Security: MASTER_KEY required; connection string never in logs; managed identity preferred. (8) Known limitations: in-memory task store is still per-replica (tasks are short-lived; this is acceptable).

- [ ] `P5-04` Update harness `upgrade` skill to detect Azure migration opportunity ‖ group:E
  - Creates: (modifies `template/.claude/skills/upgrade/SKILL.md`)
  - Reads: `template/.claude/skills/upgrade/SKILL.md`
  - Depends: W4 complete (P4-06)
  - AC: Step 10 of the `/upgrade` skill gains a sub-step: "10e. Azure migration opportunity check. After harness sync, if the upgraded SDK version is >= 0.4.0 AND the agent's `.env` or `.env.example` does NOT contain `AZURE_STORAGE_CONNECTION_STRING` or `AZURE_STORAGE_ACCOUNT_NAME`, emit: 'Azure Table Storage backends are available in this SDK version. If deploying to Azure Container Apps with multiple replicas, set AZURE_STORAGE_CONNECTION_STRING (or use managed identity via AZURE_STORAGE_ACCOUNT_NAME) and run `python -m agent_sdk migrate-store` to migrate existing SQLite data. See docs/deployment.md for the full guide.'" This is advisory only — no automatic writes.

- [ ] `P5-05` Add 0.4.0 Azure Storage entry to `CHANGELOG.md` ‖ group:E
  - Creates: (modifies `CHANGELOG.md`)
  - Reads: `CHANGELOG.md`
  - Depends: W4 complete (P4-06)
  - AC: Under `## [0.4.0] — unreleased`, adds a new `### Added` bullet: "**Azure Table Storage persistence backends** — `AzureTableCredentialStore`, `AzureTableCommitmentStore`, `AzureTableSubscriptionStore` replace SQLite for multi-replica Azure Container Apps deployments. Auto-detected from `AZURE_STORAGE_CONNECTION_STRING` (connection string) or `AZURE_STORAGE_ACCOUNT_NAME` (managed identity). AES-256-GCM encryption envelope preserved end-to-end for credentials. ETag optimistic concurrency preserves at-most-once commitment firing across replicas. Optional `[azure]` extra: `pip install agent-sdk[azure]`." And a new `### Added` bullet: "**`migrate-store` CLI** — `python -m agent_sdk migrate-store [--data-dir ./data] [--dry-run] [--force]` migrates existing SQLite credential, commitment, and subscription data to Azure Table Storage." And a `### Changed` bullet: "`BaseAgentSettings` gains three new fields: `AZURE_STORAGE_CONNECTION_STRING` (`SecretStr | None`), `AZURE_STORAGE_ACCOUNT_NAME` (`str | None`), `AZURE_STORAGE_TABLE_PREFIX` (`str`, default `agent`)."
