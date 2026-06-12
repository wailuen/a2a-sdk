# Security model

## Identities and surfaces

Every resolved identity is **kind-tagged**: `api_key` or `oauth`.

| Surface | Accepts |
|---|---|
| A2A, AG-UI | API key |
| `/mcp` | API key or OAuth token |
| `/admin/*`, key management | API key (admin) — `oauth` kind rejected |
| `/oauth/token` | unauthenticated by design (public client + PKCE) |
| `/oauth/revoke` | oauth callers for their **own** tokens only |

Task and interrupt access is identity-bound; a foreign id behaves exactly
like a missing one (404, never 403 — existence is not leaked). Admin keys
bypass for operations.

## API keys and bootstrap

Keys are stored hashed; the console shows prefixes only. Whenever the key
store holds **zero keys** at startup, a single-use bootstrap token
(15-minute TTL) is printed to stdout; the first `POST /admin/api/keys`
consumes it atomically. There is no open-until-first-key window.

## OAuth 2.1 (the `/mcp` AS)

- S256 PKCE only; dynamic client registration (RFC 7591).
- Refresh tokens are single-use and rotate; reuse revokes the whole token
  family.
- **Audience**: accepted set is exactly `{PUBLIC_URL origin,
  PUBLIC_URL/mcp}`; anything else is a hard 401 (documented deviation from
  strict RFC 8707 single-URI matching — Claude.ai sends the bare origin in
  some flows). The real privilege boundary is the kind-based surface table
  above.

## Credential store

AES-256-GCM under `MASTER_KEY` (≥32 chars, generated — the template and
`/new-agent` generate it; humans never invent it). KDF:
PBKDF2-HMAC-SHA256, ≥600k iterations, per-store salt. Namespaced
`{source}/{field}`; adapters can only resolve their own namespace.
Rotation: `python -m agent_sdk rotate-master-key` (offline only).

## Secrets hygiene (absolute)

No credential values, tokens, or user input values in error messages or
logs — ever. `AgentError` messages are generic by convention; the JSON log
formatter additionally redacts known secret patterns; upstream response
bodies never reach error text.

## Rate limiting and proxies

Per-identity and unauthenticated limiters. Client IP derivation:
with `AGENT_SDK_TRUSTED_PROXIES` set, the rightmost untrusted hop of
`X-Forwarded-For`; with none set, the socket peer. `X-Forwarded-For` is
never trusted blindly.

## DEV_MODE

Relaxes exactly three things: MASTER_KEY strength, the `PUBLIC_URL`
requirement, and secure-transport checks on OAuth endpoints. Nothing else.
`DEV_MODE=true` with a non-localhost `PUBLIC_URL` is a boot failure.

## Team-mounted routes

SDK auth is per-route dependencies, not global middleware. Routes you
mount after `build_app()` are **unauthenticated** until you add
`Depends(agent_sdk.auth.require_identity)`. The console self-check lists
mounted routes carrying no SDK auth dependency.
