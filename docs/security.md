# Security model

## Identities and surfaces

Every resolved identity is **kind-tagged**: `api_key` or `oauth`.

| Surface | Accepts |
|---|---|
| A2A, AG-UI | API key or OAuth token |
| `/mcp` | API key or OAuth token |
| `/admin/*`, key management | API key (admin) — `oauth` kind rejected |
| `/oauth/token` | unauthenticated by design (public client + PKCE) |
| `/oauth/idp/callback`, `/oauth/idp/consent` | unauthenticated by design (single-use state, browser cookie, consent ticket; per-IP rate limited). Only active with `AGENT_SDK_OAUTH_IDP=oidc`. A documented SI-5 exception |
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

### Optional IdP sign-in (Entra ID / OIDC)

Off by default (`AGENT_SDK_OAUTH_IDP=none`). With `oidc`:

- `/oauth/authorize` sends the user to your IdP; the admin-key consent page is disabled. A consent page (client name, redirect host, signed-in user) follows sign-in, to block confused-deputy code theft through open client registration.
- The ID token is checked for signature (RS256 only), issuer, audience, expiry, nonce and, on Entra, tenant. Optional `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE` / `_REQUIRED_GROUP` add a claim check. Group overage is denied.
- Who may sign in is managed in Entra (enterprise application "Assignment required"), not in the SDK.
- Tokens carry `Identity.user` (`<tenant>:<object id>` on Entra). Tasks, rate limits and stream caps are per person.
- The client secret lives in the credential store under `__oauth_idp__` only.
- **Per-source flow limit:** each client IP (same derivation as the unauthenticated rate limit, so `AGENT_SDK_TRUSTED_PROXIES` applies; an IPv6 address counts as its /64) may hold at most 50 in-flight sign-ins in a 1,000-entry table. No source can push out another source's sign-ins. What a caller sees: (a) a source at its 50 limit replaces its own oldest sign-in, with no error; that oldest sign-in just stops working ("sign-in link is invalid or has expired"). (b) When the table is full, a source already holding sign-ins also replaces its own oldest; a source holding none is refused, and the client gets an `error=temporarily_unavailable` redirect (generic, nothing echoed but the client's own `state`). (c) Past the unauthenticated rate limit the caller gets the usual 429. Residual risk: about 20 IPs (or IPv6 /64s) holding 50 sign-ins each can keep the table full and block new sign-ins for the whole tenant until their sign-ins expire (10 minutes). The per-IP rate limit is the only bound on that.
- **Removal lag:** the SDK keeps no IdP token. A person removed in Entra keeps access until their token family expires, at most `AGENT_SDK_OAUTH_IDP_SESSION_HOURS` (default 720 hours, 30 days). Lower it for faster cut-off.
- `AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true` rejects non-admin API keys on A2A, AG-UI and `/mcp`. Admin keys and service keys still work on those routes. A service key (`POST /admin/api/keys` with `service: true`, mutually exclusive with `admin`) is for automated runs: it is refused on `/admin/*`, key management and credentials, like a normal user key. The bootstrap token only mints admin keys. Admin keys open everything, so protect them.
- **Who may sign in (fail-closed):** the SDK cannot see whether an Entra tenant requires assignment ("Assignment required"), so without a claim check every member and guest of the tenant could sign in. Boot therefore refuses `oidc` for every issuer, Entra included, unless `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE` / `_REQUIRED_GROUP` is set, OR you set the explicit opt-out `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true`. The opt-out admits every account the issuer signs in and logs one WARNING at boot. It is valid only with `AGENT_SDK_OAUTH_IDP=oidc` (boot refuses it otherwise). The Microsoft personal-account tenant `9188040d-6c67-4c5b-b112-36a304b66dad` is still refused. Ruling: GH-161 (ADR a003 D14, supersedes the D13 Entra exemption).
- Cannot combine with `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` (boot refuses).
- A user clicking Allow is recorded as `user_consented_at`, never as admin approval (`consented`). Switching sign-in back off with one-time consent on therefore never auto-approves a client that only a directory user allowed; the admin-key page is shown again.

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

The SDK strips the query string from every `/oauth/` path in uvicorn's access
log only (the IdP callback URL carries `code` and `state`). Reverse proxy and
ingress logs are not covered: scrub them there, or run uvicorn with
`--no-access-log`.

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
