# ADR 0001 — Credential architecture for the AlphaGeo agent

- **Status:** Accepted
- **Date:** 2026-06-11
- **Applies to:** `examples/alphageo` (the SDK seams it relies on are agent-sdk core)

## Context

Two unrelated credentials are routinely conflated when standing this agent up:

1. **Client → Agent** — the key a caller (e.g. claude.ai) presents to prove it
   is allowed to talk to *our* agent. *"Our own key."*
2. **Agent → AlphaGeo** — the vendor key the agent uses to actually *call* the
   AlphaGeo climate API. *"How we use the tools."*

They have different owners, different lifecycles, different blast radius, and
must live in different places. Putting the upstream vendor key in `.env`, or
reusing the client key upstream, breaks tenant isolation and rotation.

## Decision

A **two-key model**, with a third (model provider) kept deliberately separate.

### 1. Client → Agent: SDK API key (auth layer)

- Minted through the auth layer: `POST /admin/api/keys`. The **first** admin key
  is minted with a one-shot `X-Bootstrap-Token`; thereafter an existing admin
  key mints more.
- Persisted as a **SHA-256 hash** of the high-entropy token
  (`ak_{key_id}_{token_urlsafe(32)}`) in the reserved `__api_keys__` namespace —
  plaintext is returned exactly once and never stored. (No salt: the token is
  already 32 random url-safe bytes, so a per-key salt buys nothing.)
- The caller sends it as a bearer credential on every request to the agent.
- Encrypted at rest under `MASTER_KEY` (same store, reserved namespace —
  unreachable from any source adapter).

### 2. Agent → AlphaGeo: vendor key (hybrid, per-call → stored fallback)

Resolved **per call** by `AlphaGeoSource.credential("api_key")`, which goes
through `resolver_for_source(store, "alphageo")` (see
`agent_sdk/credentials/store.py`):

1. **Forwarded** — `X-Agent-Credentials` request header (base64 JSON,
   request-scoped). Lets a caller bring its own AlphaGeo key per call. *Primary.*
2. **Stored fallback** — the encrypted credential store at namespace
   `alphageo`, field `api_key`. *Used when no key is forwarded.*

Store properties (`EncryptedSqliteStore`): AES-256-GCM per value, key derived
from `MASTER_KEY` via PBKDF2-HMAC-SHA256 (600k iterations), `{namespace}/{field}`
bound as AAD. The upstream key is sent **only** to `app.alphageo.ai` (raw
`Authorization` header, no `Bearer` prefix) — never to the Nominatim geocoder
fallback. The response cache is tenant-isolated by a hash of the resolved key,
so one caller's forwarded key never serves another's cached data (the rate gate
is a single adapter-wide politeness throttle, not per-tenant).

**The upstream key is never a setting and never goes in `.env`.**

### 3. Model provider (Azure OpenAI / OpenAI): config, not a stored credential

`AZURE_OPENAI_*` (and the vanilla `OPENAI_*`) live in `.env` as `SecretStr`
settings, read **only** inside `make_model_client` and never logged. They are
*not* placed in the credential store: the store's namespaces are for source
adapters, and the model client is not a `SourceAdapter`. This is configuration
of how the agent thinks, not a credential it forwards to a tool.

## Consequences

- **Provisioning a deployment** seeds `alphageo/api_key` into the encrypted
  store (or forwards it per call). Helper: `scripts/set_upstream_credential.py`.
- **Rotation** is independent: rotate `MASTER_KEY` with
  `python -m agent_sdk rotate-master-key` (re-encrypts the whole store); rotate the
  upstream key with a single `store.set("alphageo", "api_key", …)` overwrite;
  rotate a client key by minting a new one and revoking the old.
- **Isolation holds by construction**: reserved namespaces (`__api_keys__`,
  `__oauth_*__`, `__bedrock__`) are refused by `resolver_for_source`, so the
  `alphageo` adapter can never read auth material, and nothing reading
  `alphageo/api_key` can reach the client keys.
- **Local live test** (DEV_MODE): set `MASTER_KEY` + `DATA_DIR` in `.env`, seed
  `alphageo/api_key` into the store at that `DATA_DIR`, then drive a live turn
  via the SDK CLI — no browser required:

  ```bash
  # Seed the upstream key (once per DATA_DIR):
  python scripts/set_upstream_credential.py

  # Drive a live agentic turn over AG-UI (streaming):
  python -m agent_sdk test-chat \
      --app src.main:app \
      --catalog urn:alphageo:climate:v1 \
      "What is the climate risk for NYC in 2050 under SSP585?"

  # Or via A2A (poll to completion):
  python -m agent_sdk test-chat --app src.main:app --a2a \
      --catalog urn:alphageo:climate:v1 \
      "What is the climate risk for NYC in 2050 under SSP585?"

  # Interactive REPL:
  python -m agent_sdk test-chat --app src.main:app \
      --catalog urn:alphageo:climate:v1
  ```

  `--catalog urn:alphageo:climate:v1` is required for the `ClimateRiskReport`
  A2UI surface; omit it and the agent returns the `TextPart` fallback instead
  (the A2UI translator gates domain-catalog types on the client capability claim).
  No vendor secret ever touches `.env`, argv, or logs.  See `docs/testing.md` in
  the SDK root for the full `test-chat` interface and `ChatDriver` integration-test usage.
