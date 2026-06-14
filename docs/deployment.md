# Deployment

## The two invariants

1. **Exactly one process per deployment.** The task store, SSE subscriber
   queues and rate limiter are process-local. The template Dockerfile
   hard-codes `--workers 1`; the SDK refuses `WEB_CONCURRENCY > 1` at boot
   (best-effort — `uvicorn --workers N` bypasses the env var; the
   Dockerfile is the real control). Multi-replica support arrives only
   with a shared `TaskStore` backend.

2. **One origin (subdomain) per agent.** RFC 8615 well-known URIs are
   origin-rooted: the agent card, the protected-resource metadata
   (including the path-suffixed `/.well-known/oauth-protected-resource/mcp`)
   and the AS metadata must live at the origin root. Path-prefix
   deployments (`https://host/agents/foo/`) therefore need reverse-proxy
   rewrites of the well-known namespace:

   ```nginx
   location /.well-known/ { proxy_pass http://agent-foo/.well-known/; }
   location /agents/foo/  { proxy_pass http://agent-foo/; }
   ```

   The console self-check verifies the externally-visible URLs either way.
   All advertised URLs derive from `PUBLIC_URL`.

## Docker

The template Dockerfile is the reference: BuildKit SSH mount for the
private git dependency (GitHub host keys baked from published
fingerprints — never build-time `ssh-keyscan`), multi-stage, non-root,
`/data` volume for the credential store, `/health` healthcheck,
`--workers 1`.

HTTPS+token installs instead of SSH: the token enters **only** via
`RUN --mount=type=secret` (never a build ARG — ARGs persist in layer
history), URL form `https://x-access-token:${TOKEN}@...`, with
`pip install --no-cache-dir`. CI must assert the final image's layers and
`direct_url.json` contain no token.

## Escape hatches

`build_app()` returns a plain FastAPI app:

- **Mount team routes/middleware after build** — supported. SDK auth is
  per-route dependencies, so your routes are unauthenticated until you add
  `Depends(agent_sdk.auth.require_identity)`; the self-check lists routes
  without it. Middleware added post-build wraps *outside* SDK middleware
  and must be added before startup.
- **`Agent(lifespan_extras=[...])`** — async context managers for
  team-owned resources (DB pools etc.) that should live inside the managed
  lifespan.
- **`Agent(model_client=...)`** — any `ModelClient` implementation
  replaces Bedrock behind the same seam.
- **`Agent(task_store=...)`** — alternative `TaskStore` (the in-memory
  default is the only one shipped today).

## Azure Container Apps + multi-replica

### Overview

The default SQLite persistence stores (credentials, commitments, subscription state) use
POSIX advisory locks for atomic writes. Azure Files — the most common shared-volume option
for Azure Container Apps — does not implement POSIX file locking across separate replicas.
Running two or more ACA replicas with SQLite on an Azure Files mount causes concurrent write
corruption and startup races (two replicas both attempting to bootstrap the admin key).

Azure Table Storage eliminates this problem. The SDK ships three backends —
`AzureTableCredentialStore`, `AzureTableCommitmentStore`, and `AzureTableSubscriptionStore`
— that replace the SQLite stores when Azure Storage environment variables are present. Table
Storage provides per-row ETag concurrency, cross-replica consistency, and managed-identity
auth, with no shared file mount required.

### Prerequisites

- Azure Storage account (General Purpose v2 or StorageV2; LRS is sufficient).
- `pip install agent-sdk[azure]` — the `azure-data-tables` client is an optional extra to
  avoid pulling it into single-replica deployments that do not need it.

### Configuration

**Mode 1 — Connection string (dev/test):**

Set `AZURE_STORAGE_CONNECTION_STRING` in `.env`. The SDK auto-detects this and wires all
three Azure backends at boot. Treat this value as a secret; do not commit it to source
control and do not log it.

```
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net
```

**Mode 2 — Managed identity (production ACA — preferred):**

Set only `AZURE_STORAGE_ACCOUNT_NAME` (no connection string). The SDK uses
`DefaultAzureCredential`, which resolves the ACA system-assigned or user-assigned managed
identity automatically. No secret to rotate, no key to store.

```
AZURE_STORAGE_ACCOUNT_NAME=mystorageaccount
```

Never set both simultaneously. If both are present the SDK will fail at boot with a
configuration error.

### Table naming

The SDK creates (or reuses) three tables per deployment:

| Table name | Contents |
|---|---|
| `{PREFIX}credentials` | Encrypted credential blobs (AES-256-GCM; MASTER_KEY required) |
| `{PREFIX}commitments` | Commitment state and ETag-guarded claim records |
| `{PREFIX}subscriptions` | Subscription event state |

`PREFIX` defaults to `agent`. Override with `AZURE_STORAGE_TABLE_PREFIX` in `.env`.

Tables are created automatically on first boot if they do not exist; no manual setup is
needed beyond the storage account.

### Migration from SQLite

If the agent has existing data in local SQLite files (under `DATA_DIR`), migrate it before
switching to Azure Storage:

```bash
# Preview what will be migrated (no writes):
python -m agent_sdk migrate-store --data-dir ./data --dry-run

# Migrate (fails if Azure tables already contain data):
python -m agent_sdk migrate-store --data-dir ./data

# Overwrite existing Azure data:
python -m agent_sdk migrate-store --data-dir ./data --force
```

The migration copies all credentials (still encrypted), commitments, and subscription
records into the configured Azure Storage tables. The source SQLite files are not deleted;
they remain as a local backup. Verify the migration with `--dry-run` before committing to
production.

### Replicas

Set `replicas: 2` (or higher) in your ACA YAML or Bicep definition. Each replica runs one
Uvicorn process:

```yaml
scale:
  minReplicas: 2
  maxReplicas: 5
```

Keep `WEB_CONCURRENCY=1` (one process per replica container). The in-process task store and
SSE subscriber queues are still per-replica. Tasks are short-lived (seconds to minutes);
users may land on any replica for follow-up turns within a task, which is acceptable because
A2A task state is not shared across replicas (see Known Limitations below). Increasing
`WEB_CONCURRENCY` beyond 1 within a replica reintroduces the per-process store isolation
problem and is unsupported.

### Security

- `MASTER_KEY` minimum 32-character requirement is unchanged. Credential values are
  encrypted with AES-256-GCM before being written to Table Storage; plaintext is never
  stored.
- `AZURE_STORAGE_CONNECTION_STRING` must never appear in logs, error messages, or agent
  output (SI-6). The SDK treats this field as `SecretStr` and excludes it from all
  serialization.
- Prefer managed identity (`AZURE_STORAGE_ACCOUNT_NAME` only) in production to eliminate
  key rotation entirely.
- Assign the `Storage Table Data Contributor` role to the ACA managed identity on the
  storage account scope — not subscription scope.

### Known limitations

- **In-memory task store is per-replica.** A2A task state (status, artifacts, SSE
  subscriber queues) lives in the replica that received the initial `message/send` request.
  If a follow-up request (e.g. `message/send` continuation or `tasks/get`) is routed to a
  different replica, the task will not be found. This is acceptable for short-lived tasks
  (the common case); sticky sessions or a shared `TaskStore` backend (not yet shipped)
  would be required for long-running tasks that survive replica restarts.

## Key rotation

`python -m agent_sdk rotate-master-key` — offline only (refuses while
another process holds the store); reads keys from `MASTER_KEY` /
`NEW_MASTER_KEY` env or no-echo prompts, never argv. Re-encrypts every
credential under a fresh salt in one transaction, then you update the
deployment env and restart.

Losing `MASTER_KEY` (with the hash store intact) is recovered only by an
out-of-band store wipe — which also destroys stored credentials and
connector registrations.
