# Plan — Azure Table Storage backends (0.4.0)

## Goal

Replace all three SQLite persistence stores with Azure Table Storage backends
so Azure Container Apps agents can run multiple replicas without losing
credential or operational state on restart. Azure Files mounts (currently
the broken workaround) are completely eliminated.

## Stores migrated

| Store | SQLite class | Azure class | ABC needed |
|-------|-------------|-------------|------------|
| CredentialStore | `EncryptedSqliteStore` | `AzureTableCredentialStore` | already exists (`CredentialStore`) |
| CommitmentStore | `CommitmentStore` (concrete) | `AzureTableCommitmentStore` | extract `CommitmentBackend` |
| SubscriptionStore | `SubscriptionStore` (concrete) | `AzureTableSubscriptionStore` | extract `SubscriptionBackend` |

## Wave summary

| Wave | File | Parallel group | Slices | Depends |
|------|------|---------------|--------|---------|
| W0 ✅ 2026-06-14 | w000-scaffold.md | sequential | 5 | — |
| W1 ✅ 2026-06-14 | w001-azure-credential-store.md | B (parallel with W2,W3) | 6 | W0 complete |
| W2 ✅ 2026-06-14 | w002-azure-commitment-store.md | C (parallel with W1,W3) | 6 | W0 complete |
| W3 ✅ 2026-06-14 | w003-azure-subscription-store.md | D (parallel with W1,W2) | 5 | W0 complete |
| W4 ✅ 2026-06-14 | w004-wire-migrate.md | sequential | 7 | W1+W2+W3 complete |
| W5 ✅ 2026-06-14 | w005-template-docs.md | E (parallel within) | 6 | W4 complete |

**Total:** 6 waves, 35 slices

## Dependency graph

```
W0 (scaffold)
 ├─▶ W1 (credential store) ─┐
 ├─▶ W2 (commitment store)  ├─▶ W4 (wire + migrate CLI) ─▶ W5 (docs)
 └─▶ W3 (subscription store)┘
```

## Security invariants covered

| SI | Scope |
|----|-------|
| SI-4 | AzureTableCredentialStore.get() never exposes plaintext in exceptions or logs |
| SI-6 | AZURE_STORAGE_CONNECTION_STRING treated as `SecretStr`; never logged; .env.example marks it secret |
| Encryption | AES-256-GCM envelope preserved end-to-end; plaintext never written to Table Storage |
| MASTER_KEY | Same min-32-char requirement enforced in Azure path as SQLite path |

## Optional dependency

`pyproject.toml` `[azure]` extra: `azure-data-tables>=12.5`, `azure-identity>=1.15`.
Clear `ImportError` at module load if Azure backend configured but packages absent.

## Auto-detection logic (app.py)

```
AZURE_STORAGE_CONNECTION_STRING set → AzureTableCredentialStore(connection_string=...)
AZURE_STORAGE_ACCOUNT_NAME set     → AzureTableCredentialStore(account_name=...) via DefaultAzureCredential
Neither                            → EncryptedSqliteStore (dev default, unchanged)
```

Same logic exposed as `create_commitment_backend(settings)` and
`create_subscription_backend(settings)` factory functions in contrib modules.

## New settings fields (BaseAgentSettings)

| Field | Alias | Type | Default |
|-------|-------|------|---------|
| `azure_storage_connection_string` | `AZURE_STORAGE_CONNECTION_STRING` | `SecretStr \| None` | `None` |
| `azure_storage_account_name` | `AZURE_STORAGE_ACCOUNT_NAME` | `str \| None` | `None` |
| `azure_storage_table_prefix` | `AZURE_STORAGE_TABLE_PREFIX` | `str` | `"agent"` |

## Migrate CLI

`python -m agent_sdk migrate-store [--data-dir ./data] [--dry-run] [--force]`

Implemented in `agent_sdk/__main__.py` as `_cmd_migrate_store()`.
