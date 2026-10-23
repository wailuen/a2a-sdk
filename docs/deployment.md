# Deployment

## The two invariants

1. **Exactly one process per deployment.** The task store, SSE subscriber
   queues and rate limiter are process-local. The template Dockerfile
   hard-codes `--workers 1`; the SDK refuses `WEB_CONCURRENCY > 1` at boot
   (best-effort — `uvicorn --workers N` bypasses the env var; the
   Dockerfile is the real control). Multi-replica support arrives only
   with a shared `TaskStore` backend. With OAuth or IdP sign-in on, run
   **exactly one replica** (see Known limitations).

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

### Custom TaskStore durability

`InMemoryTaskStore.get()` returns the live record by reference, so an
in-place mutation of `task.status` or `messages` *is* the write. A durable
subclass whose `get()` deserializes a fresh copy per call does not get that
for free — it must instead override two hooks that are non-abstract and
default to a no-op on the base `TaskStore`:

- **`persist_messages(record)`** — flushes `record.messages`.
- **`persist_status(record)`** — flushes `record.task.status`.

**Override both together, never just one.** A store that overrides only
`persist_messages` never learns a terminal transition (`COMPLETED`,
`CANCELED`, ...), so the transcript it just flushed is never selected back
as a continuation candidate. Flush order is fixed: `persist_messages` runs
first, and `persist_status` fires only if that flush succeeded — so a
terminal status is never published durably ahead of the transcript it
depends on.

By default `persist_status` fires only on terminal/interrupt transitions,
not on every `WORKING` update — a streamed reply can emit many WORKING
transitions per turn, and flushing all of them would hit durable storage far
more than durability requires. Set the class attribute
**`persist_every_status = True`** to restore a flush on every status
transition (e.g. to drive a live status dashboard).

**The interrupt-state `persist_messages` flush is a mid-turn snapshot, not a
turn-boundary one.** `persist_messages` also fires on `AUTH_REQUIRED`/
`INPUT_REQUIRED` (not only terminal states) — but an interrupt is always
raised from inside the per-tool-call loop, after that turn's assistant
`toolUse` message is folded into `record.messages` and before its matching
`toolResult` is. So the transcript this flush captures is **guaranteed** to
end on a dangling `toolUse` with no matching `toolResult` — not directly
replayable against a Converse-API-shaped backend. If your durable
`TaskStore` subclass reconstructs a task from this snapshot after a process
restart, repair that dangling tail yourself (append a synthetic `toolResult`
per outstanding `toolUseId`) before handing the transcript to a model —
mirror `agent_sdk.agent.runner.repair_dangling_tool_use`, which the SDK
itself calls on every other mid-turn exit path (cancel, a `long_running`
tool's deferred handoff, a mid-turn exception) but not on this one, since
the interrupted call is still logically in flight, not abandoned.

See the `TaskStore` docstrings in `agent_sdk/tasks/store.py` for the full
rationale.

### Current date in the system prompt (GH-154)

- `AGENT_SDK_INJECT_CURRENT_DATE` (default `true`): append `Today is YYYY-MM-DD (<tz>).` to each task's system prompt.
- `AGENT_SDK_FINAL_SUMMARY` (default `true`): when a task hits the turn limit or token budget, make one last model call with tools off so the user gets an answer from the work so far. The task still ends as failed. That last call re-sends the whole conversation and its answer is capped at `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` (default 1024) tokens. It is made on both a turn-limit stop and a token-budget stop, so total spend can end above the budget by that one call. A fixed notice is sent only if the call fails or returns nothing usable. Set `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS=0` for notice-only. On the OpenAI/Azure backend, gpt-5 and other reasoning models count hidden "thinking" tokens against the same limit. If the summary comes back empty because thinking used the limit up, a warning is logged; raise `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` (it is also capped by `AGENT_SDK_MAX_OUTPUT_TOKENS`) or lower `AGENT_SDK_OPENAI_REASONING_EFFORT`. Set `false` to skip the call.
- `AGENT_SDK_AGUI_MAX_MESSAGE_CHARS` (default `32000`, minimum `1000`): longest replayed AG-UI history message sent to the model. A longer one keeps its start and end, with `[... N chars omitted ...]` in the middle (the marker counts within the limit). A value below 1000 fails boot.
- `AGENT_SDK_TIMEZONE` (default `UTC`): IANA zone used for that date. An invalid name fails boot (not checked when the date line is off). `UTC` needs no zone data; other names use the host's zone files or the `tzdata` package the SDK installs.
- `AGENT_SDK_OPENAI_REASONING_EFFORT` (default unset): `reasoning_effort` sent on every OpenAI/Azure call. Set it only for a reasoning deployment (gpt-5, o-series); other models reject it.
- `AGENT_SDK_OPENAI_MAX_COMPLETION_TOKENS` (default unset): hard ceiling on `max_completion_tokens` for every OpenAI/Azure call, including the summary call.

Clients may override the zone per request (AG-UI `forwardedProps.timezone`, A2A `message.metadata.timezone`).

### `AGENT_SDK_MAX_TURNS` vs. context continuation's message cap

`InMemoryTaskStore.MAX_CONTEXT_MESSAGES` (default 50) bounds how much of the
most recent terminal task's transcript `context_messages()` carries into a
fresh `message/send` on the same `contextId` (A2A §3 continuation). This cap
is independent of, but not unrelated to, **`AGENT_SDK_MAX_TURNS`**
(default 20, `LoopPolicies.max_turns`): a task that runs every turn to
completion without ever producing a final reply folds `2 * max_turns + 2`
messages, with its only plain user-authored turn boundary at the very first
(seed) message.

Raise `AGENT_SDK_MAX_TURNS` past roughly 24 and that per-task message count
exceeds the default `MAX_CONTEXT_MESSAGES`, so the cap's trailing window can
land with no turn boundary in it at all. The store falls back to the nearest
earlier boundary rather than dropping the whole prior transcript, and logs a
`WARNING` (`agent_sdk.tasks.memory`) each time it does. Seeing that warning
routinely means your `MAX_CONTEXT_MESSAGES` (or a durable subclass's
override of it) is undersized for your `max_turns` — raise it, or lower
`max_turns`, to keep continuation replay at its nominal size instead of
relying on the fallback every time.

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

**Anything that serves `/mcp` or OAuth connectors requires exactly one replica.**
Set `minReplicas: 1` and `maxReplicas: 1`. The OAuth server is always mounted.
Its flows, consent tickets, auth codes and access tokens, and all MCP sessions,
live in the memory of one process. A sign-in or session that starts on one
replica fails if the next call lands on another. The SDK logs one WARNING at
boot whenever a shared (Azure Table) store is configured.

```yaml
scale:
  minReplicas: 1
  maxReplicas: 1
```

Only pure A2A or AG-UI traffic with API keys (no `/mcp`, no OAuth connectors)
can use more than one replica, and even then task state is per-replica (see
Known limitations). Keep `WEB_CONCURRENCY=1`;
raising it reintroduces per-process isolation and is unsupported.

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

- **Access logs keep no sign-in secrets only inside uvicorn.** The SDK strips the
  query string from `/oauth/` paths in uvicorn's access log, so the IdP callback's
  `code` and `state` are not logged there. Proxy and ingress logs are not covered;
  scrub them or use `--no-access-log`.
- **OAuth and MCP state is per-process.** IdP flows, consent tickets, auth codes,
  access tokens and MCP sessions are held in process memory, not in the shared store.
  With more than one replica, connector sign-in and MCP calls break when requests hit
  different replicas. Run one replica when you serve `/mcp` or OAuth connectors.
- **Revoking is slow across replicas for some items.** Revoked API keys and refresh
  tokens take effect at once on every replica. Only in-memory access tokens (at most
  1 hour) and MCP sessions stay valid on the other replicas until they expire or restart.

## Behind a TLS gateway (GH-218)

Uvicorn only trusts forwarded headers (`X-Forwarded-For`, `X-Forwarded-Proto`)
from `127.0.0.1` by default. Behind a gateway on another address, the SDK sees
the gateway as the client. To fix that, set uvicorn's `FORWARDED_ALLOW_IPS`
environment variable to the gateway's address range, for example
`FORWARDED_ALLOW_IPS=10.0.0.0/16`. Use the same values as
`AGENT_SDK_TRUSTED_PROXIES`, so uvicorn and the rate limiter agree on who the
gateway is (see [Rate limiting and proxies](security.md#rate-limiting-and-proxies)).

Never set `FORWARDED_ALLOW_IPS='*'` (or `--forwarded-allow-ips='*'`). It makes
uvicorn believe forwarded headers from any caller, so a client can forge its
own address. That defeats the `AGENT_SDK_TRUSTED_PROXIES` trust model and lets
a client dodge the per-IP rate limit.

Note: `/mcp/` (trailing slash) is already served without a redirect, so no
gateway setting is needed for it.

## Key rotation

`python -m agent_sdk rotate-master-key` — offline only (refuses while
another process holds the store); reads keys from `MASTER_KEY` /
`NEW_MASTER_KEY` env or no-echo prompts, never argv. Re-encrypts every
credential under a fresh salt in one transaction, then you update the
deployment env and restart.

Losing `MASTER_KEY` (with the hash store intact) is recovered only by an
out-of-band store wipe — which also destroys stored credentials and
connector registrations.
