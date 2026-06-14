---
id: ADR-002
title: Azure Table Storage persistence backends
status: accepted
date: 2026-06-14
---

## Context

The template Dockerfile mounts `/data` as a Docker volume for the SQLite credential store.
In Azure Container Apps deployments with multiple replicas, Azure Files was used to share
that volume across instances. This approach is broken: SQLite requires POSIX advisory locks
for atomic writes, and Azure Files does not provide them across separate replicas. The result
was data loss (concurrent writes corrupting the store) and startup races (two replicas both
attempting to bootstrap the admin key simultaneously).

Single-replica deployments are unaffected, but the inability to scale out is a hard ceiling
on availability and throughput for production ACA deployments.

## Decision

Introduce three Azure Table Storage backends that replace the SQLite stores for multi-replica
deployments:

- `AzureTableCredentialStore` — replaces `CredentialStore` (SQLite)
- `AzureTableCommitmentStore` — replaces the commitments SQLite table
- `AzureTableSubscriptionStore` — replaces the subscription-state SQLite table

**Auto-detection.** `BaseAgentSettings` gains three new optional fields:
`AZURE_STORAGE_CONNECTION_STRING` (`SecretStr | None`), `AZURE_STORAGE_ACCOUNT_NAME`
(`str | None`), and `AZURE_STORAGE_TABLE_PREFIX` (`str`, default `"agent"`).
If either Azure storage field is set at boot, the SDK automatically wires the Azure
backends. Otherwise, SQLite is used as before — no migration is required for single-replica
deployments.

**Authentication modes.**
- Connection string (`AZURE_STORAGE_CONNECTION_STRING`): for development and test environments.
  Treat as a secret; do not commit. Never log.
- Managed identity (`AZURE_STORAGE_ACCOUNT_NAME` only, no connection string): preferred for
  production ACA deployments. No secret to rotate.

**Encryption.** The AES-256-GCM encryption envelope used by `CredentialStore` is preserved
end-to-end. Plaintext credential values are never written to Table Storage; the encrypted
ciphertext blob is stored as an opaque field, decrypted in-process using `MASTER_KEY`.

**Concurrency.** `AzureTableCommitmentStore` uses Azure Table Storage ETags with
`MatchConditions.IfNotModified` for optimistic concurrency on commitment-claiming writes.
This provides the at-most-once firing guarantee across replicas that a single-replica SQLite
`EXCLUSIVE` transaction provided locally.

**Caching.** `AzureTableCredentialStore` maintains a per-replica in-memory read cache with a
5-minute TTL. Credential values are assumed to be relatively stable; the TTL balances
latency reduction against propagation delay for rotations.

**Installation.** Azure Table Storage support is an optional extra to avoid pulling
`azure-data-tables` into deployments that do not need it:
```
pip install agent-sdk[azure]
```

**Migration.** A `migrate-store` CLI command migrates existing SQLite data to Azure Table
Storage:
```bash
python -m agent_sdk migrate-store [--data-dir ./data] [--dry-run] [--force]
```

SQLite remains the default for single-replica and local deployments. The Azure backends are
additive — existing deployments are unaffected unless both `AZURE_STORAGE_*` settings and
`pip install agent-sdk[azure]` are present.

## Consequences

- Multi-replica Azure Container Apps deployments are now supported without Azure Files mounts.
- Azure Files mount requirement is eliminated; the `/data` volume is only needed for single-
  replica deployments.
- `pip install agent-sdk[azure]` is required to activate the Azure path. The base install is
  unchanged.
- `migrate-store` CLI provides a documented, reversible migration path with `--dry-run` preview.
- `MASTER_KEY` minimum 32-character requirement is unchanged; it still encrypts all credential
  values in Table Storage.
- In-memory task store remains per-replica (acceptable — tasks are short-lived; see Known
  Limitations).

## Anti-patterns

```
❌  plaintext credential value in any Table Storage field
❌  AZURE_STORAGE_CONNECTION_STRING in logs or error messages (SI-6)
❌  MASTER_KEY shorter than 32 characters (same constraint as SQLite path)
❌  Setting both AZURE_STORAGE_CONNECTION_STRING and AZURE_STORAGE_ACCOUNT_NAME
    simultaneously — set exactly one
```

## References

- SI-4: Credentials resolved via `self.credential()`, never `os.environ`.
- SI-6: Upstream vendor keys (and infrastructure secrets) never in logs or `.env` as plaintext.
