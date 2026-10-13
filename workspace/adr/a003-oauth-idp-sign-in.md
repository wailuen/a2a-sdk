---
id: ADR-003
title: Opt-in Entra ID / OIDC sign-in at /oauth/authorize (GH-152)
status: accepted
date: 2026-10-09
deciders: wailuen (maintainer decisions 1-3, via /gh-review 2026-10-09); planner (decisions marked PLANNER below — all ratified by the maintainer 2026-10-09, D3 admin-key scope and D6 default changed as noted); checkable reference: https://github.com/wailuen/a2a-sdk/issues/152#issuecomment-6081432302
wave: w042
supersedes: none
---

## Context

GH-152 asks for "only named people from our Entra tenant can use this agent". Today the OAuth
chain (`agent_sdk/routes/oauth.py`) approves a connector with an admin API key, and the token it
mints identifies the DCR client (`Identity(subject=client_id)`, `auth/oauth_tokens.py`), not a
person. Every user behind one client collapses onto one identity for task binding, rate limits
and stream caps (`common/admission.py::identity_key`).

The issue proposed (a) federating `/oauth/authorize` to an upstream OIDC IdP, (b) an
SDK-maintained access list with an admin page/API/CLI, (c) a per-surface setting that binds
tokens to the MCP or A2A audience. The maintainer accepted (a) and rejected (b) and (c).

This ADR is the SDK's own decision record (the SDK repo had no `workspace/adr/` before this; the
numbering continues after `template/workspace/adr/a001`/`a002`, which are SDK-level decisions
shipped to agents, so `ADR-003` stays globally unique).

## Decisions

### D1 — Membership lives in Entra only (MAINTAINER)

No SDK access-list store, no `/admin → Access` page, no `/admin/api/access`, no
`python -m agent_sdk access` command. Admins restrict sign-in in Entra: enterprise application
**Assignment required = Yes** plus user/group assignment, app roles, or groups.

The SDK verifies the ID token (JWKS signature, `iss`, `aud`, `exp`, `nbf`, `iat`, `nonce`, and
for Entra `tid`) and MAY additionally require a claim:

- `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE` — value must appear in the `roles` claim (Entra app role).
- `AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP` — group object id must appear in the `groups` claim.
  Group overage (Entra omits `groups` and sends `_claim_names` when a user has >200 groups) is
  **denied**, not resolved through Graph. App roles are the recommended mechanism.

If both are set, both are required. A missing required claim fails closed with a generic
`access_denied`.

### D2 — Keep the two-value audience equivalence; drop the surfaces setting (MAINTAINER + PLANNER)

DESIGN.md §5.5 stays: a token minted for the root origin or for `{PUBLIC_URL}/mcp` is accepted
on every surface (Claude.ai sometimes sends the bare origin as `resource`).

**PLANNER — `AGENT_SDK_OAUTH_IDP_SURFACES` is dropped.** With audiences equivalent, a per-surface
choice of approval path creates no boundary: a token approved through the admin-key path for one
audience is still accepted on the other surface. The setting would therefore only suggest an
isolation it cannot deliver. Instead, when `AGENT_SDK_OAUTH_IDP=oidc`, **every** `/oauth/authorize`
flow (both audiences) federates to the IdP, and the admin-key consent path is disabled
(`POST /oauth/authorize` returns the generic 400 error page and never verifies a key or mints a
code). Admin automation does not need OAuth; it uses API keys directly (D3). If the env var
`AGENT_SDK_OAUTH_IDP_SURFACES` is present, boot logs one WARNING that it is not supported and is
ignored (the behaviour it is ignored in favour of is stricter, so a warning is enough).

### D3 — API keys keep working, with an opt-out switch (MAINTAINER; route scope PLANNER)

Default with sign-in on: API-key Bearer is accepted everywhere it is today.

`AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true` (only valid with `oauth_idp=oidc`; boot refuses it
otherwise) rejects non-admin `kind="api_key"` identities — **admin keys stay accepted** — on every route whose
auth dependency is `require_identity`:

| Covered (API key → 401 + PRM `WWW-Authenticate`) | Not covered (API keys still accepted) |
|---|---|
| `POST /v1/message:send`, `POST /v1/message:stream` | `/admin/*` pages and `/admin/api/*` (incl. the admin tool runner) — `require_admin` |
| `GET /v1/tasks`, `GET /v1/tasks/{id}`, `POST /v1/tasks/{id}:cancel`, `POST /v1/tasks/{id}:subscribe` | key management, bootstrap |
| `GET /v1/card` (extended card) | `POST /oauth/revoke` (operator kill-switch for any token) |
| `POST /ag-ui/run` | discovery (`/.well-known/*`), `/health`, `/oauth/register`, `/oauth/token` |
| `POST/GET/DELETE /mcp`, `GET /mcp/sse`, `POST /mcp/messages` | |
| any agent escape-hatch route that depends on `require_identity` | |

Mechanism: `require_identity` gains the check; `require_api_key_identity`/`require_admin` resolve
through a shared internal resolver that skips it. Operators are never locked out of the console.

**MAINTAINER (2026-10-09) — user keys only; admin keys stay accepted.** The planner proposed
rejecting admin keys on protocol routes too ("named people only" means every protocol call is
attributable to a person). The maintainer chose user keys only, so the console's chat tab,
`/acceptance` and `/agent-verify` keep working with the switch on. Trade-off accepted: a holder
of the admin key can still call protocol routes without signing in; docs must say so.

### D4 — Federate at `/oauth/authorize`; the SDK stays the authorization server

Clients keep DCR, PKCE S256, PRM, AS metadata, token, refresh and revoke unchanged. With
`oauth_idp=oidc`:

1. `GET /oauth/authorize` runs `_validate_authorize` exactly as today (unknown client /
   unregistered `redirect_uri` → 400 page, never a redirect). Then it stores the validated
   request server-side under a fresh random `state` (single-use, TTL 10 min, bounded LRU,
   memory-only per the single-process invariant), sets a browser-binding cookie, and 302s to
   the IdP `authorization_endpoint` with `response_type=code`, `response_mode=query`,
   `scope=openid profile email`, our own PKCE S256 challenge, a `nonce`, and
   `redirect_uri={PUBLIC_URL}/oauth/idp/callback`. `offline_access` is NOT requested.
2. `GET /oauth/idp/callback` pops the flow by `state` (unknown, expired, replayed, or cookie
   mismatch → local 400 error page, never a redirect, no code). An IdP `error` param →
   generic `access_denied` redirect to the client. Otherwise it exchanges the code at the
   token endpoint as a confidential client (`client_secret_post`, PKCE verifier), validates
   the ID token, applies D1's optional claim checks, and renders the consent page (D9).
3. `POST /oauth/idp/consent` (single-use consent ticket) → `mint_code(..., user=..., label=...)`
   and 303 to the client's `redirect_uri` with `code` + the client's original `state`.

Browser-binding cookie: `__Host-agent_sdk_idp`, random value, `HttpOnly; Secure; SameSite=Lax;
Path=/; Max-Age=600`; the flow stores only its sha256. Defence in depth against a flow started in
one browser and finished in another.

**D4 note (GH-152 RT-004) — per-source flow quota.** `GET /oauth/authorize` is unauthenticated and DCR is open, so a few IPs could fill the 1,000-entry LRU and evict real users' flows. Chosen design: `IdpFlowStore.put(..., source=)` where `source` is the same client IP the unauth rate limiter uses (`_client_key`, honours trusted-proxy rules). A source at its quota (50) evicts only its own oldest flow. When the table is full, a source that already holds flows evicts its own oldest; a source holding none is refused (`IdpFlowStore._evict_for` raises `IdpUnavailable`, which `_federate` turns into an `error=temporarily_unavailable` redirect). Evicting the largest holder was rejected: a fresh source could then evict a real user holding a few flows. The refusal is generic and echoes only the client's own `state` (SI-2). Consent tickets keep the plain LRU bound with no per-source quota: one is created only after a real IdP sign-in and ID-token check, so an unauthenticated caller cannot mint them. Stateless sealed-`state` was rejected as a larger change. Residual: an attacker with about 20 IPs (or IPv6 /64s) at the default quota can keep the table full and refuse every new source with `temporarily_unavailable` until those flows expire (600 s); the per-IP rate limit is the only bound there.

### D5 — Identity shape: explicit `user` field; `subject` stays the client_id

`Identity` gains `user: str | None = None` (appended last, so positional construction is
unchanged). `subject` keeps meaning "registration" (client_id / key id), so `revoke_by_value`,
audit and every existing caller keep their meaning.

- Entra: `user = f"{tid}:{oid}"` (stable, immutable). Generic OIDC: `user = sub`.
  `email`/`preferred_username` go to `label` only (sanitised via C-007) — they are mutable and,
  in Entra, unverified, so they are never used for an allow decision.
- `binding` → `(kind, subject)` when `user is None` (unchanged), else
  `(kind, f"{subject}|{user}")`. The tuple type is unchanged, so `TaskRecord.identity` and C-005
  are untouched. Including the client_id is deliberate least privilege: a second client app the
  same person signs into cannot read the first app's tasks.
- New `Identity.principal_key` property (`f"{kind}:{subject}"`, or `...:{user}` when set) is the
  one key for the per-identity rate limiter (`auth/middleware.py`) and stream admission
  (`common/admission.py::identity_key`). Two users through one DCR client now get separate
  budgets; with `oauth_idp=none` every key is byte-identical to today.
- `revoke_by_value`: an oauth caller may revoke only tokens whose `client_id` AND `user` match.

Why not overload `subject` with the user: `subject == client_id` is load-bearing in
`revoke_by_value`, the per-ORG cap documentation, and audit logs; overloading would silently
change all three. Existing tasks stay valid: with `oauth_idp=none` nothing changes, and turning
sign-in on requires a restart, which already empties the memory-only task store.

### D6 — No IdP refresh token; bounded SDK session when sign-in is on (PLANNER default)

The SDK does not request `offline_access` and keeps no IdP access/refresh token (ID token is
validated, then discarded). Removal is enforced by Entra at the next IdP sign-in.

Today a refresh token's 90-day expiry **rolls forward on every rotation**, so a family that is
used regularly never expires. With sign-in on that would let a user removed in Entra keep access
indefinitely. So when `oauth_idp=oidc`:

- Each token family gets an absolute `family_expires_at = first mint + AGENT_SDK_OAUTH_IDP_SESSION_HOURS`
  (default **720** = 30 days — maintainer ruling 2026-10-09; allowed 1-2160), copied through every rotation. Access and refresh expiries
  are clamped to it. After it, refresh → `invalid_grant`, and the client must re-run authorize,
  which re-signs-in at the IdP (where assignment/role is re-checked).
- **Worst-case access after removal in Entra = SESSION_HOURS** (default 720 h = 30 days).
- Re-checking the user against Entra at refresh (IdP refresh token or Graph) is **out of scope**;
  follow-up issue.
- Refresh families minted before sign-in was turned on carry no `user`; under `oauth_idp=oidc`
  they are refused at rotation (`invalid_grant`) and the family revoked, forcing an IdP sign-in.
- With `oauth_idp=none` nothing changes: no `family_expires_at`, and persisted refresh records keep
  exactly today's key set.

### D7 — Client secret in the credential store

Reserved namespace `NS_OAUTH_IDP = "__oauth_idp__"`, field `client_secret`, set from
`/admin → Credentials` (same pattern as `__model__`, ADR a001). Never `.env`, settings, argv or
logs (SI-4/SI-6). Read per token exchange, scoped to the request (LRN-081), so rotation needs no
restart.

**PLANNER — a missing secret does not fail boot.** The secret can only be set through the admin
API of a running agent (there is no offline credentials CLI), so failing boot would be a
chicken-and-egg lock-out. Instead boot logs one WARNING, and `/oauth/authorize` fails closed with
a generic `temporarily_unavailable` redirect until the secret exists. It never falls back to the
admin-key page. Boot DOES fail for: missing issuer or client id, a multi-tenant / non-GUID Entra
issuer, a v1 (`sts.windows.net`) issuer, a missing `[oidc]` extra, the one-time-consent conflict
(D10), and `DISABLE_API_KEYS` without `oauth_idp=oidc`.

### D8 — IdP client: discovery, JWKS, host pinning, outage

New SDK-internal module `agent_sdk/auth/oidc.py` (new component; not a `SourceAdapter`, because
it is SDK auth infrastructure, not agent domain code, and its secret lives in a reserved namespace
no adapter can read).

- Discovery from `{issuer}/.well-known/openid-configuration`, fetched lazily (boot never depends
  on IdP reachability). The document's `issuer` must equal the configured issuer exactly;
  `authorization_endpoint`, `token_endpoint`, `jwks_uri` must be `https` on the issuer's host.
  **PLANNER:** v1 pins all endpoints to the issuer host. IdPs that serve JWKS from another host
  (Google) are unsupported in v1 and fail closed; Entra and Okta work. Extra-host allowlist is a
  follow-up.
- Own `httpx.AsyncClient`: `follow_redirects=False`, 10 s timeout, 512 KiB response cap.
- Cache: discovery and JWKS TTL 1 h. Unknown `kid` → one forced JWKS refetch, at most once per
  60 s (no amplification). Refetch failure keeps the last good copy for up to 24 h with a WARNING.
- Outage (network error, timeout, 5xx, oversize, malformed JSON) → generic
  `temporarily_unavailable` redirect to the validated client `redirect_uri`; never a 500, never
  upstream detail. IdP 4xx at the token endpoint → `access_denied`.
- ID token: PyJWT, `algorithms=["RS256"]` only (rejects `none`/HS*), `aud == client_id` (if `aud`
  is a list, `azp` must equal client_id), exact `iss`, 60 s leeway, required claims
  `exp, iat, iss, aud, sub, nonce` (+ `nbf, tid, oid` for Entra), `nonce` compared with
  `hmac.compare_digest`, `tid` equal to the configured tenant GUID.
- Entra hardening: issuer must be `https://<microsoft login host>/<tenant GUID>/v2.0`; the tenant
  segments `common`, `organizations`, `consumers` and any non-GUID value are refused at boot.

### D9 — Show a consent page after sign-in (PLANNER — departs from the issue's "skip")

DCR is open: anyone can register a client with their own `redirect_uri`. Without a consent step,
an attacker could send a victim the authorize URL of the attacker's client; Entra SSO would sign
the victim in silently and the code (for the victim's identity) would go to the attacker's
redirect, where the attacker holds the PKCE verifier. This is the MCP "confused deputy" case;
the MCP security guidance requires per-client user consent for a proxy authorization server.

So after the ID token validates, the SDK renders a consent page: client name, the `redirect_uri`
host (shown prominently), the agent, and the signed-in user's label, with Allow / Deny. The form
posts a single-use consent ticket (random, server-side, TTL 5 min, bound to the flow and user) to
`POST /oauth/idp/consent`. Page headers reuse `_CONSENT_SECURITY_HEADERS` and
`_redirect_security_headers` (form-action widened on the form-owning document, LRN-126; origin
rebuilt from validated parts, LRN-127). Consent is not remembered in v1 (no new store); with the
30-day session that is about one click per month per client.

**Consent record and client eviction (decided in w042 fix loop, RT-001/RT-002).** Allow writes
`user_consented_at` on the client record via `OAuthTokenStore.mark_user_consented()`. It must
never write `consented`: that bit means "an admin approved this client" (admin-key POST or
`provision-org-oauth-client`) and is the only bit the `oauth_one_time_consent` shortcut trusts.
Reusing it would let a later switch to `oauth_idp=none` + one-time consent auto-approve every
client any directory user ever allowed. Eviction at the `MAX_CLIENTS` cap is mode-independent:
`consented` clients are never evicted (admin-only, so they cannot be flooded, and every client
approved before this ADR carries it, so the upgrade creates no victims); `user_consented_at`
clients are protected only while they hold a live refresh family; all others go oldest-first.
No separate `pinned` flag.

### D10 — Conflict with `oauth_one_time_consent`

Boot refuses `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` together with `AGENT_SDK_OAUTH_IDP=oidc`:
"AGENT_SDK_OAUTH_ONE_TIME_CONSENT cannot be combined with AGENT_SDK_OAUTH_IDP=oidc — IdP sign-in
replaces admin-key consent. Unset one of them."

### D11 — JWT library: `PyJWT[crypto]` as optional extra `[oidc]`

`[project.optional-dependencies] oidc = ["PyJWT[crypto]>=2.8"]`, imported lazily inside
`auth/oidc.py`. Boot fails with "install agent-sdk[oidc]" when `oauth_idp=oidc` and the import
fails. Reasons: PyJWT is already in `uv.lock` (pulled by `msal` for `[obo]`), so the lock gains no
new package; `cryptography` is already a core dependency. Rejected: hand-rolled RS256 on
`cryptography` (security-sensitive parsing we should not own); `msal` (its ID-token handling
does not verify the JWKS signature, it trusts TLS); PyJWT's `PyJWKClient` (sync `urllib`, cannot
reuse the pinned httpx client) — the module fetches JWKS itself and builds keys with `jwt.PyJWKSet`.

### D12 — Unauthenticated callback/consent routes (SI-5 note)

`/oauth/idp/callback` and `/oauth/idp/consent` are intrinsically unauthenticated, like
`/oauth/token`: the browser arrives from the IdP with no Bearer. They are gated by the single-use
state + browser-binding cookie + consent ticket and carry `Depends(unauth_rate_limit)`. Documented
as an SI-5 exception in `docs/security.md`.

### D13 — Fail-closed sign-in gate for non-Entra issuers (GH-152 ruling)

Ruling: https://github.com/wailuen/a2a-sdk/issues/152#issuecomment-6094590732

`parse_idp_issuer` pins a tenant only for Entra issuers. For any other issuer `tenant_id` is None,
so with no `required_role` / `required_group` any valid ID token from that issuer would be accepted.
Boot now refuses `AGENT_SDK_OAUTH_IDP=oidc` unless one holds: the issuer is an Entra tenant pinned
by GUID ("pinned by GUID" excludes the Microsoft personal-account tenant `9188040d-6c67-4c5b-b112-36a304b66dad`, which `parse_idp_issuer` refuses); `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE` is set; `AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP` is set; or
the explicit opt-out `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true` is set. The opt-out logs one
WARNING at boot (every account at the issuer is admitted) and is refused when `oauth_idp != oidc`.
Messages name settings only, never values (SI-2).

### D14 — Role, group or opt-out required for every issuer (GH-161 ruling)

Ruling: https://github.com/wailuen/a2a-sdk/issues/161#issuecomment-6137224867

**Supersedes the Entra exemption in D13.** An Entra tenant with no role or group admits every member
and guest unless the tenant admin turned on "Assignment required", which the SDK cannot see. Boot now
refuses `AGENT_SDK_OAUTH_IDP=oidc` for every issuer unless `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE`,
`AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP` or `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true` is set.
The opt-out keeps its single boot WARNING. The personal-account tenant GUID refusal is unchanged.
Messages name settings only, never values (SI-2). `oauth_idp=none` is unchanged.

## Settings summary

| Setting | Default | Notes |
|---|---|---|
| `AGENT_SDK_OAUTH_IDP` | `none` | `none` \| `oidc`; any other value → boot error |
| `AGENT_SDK_OAUTH_IDP_ISSUER` | — | required when `oidc` |
| `AGENT_SDK_OAUTH_IDP_CLIENT_ID` | — | required when `oidc`; non-secret |
| `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE` | unset | optional `roles` claim value |
| `AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP` | unset | optional `groups` claim value; overage denied |
| `AGENT_SDK_OAUTH_IDP_SESSION_HOURS` | `720` | 1-2160; absolute token-family lifetime |
| `AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS` | `false` | D3 |
| `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS` | `false` | D13, D14; only with `oidc` |
| `__oauth_idp__/client_secret` | — | credential store only |

## Consequences

- `oauth_idp=none`: byte-identical behaviour (pinned by a regression test and by the existing
  OAuth test files passing unedited).
- Per-person attribution, task isolation, rate limits and stream caps when sign-in is on.
- Removal in Entra takes effect within `SESSION_HOURS` (default 720 h = 30 days), not instantly.
  Mitigation (GH-163): an admin can revoke a user at once from the console "Signed-in users" panel or `DELETE /admin/api/oauth/identities/{user}`. Refresh is refused on all workers; a live access token survives on other workers until it expires (per-process memory, GH-162).
- Claude.ai connectors re-authorize (IdP sign-in + one consent click) once per session.
- With the API-key switch on, console chat and protocol-level harness probes need it off.
- PRM and AS metadata documents are unchanged; `/agent-verify` OAuth probes are unaffected.

## Out of scope / follow-ups

- OBO / `contrib.obo` from the signed-in user's token (the SDK keeps no IdP token).
- Re-checking Entra membership at refresh (IdP refresh token or Graph).
- Graph fallback for group overage.
- Non-issuer-host endpoints (Google) via an extra-host allowlist.
- Remembered per-(user, client) consent.
- An SDK-side access list (rejected by D1; revisit only if Entra-only proves insufficient).
