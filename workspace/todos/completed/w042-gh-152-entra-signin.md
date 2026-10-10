# w042 — GitHub issue #152: opt-in Entra ID / OIDC sign-in at /oauth/authorize

Sourced from wailuen/a2a-sdk#152 (/gh-review 2026-10-09). Target: next release after w041
(0.8.1 per maintainer; if w041 ships as 0.8.1 first, this is 0.8.2). Additive and off by default —
no stable-core break (`Identity.user` is a new trailing field with a default).

**Design record:** `workspace/adr/a003-oauth-idp-sign-in.md` (ADR-003). Every todo below
implements that ADR; where the issue text and the ADR differ, the ADR wins.

**Maintainer decisions (2026-10-09, override the issue):** (1) membership lives in Entra only —
no SDK access list, admin Access page, admin access API or `access` CLI; optional required
role/group claim; (2) keep DESIGN.md §5.5's two-value audience equivalence — no per-surface token
binding; (3) API keys keep working, plus an opt-out switch.

**PLANNER decisions — RATIFIED by the maintainer 2026-10-09 (/gh-review), with two changes.**
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/152#issuecomment-6081432302

D3 the API-key switch rejects USER (non-admin) keys only — admin keys stay valid everywhere;
D6 the default session cap is 720 h (30 days). Unchanged and ratified: D2 drop
`AGENT_SDK_OAUTH_IDP_SURFACES` and federate every authorize flow; D6 absolute family cap + refuse pre-IdP refresh
families; D7 a missing client secret warns at boot instead of failing; D8 endpoints pinned to the
issuer host (Google unsupported in v1); D9 show a consent page after sign-in (the issue proposed
skipping it — kept because DCR is open and silent SSO would hand a victim's code to an
attacker-registered redirect).

**Grouping:** group:A1 (GH-152-A, -B, -C) touch disjoint files and launch together. group:A2
(GH-152-D, -E) launches after all of A1; D and E share no files and do not depend on each other.
Pairwise check done: no A1 todo is in another A1 todo's Depends closure; D and E each depend only
on A1 todos.

**Concurrency note:** w041 edits CHANGELOG.md `[Unreleased]` and template advisor files. This wave
must start after w041 is archived; append to `[Unreleased]`, never rewrite w041's entries.

---

- [x] `GH-152-A` Settings, boot validation, reserved secret namespace, `[oidc]` extra ‖ group:A1
  - Creates: `tests/test_gh152_idp_settings_boot.py`
  - Modifies: `agent_sdk/config.py`, `agent_sdk/credentials/store.py`, `agent_sdk/app.py` (boot-validation call only — runtime wiring is GH-152-D), `agent_sdk/routes/admin.py`, `pyproject.toml`, `uv.lock`
  - Reads: `template/workspace/adr/a001-credential-model.md` (`__model__` pattern), `agent_sdk/routes/admin.py:400-450` (`_MODEL_FIELDS` / `_BEDROCK_FIELDS` credential cards), `agent_sdk/app.py:365-371` (lazy-import + clear install message pattern)
  - Severity: medium (feature gap — blocks enterprise rollout)
  - Root cause: No setting, secret slot or boot check exists for an upstream IdP. ADR-003 D7/D10/D11 and the settings table define them.
  - AC: `config.py` adds `oauth_idp` (`AGENT_SDK_OAUTH_IDP`, `Literal["none","oidc"]`, default `none`), `oauth_idp_issuer`, `oauth_idp_client_id`, `oauth_idp_required_role`, `oauth_idp_required_group`, `oauth_idp_session_hours` (default 720, 1-2160), `oauth_idp_disable_api_keys` (default false). An unknown `AGENT_SDK_OAUTH_IDP` value fails settings validation. Test RED before code, GREEN after.
  - AC: Entra issuer parsing lives here (one function, used by boot and by GH-152-D wiring): an issuer on a Microsoft login host must be `https://<host>/<tenant GUID>/v2.0`; `common`, `organizations`, `consumers`, any non-GUID tenant, and `https://sts.windows.net/...` (v1) are refused with a message naming the setting. The function returns the tenant GUID (or None for a non-Entra issuer). Any issuer must be `https` with no query/fragment.
  - AC: `build_app()` fails at boot with a clear message, and no secret value in it, when `oauth_idp=oidc` and: issuer or client id missing; issuer refused by the parser; `import jwt` fails ("install agent-sdk[oidc]"); `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` (exact message from ADR-003 D10). It also fails when `oauth_idp_disable_api_keys=true` with `oauth_idp=none`. Named tests: `test_boot_refuses_multi_tenant_issuer_aliases` (parametrised over common/organizations/consumers/non-GUID/sts.windows.net), `test_boot_refuses_one_time_consent_with_idp`, `test_boot_refuses_missing_issuer_or_client_id`, `test_boot_refuses_missing_oidc_extra` (monkeypatch the import), `test_boot_refuses_disable_api_keys_without_idp`.
  - AC: A missing `__oauth_idp__/client_secret` does NOT fail boot: one WARNING is logged that names the admin Credentials page and contains no value (`test_boot_warns_when_idp_secret_missing`, using a handler on the `agent_sdk` logger per LRN-106).
  - AC: When `AGENT_SDK_OAUTH_IDP_SURFACES` is present in the environment, boot logs one WARNING that it is unsupported and ignored (ADR-003 D2) (`test_boot_warns_on_unsupported_surfaces_setting`).
  - AC: `credentials/store.py` adds `NS_OAUTH_IDP = "__oauth_idp__"` to `RESERVED_NAMESPACES`; `resolver_for_source("__oauth_idp__")` raises (`test_oauth_idp_namespace_reserved`).
  - AC: `/admin/api/credentials` lists an `__oauth_idp__` card with one field `client_secret` (set/unset only, never the value) and `PUT /admin/api/credentials/__oauth_idp__/client_secret` stores it; both are `require_admin` only — an oauth-kind token and a non-admin key get 403 (`test_admin_can_set_idp_client_secret`, `test_idp_secret_card_never_returns_value`).
  - AC: `pyproject.toml` adds `oidc = ["PyJWT[crypto]>=2.8"]`; `uv lock` is re-run and `uv.lock` adds no new package (PyJWT is already locked via msal).
  - AC: With `oauth_idp=none`, `build_app()` makes no new log lines, reads no `__oauth_idp__` field, and does not import `jwt` (`test_idp_off_boot_is_silent_and_does_not_import_jwt`).
  - SI: SI-4, SI-6 — the client secret exists only in the encrypted store; it is never a `Settings` field, env var, CLI arg or log value. Pinned by `test_idp_secret_card_never_returns_value` and `test_boot_warns_when_idp_secret_missing` (asserts a planted secret sentinel is absent from all log records).
  - SI: SI-2 — boot error messages name settings, never values.
  - Reuses: C-001 (store encryption is unchanged — the secret rides the existing AES-GCM path; no second crypto path)
  - Depends: (none)
  - GH: https://github.com/wailuen/a2a-sdk/issues/152

- [x] `GH-152-B` OIDC relying-party module: discovery/JWKS cache, host pinning, ID-token validation, flow-state store ‖ group:A1
  - Creates: `agent_sdk/auth/oidc.py` (shared — new component, register as C-023 `OidcRelyingParty` + `IdpFlowStore`), `tests/test_gh152_oidc_rp.py`, `tests/test_gh152_idp_flow_state.py`
  - Reads: `agent_sdk/auth/oauth_tokens.py` (`verify_pkce_s256`, `_hash`, bounded-LRU pattern), `agent_sdk/common/redact.py` (C-007)
  - Severity: medium
  - Root cause: The SDK has no OIDC client. ADR-003 D8/D11 specify it; it must be pure and testable with `httpx.MockTransport` so the route todo can stay thin.
  - AC: `OidcConfig` dataclass (issuer, client_id, tenant_id|None, required_role|None, required_group|None, redirect_uri) and `OidcRelyingParty(config, secret_provider: Callable[[], str | None], transport=None)`. `jwt` is imported lazily inside the module's functions, never at package import.
  - AC: Discovery: fetched lazily from `{issuer}/.well-known/openid-configuration`; the document's `issuer` must equal the configured issuer exactly; `authorization_endpoint`, `token_endpoint`, `jwks_uri` must be `https` on the issuer host, else `IdpUnavailable` (fail closed). Own `httpx.AsyncClient` with `follow_redirects=False`, 10 s timeout, 512 KiB response cap. Named tests: `test_discovery_rejects_issuer_mismatch`, `test_discovery_rejects_endpoint_off_issuer_host`, `test_discovery_rejects_redirect_response`, `test_oversize_response_is_unavailable`.
  - AC: Cache: discovery and JWKS TTL 1 h; an unknown `kid` triggers one forced JWKS refetch, at most once per 60 s; a failed refresh keeps the last good copy up to 24 h with a WARNING. Named tests: `test_jwks_refetch_on_unknown_kid_once`, `test_jwks_forced_refetch_rate_limited`, `test_stale_cache_served_on_refresh_failure`.
  - AC: `build_authorize_url(state, nonce, code_challenge)` emits `response_type=code`, `response_mode=query`, `scope=openid profile email` (no `offline_access`), `code_challenge_method=S256`, the configured `redirect_uri`.
  - AC: `exchange_code(code, code_verifier)` posts `client_secret_post` to the token endpoint; a missing secret → `IdpUnavailable`; network error/timeout/5xx/malformed JSON → `IdpUnavailable`; 4xx → `IdpDenied`. Only `id_token` is kept; access/refresh tokens in the response are discarded and never stored.
  - AC: `validate_id_token(token, nonce)` uses PyJWT with `algorithms=["RS256"]`, exact `iss`, `aud == client_id` (list `aud` requires `azp == client_id`), 60 s leeway, required `exp, iat, iss, aud, sub, nonce` (+ `nbf, tid, oid` when `tenant_id` set), `nonce` via `hmac.compare_digest`, `tid == tenant_id`. Returns `(user, label)`: Entra `f"{tid}:{oid}"`, else `sub`; label from `preferred_username` or `email`, through C-007 `sanitize_text(max_len=128)`. Then required role (`roles`) and group (`groups`; `_claim_names` overage → deny) checks. Every failure → `IdpDenied(reason_code)` with a fixed reason code. Test RED before code, GREEN after. Named tests: `test_id_token_bad_signature_rejected`, `test_id_token_alg_none_and_hs256_rejected`, `test_id_token_expired_rejected`, `test_id_token_nbf_future_rejected`, `test_id_token_wrong_aud_rejected`, `test_id_token_list_aud_requires_azp`, `test_id_token_wrong_iss_rejected`, `test_id_token_wrong_tid_rejected`, `test_id_token_wrong_nonce_rejected`, `test_id_token_missing_oid_rejected_for_entra`, `test_required_role_enforced`, `test_required_group_enforced`, `test_group_overage_denied`, `test_user_key_is_tid_oid_not_email`.
  - AC: `IdpFlowStore`: memory-only, bounded LRU (e.g. 1 000), stores the validated authorize params + our PKCE verifier + nonce + sha256 of the browser-binding value under a random `state`; `pop(state, binding)` is single-use, TTL 600 s, and burns the entry on any mismatch. A second store kind holds consent tickets (TTL 300 s, single-use, bound to flow + user). Named tests: `test_state_single_use`, `test_state_expires_after_ttl`, `test_state_binding_mismatch_burns_entry`, `test_state_store_bounded`, `test_consent_ticket_single_use_and_expiring`.
  - SI: SI-2 — `IdpDenied`/`IdpUnavailable` messages are fixed constants; no exception text from httpx/PyJWT/the IdP body reaches a message or log (log the exception TYPE only, LRN-221). Pinned by `test_oidc_errors_carry_no_upstream_text` (IdP body and token contain sentinels; assert absent from exception str and every `agent_sdk` log record).
  - SI: SI-7 (by analogy — this is SDK auth infrastructure, not a `SourceAdapter`) — outbound hosts pinned to the issuer host; pinned by `test_discovery_rejects_endpoint_off_issuer_host`.
  - Reuses: C-007 (label sanitising — do not re-inline a control-char map)
  - Depends: (none)
  - GH: https://github.com/wailuen/a2a-sdk/issues/152
  - Reuses: C-007  # Correctly cited for the label. Also route the fixed IdpDenied/IdpUnavailable reason text and the WARNING on a failed JWKS refresh through C-007 sanitize_text/safe_error_text if any part of it is built from a value. The plan says they are constants; keep them constants and do not interpolate the kid, the issuer host or the HTTP status into them.
  - SI: SI-1  # agent_sdk/auth/oidc.py builds its own httpx.AsyncClient. In this repo, SI-1 allows HTTP clients only in the SourceAdapter base (agent_sdk/sources.py) and the agent/ model clients, plus the existing escape hatch agent_sdk/common/http.py (safe_get). ADR-003 D8 justifies the exception, but the todo's SI: field cites only SI-2 and SI-7-by-analogy, not SI-1. Add 'SI: SI-1 — sanctioned exception per ADR-003 D8' and pin every property of the client with named tests: follow_redirects=False (already test_discovery_rejects_redirect_response), the 10 s timeout, the 512 KiB cap enforced while streaming (not after the full body is read), and no client constructed at import time. Also make the client reuse agent_sdk/common/http.py::_is_non_public_ip on the resolved issuer host, so a misconfigured or rebinding issuer cannot reach loopback, link-local or metadata addresses. That predicate already serves as the single deny-list for SourceAdapter and validate_credential_url.

- [x] `GH-152-C` `Identity.user`, user-carrying tokens, absolute session cap, API-key opt-out switch ‖ group:A1
  - Creates: `tests/test_gh152_identity_user.py`, `tests/test_gh152_session_cap.py`, `tests/test_gh152_api_key_optout.py`
  - Modifies: `agent_sdk/auth/identity.py`, `agent_sdk/auth/oauth_tokens.py`, `agent_sdk/auth/middleware.py`, `agent_sdk/common/admission.py`
  - Reads: `agent_sdk/tasks/store.py` (`TaskRecord.identity: tuple[str, str]`), `agent_sdk/tasks/memory.py` (`identity.binding` call sites), `agent_sdk/routes/oauth.py:770-815` (revoke)
  - Severity: medium
  - Root cause: `Identity.subject` is the DCR client id, so every person behind one client shares task binding, rate limits and stream caps; refresh expiry rolls forward on each rotation, so a family never ends while used. ADR-003 D3/D5/D6.
  - AC: `Identity` gains `user: str | None = None` (last field) and a `principal_key` property; `binding` returns `(kind, subject)` when `user is None` (unchanged) and `(kind, f"{subject}|{user}")` otherwise. `middleware.py`'s identity rate limiter and `admission.py::identity_key` both use `principal_key`. With `user is None` every key is byte-identical to today (`test_identity_keys_unchanged_without_user`). Two users through one client get distinct `binding` and `principal_key` and cannot read each other's tasks (`test_two_users_same_client_isolated_tasks`, `test_two_users_same_client_separate_rate_limits`). Test RED before code, GREEN after.
  - AC: `mint_code`, `consume_code`, `mint_token_pair`, `rotate_refresh`, `verify` carry an optional `user`; `verify` returns `Identity(kind="oauth", subject=client_id, user=user, label=label)`. When `user is None`, the persisted refresh record's key set is exactly today's (`test_refresh_record_shape_unchanged_without_user`).
  - AC: `OAuthTokenStore(..., session_ttl_seconds: int | None = None, require_user: bool = False)`. With `session_ttl_seconds` set, the first mint stamps `family_expires_at`, rotation copies it, and access/refresh expiries are clamped to it; past it, `rotate_refresh` returns None and the access token stops verifying. With `require_user=True`, a refresh record without `user` is refused and its family revoked. Named tests: `test_family_expires_absolute_despite_rotation`, `test_access_token_clamped_to_family_expiry`, `test_legacy_userless_refresh_refused_when_user_required`, `test_no_family_cap_when_session_ttl_unset`.
  - AC: `revoke_by_value`: an oauth caller can revoke only tokens whose `client_id` AND `user` match its own (`test_oauth_user_cannot_revoke_other_users_token`); api-key callers are unchanged.
  - AC: `AuthRuntime` gains `idp_disable_api_keys: bool = False`. A shared internal resolver backs both `require_identity` and `require_api_key_identity`; only `require_identity` rejects NON-ADMIN `kind="api_key"` identities when the flag is on (maintainer ruling 2026-10-09: admin keys stay accepted on every route, so the console chat tab, /acceptance and /agent-verify keep working), with 401 + the PRM `WWW-Authenticate` challenge and a generic detail, counted against the unauth limiter. `require_admin`/`require_api_key_identity` never apply the switch. Named tests: `test_user_api_key_rejected_on_every_require_identity_route` (walks `app.routes`, finds every route whose dependants include `require_identity`, asserts 401 for a non-admin key — must cover the 13 routes listed in ADR-003 D3), `test_admin_key_still_accepted_on_protocol_routes_with_switch_on`, `test_admin_routes_still_accept_admin_key_with_switch_on`, `test_oauth_revoke_still_accepts_api_key_with_switch_on`, `test_api_keys_accepted_when_switch_off`.
  - SI: SI-5 — the switch must not open any route; pinned by `test_api_key_rejected_on_every_require_identity_route` and `test_admin_routes_still_accept_admin_key_with_switch_on`.
  - SI: SI-2 — no token or user id in the new 401 detail; `test_api_key_switch_401_detail_is_generic`.
  - Reuses: C-005 (TaskStore — `binding` keeps its `tuple[str, str]` type so `TaskRecord` and C-005's contract are untouched; do not widen the tuple)
  - Depends: (none)
  - GH: https://github.com/wailuen/a2a-sdk/issues/152
  - SI: SI-5  # The SI-5 pin names a test that the AC does not create. The SI: line cites `test_api_key_rejected_on_every_require_identity_route`, but the AC names it `test_user_api_key_rejected_on_every_require_identity_route`. Under fail-closed review, a pinning test that does not exist means SI-5 is unproven. Make the two names match. The walking test must also fail (not pass trivially) when it finds fewer than the 13 routes in ADR-003 D3, so a refactor that drops require_identity from a route cannot shrink the covered set silently.

- [x] `GH-152-D` Federated `/oauth/authorize`, `/oauth/idp/callback`, consent page, `/oauth/token` user carry, app wiring ‖ group:A2
  - Creates: `tests/test_gh152_idp_authorize_flow.py`, `tests/test_gh152_idp_off_regression.py`, `tests/test_gh152_idp_no_secret_leak.py`
  - Modifies: `agent_sdk/routes/oauth.py`, `agent_sdk/app.py` (runtime wiring)
  - Reads: `agent_sdk/auth/oidc.py`, `agent_sdk/auth/oauth_tokens.py`, `agent_sdk/auth/middleware.py`, `agent_sdk/config.py`, `tests/test_oauth_flow.py`, `tests/test_mcp_oauth.py`, `tests/test_oauth_one_time_consent.py`, `tests/test_provision_org_oauth_client.py`
  - Severity: medium
  - Root cause: Approval at `/oauth/authorize` is hard-wired to an admin API key. ADR-003 D4/D9/D12.
  - AC: `app.py`: when `oauth_idp=oidc`, build `OidcConfig` (tenant from GH-152-A's parser, `redirect_uri={PUBLIC_URL}/oauth/idp/callback`), `OidcRelyingParty` with a secret provider that reads `__oauth_idp__/client_secret` per call, `IdpFlowStore`, `OAuthTokenStore(session_ttl_seconds=hours*3600, require_user=True)`, `AuthRuntime(idp_disable_api_keys=...)`. With `oauth_idp=none` none of these are constructed and the existing constructor calls are unchanged.
  - AC: `GET /oauth/authorize` with IdP on: `_validate_authorize` runs unchanged (unknown client / unregistered `redirect_uri` → 400 page, never an IdP redirect); then a missing secret or `IdpUnavailable` → `_error_redirect(..., "temporarily_unavailable", state)`; otherwise store the flow, set the `__Host-agent_sdk_idp` cookie (`HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=600`), 302 to the IdP. Applies to both audiences. Named tests: `test_unknown_client_never_redirects_to_idp`, `test_unregistered_redirect_uri_never_redirects_to_idp`, `test_authorize_redirects_to_idp_with_pkce_s256_and_nonce` (both audiences), `test_authorize_missing_secret_is_temporarily_unavailable`, `test_idp_outage_is_temporarily_unavailable_not_500`. Test RED before code, GREEN after.
  - AC: `POST /oauth/authorize` with IdP on → generic 400 error page; no key is verified and no code is minted (`test_admin_key_consent_disabled_under_idp`).
  - AC: `GET /oauth/idp/callback`: unknown / expired / replayed `state` or cookie mismatch → local 400 page, no redirect, no code (`test_callback_state_replay_rejected`, `test_callback_unknown_state_rejected`, `test_callback_cookie_mismatch_rejected`); IdP `error` param → `access_denied` redirect; `IdpDenied` (bad token, wrong tid/nonce, missing role) → `access_denied` redirect with no IdP detail (`test_callback_invalid_id_token_access_denied`, `test_callback_missing_required_role_access_denied`); success → consent page showing client name, `redirect_uri` host, user label, Allow/Deny, served with `_CONSENT_SECURITY_HEADERS` + `_redirect_security_headers` (LRN-126/127).
  - AC: `POST /oauth/idp/consent`: valid ticket + Allow → `mint_code(..., user=, label=)` and 303 to `redirect_uri` with `code` and the client's original `state`; Deny → `access_denied`; reused/expired ticket → 400 page. `/oauth/token` passes `user`/`label` from the code into the pair; the resulting access token verifies to `Identity(kind="oauth", subject=client_id, user="<tid>:<oid>")`. Named tests: `test_full_idp_flow_mints_user_bound_token`, `test_consent_deny_returns_access_denied`, `test_consent_ticket_replay_rejected`, `test_refresh_keeps_user_and_family_cap`.
  - AC: Both new routes carry `Depends(unauth_rate_limit)` and are unauthenticated by design (ADR-003 D12) (`test_idp_routes_rate_limited`).
  - AC: **Off = byte-identical.** With `oauth_idp=none`: GET `/oauth/authorize` body and headers equal today's consent page for the same input; POST approve, token, refresh, revoke, PRM (both), AS metadata responses equal today's; `/oauth/idp/callback` and `/oauth/idp/consent` return 404; minted identities have `user is None`. The four existing OAuth test files pass with no edits (`git diff --stat` on them is empty). Named tests: `test_idp_off_authorize_page_byte_identical`, `test_idp_off_metadata_byte_identical`, `test_idp_off_idp_routes_404`.
  - AC: `/agent-verify` OAuth-chain probes (PRM, AS metadata, 401 + `WWW-Authenticate`, CORS preflight) unchanged with IdP on and off (`test_idp_on_discovery_documents_unchanged`).
  - AC: Full suite `pytest -q` green before archive (LRN-106), not only the new files.
  - SI: SI-2 — client secret, IdP code, ID token, IdP access/refresh token, our PKCE verifier, nonce and cookie value never appear in logs, error pages, `error_description`, or the final client redirect URL. Pinned by `test_no_idp_secrets_in_logs_or_responses` (plants sentinels in every one of those values, drives success and every failure path, scans every `agent_sdk` log record via an attached handler and every response body/header).
  - SI: SI-5 — new unauthenticated routes are state/cookie/ticket-gated and rate-limited; pinned by `test_callback_state_replay_rejected` and `test_idp_routes_rate_limited`.
  - SI: SI-4 — the secret is read through the store per exchange and never cached on the app or a module global (`test_idp_secret_rotation_needs_no_restart`).
  - Reuses: C-023 (new, from GH-152-B — `OidcRelyingParty`, `IdpFlowStore`), C-007 (any echoed label)
  - Depends: GH-152-A, GH-152-B, GH-152-C
  - GH: https://github.com/wailuen/a2a-sdk/issues/152
  - SI: SI-5  # POST /oauth/idp/consent is an unauthenticated state-changing form POST. The ticket is bound to flow + user, but the AC does not bind it to the __Host-agent_sdk_idp browser cookie. A ticket leaked through a Referer header or logs could be replayed from another browser within 300 s. Require pop(ticket, cookie_binding) on consent, as the callback does, and add `test_consent_ticket_cookie_mismatch_rejected`.

- [x] `GH-152-E` Docs, setup skill, CHANGELOG, AUTH_SURFACE mirrors ‖ group:A2
  - Modifies: `DESIGN.md` (§5.5, §6), `docs/security.md`, `CHANGELOG.md`, `harness/skills/setup/SKILL.md`, `template/.claude/skills/setup/SKILL.md`, `.claude/workflows/sdk-wave.js`, `.claude/workflows/wave-cycle.js`, `harness/workflows/wave-cycle.js`, `template/.claude/workflows/wave-cycle.js`, `tests/test_workflows.py`
  - Reads: `workspace/adr/a003-oauth-idp-sign-in.md`, `workspace/components/README.md` (C-014)
  - Severity: low
  - Root cause: The feature changes the auth design and operator setup; DESIGN.md, the security doc, the setup skill and the redteam surface lists must say so.
  - AC: DESIGN.md §5.5 gets an "Upstream IdP sign-in (opt-in, GH-152 / ADR-003)" addendum: federation flow, consent page, the two new routes, `POST /oauth/authorize` disabled under IdP, audience equivalence explicitly unchanged. §6 gets: `Identity.user` + `binding`/`principal_key`, `__oauth_idp__` reserved namespace, absolute session cap and the removal-lag statement ("a user removed in Entra keeps access for up to `AGENT_SDK_OAUTH_IDP_SESSION_HOURS`, default 720 h (30 days); re-check at refresh is out of scope"), the API-key switch route table from ADR-003 D3.
  - AC: `docs/security.md`: surface table gains the IdP routes (SI-5 exception, D12) and the API-key switch column; the "OAuth 2.1" section covers ID-token checks, host pinning, no IdP token kept, session cap. Also corrects the stale "A2A, AG-UI | API key" row (OAuth tokens are accepted there too, per §5.5).
  - AC: `CHANGELOG.md` `[Unreleased]` → `### Added` entry for opt-in OIDC/Entra sign-in, the `[oidc]` extra, `Identity.user`, all new settings; and a note that with `AGENT_SDK_OAUTH_IDP=none` nothing changes (LRN-145 — under `[Unreleased]`, below/alongside w041's entries, never inside a tagged section).
  - AC: Setup skill (harness + template copies identical in the new section): Entra app registration steps — single-tenant web app; redirect URI `{PUBLIC_URL}/oauth/idp/callback`; client secret → `/admin → Credentials → __oauth_idp__`; Enterprise application → Properties → **Assignment required = Yes** and assign users/groups (or create an app role and set `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE`); set `AGENT_SDK_OAUTH_IDP=oidc`, `..._ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0`, `..._CLIENT_ID`; `pip install 'agent-sdk[oidc]'`; restart; `AGENT_SDK_OAUTH_ONE_TIME_CONSENT` must be unset; the API-key switch disables console chat and `/acceptance`/`/agent-verify` protocol probes. Note: there is no `.claude/skills/setup` in this repo; the mirrors are `harness/` and `template/.claude/`.
  - AC: C-014: `agent_sdk/auth/oidc` added to `AUTH_SURFACE` in `.claude/workflows/sdk-wave.js`; `src/auth/oidc` added to `AUTH_SURFACE` in all three `wave-cycle.js` mirrors; `tests/test_workflows.py` parity tests pass with the new member.
  - AC: Template edits land in the template's own repo (`template/` is gitignored by a2a-sdk) by hunk-level staging (`git -C template add -p`) of only this wave's hunks, then commit + push to wailuen/a2a-agent-template, once the user approves that push. Until then they are an open deliverable in the closing note below. Do not revert or reformat the template's existing uncommitted edits.
  - AC: Follow-ups listed in ADR-003 are filed or listed in the wave's closing note: OBO from the user token, re-check at refresh, group overage via Graph, non-issuer-host endpoints, remembered consent.
  - SI: none (docs only) — but docs must not include any real tenant id, client id or secret; placeholders only.
  - Reuses: C-014 (extend the one AUTH_SURFACE list — do not add per-protocol literals)
  - Depends: GH-152-A, GH-152-B, GH-152-C
  - GH: https://github.com/wailuen/a2a-sdk/issues/152
  - Modifies (mirror): `template/.claude/workflows/wave-cycle.js` — lands via commit+push to wailuen/a2a-agent-template per LRN-071; runtime copy is what /acceptance / the harness skill actually executes — implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step  # The mirror is listed in Modifies:, but the AC says 'Template edits are left uncommitted for the template's own repo'. That makes propagation implicit, which is the exact failure LRN-071/LRN-085 forbid. Annotate the path '(lands via commit+push to wailuen/a2a-agent-template per LRN-071)' and add an explicit final step: `git -C template/ commit` + `git -C template/ push` for wave-cycle.js (and template/.claude/skills/setup/SKILL.md). Stage only this wave's files, so the pre-existing uncommitted template edits stay untouched. If a commit is truly blocked, the closing note must name the unpropagated files and the diff check `diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js` as an open deliverable. Note: .claude/workflows/sdk-wave.js correctly has no template mirror, because it is SDK-only.

## Closing note — open deliverable (template repo, not yet landed)

Status: OPEN. The w042 template mirror edits are written in the template working tree but are
NOT committed or pushed to wailuen/a2a-agent-template. A workflow cannot authorize a commit or
push to another repository; this needs the user's explicit go-ahead.

Unpropagated files (template repo, `git -C template status`):
- `template/.claude/workflows/wave-cycle.js` — w042 hunk: `'src/auth/oidc'` appended to `AUTH_SURFACE`.
- `template/.claude/skills/setup/SKILL.md` — w042 hunk: the "If Entra ID sign-in is wanted" block under step 4.

Why plain `git add` is wrong: the template tree is dirty with other waves' edits (11 files;
wave-cycle.js differs from template HEAD by ~1,483 lines; setup/SKILL.md also carries the
one-time-consent, OpenAI-retry and uv.lock hunks from earlier waves). Stage hunk by hunk:

    git -C template add -p .claude/workflows/wave-cycle.js .claude/skills/setup/SKILL.md
    # accept only the AUTH_SURFACE 'src/auth/oidc' hunk and the Entra block hunk
    git -C template commit -m "feat(setup,wave-cycle): GH-152 Entra sign-in setup steps + src/auth/oidc in AUTH_SURFACE"
    git -C template push origin main

Note: in wave-cycle.js the AUTH_SURFACE line sits inside a larger diff hunk from other waves;
use `s` (split) or `e` (edit) in `add -p` so only the one-line change is staged.

Verification check (content parity, passes today): `diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js`
returns no output. After the push, also confirm `git -C template show HEAD:.claude/workflows/wave-cycle.js | grep "src/auth/oidc"` matches.

ADR-003 follow-ups (not in this wave): OBO from the user token, re-check at refresh, group
overage via Graph, non-issuer-host endpoints, remembered consent.

---

**Archived 2026-10-10 (by /gh-review).** sdk-wave run wf_90e16678-c82: phase redteam ended at round 6
with 0 critical/high; pre-archive gate 2817 passed, 0 failed; protocol audits (A2A, AG-UI, MCP, seam)
found no critical/high. Group A2's unit loop exhausted its 5 rounds with one HIGH open (RT-001: the
template mirrors were not committed/pushed to wailuen/a2a-agent-template). /gh-review resolved that
by syncing the template right after archiving. Medium/low findings are recorded, not fixed:
`deferred/w042-group-A1-medium-low.md`, `deferred/w042-group-A2-medium-low.md` (incl. RT-003
concurrent same-browser flows, RT-004 flow-table eviction, RT-002 `.env`-only SURFACES warning,
RT-005/006 doc gaps, RT-007 off-mode golden coverage), `deferred/w042-phase-medium-low.md`.
