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

## Key rotation

`python -m agent_sdk rotate-master-key` — offline only (refuses while
another process holds the store); reads keys from `MASTER_KEY` /
`NEW_MASTER_KEY` env or no-echo prompts, never argv. Re-encrypts every
credential under a fresh salt in one transaction, then you update the
deployment env and restart.

Losing `MASTER_KEY` (with the hash store intact) is recovered only by an
out-of-band store wipe — which also destroys stored credentials and
connector registrations.
