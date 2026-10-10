wave: w042
scope: group A1
date: 2026-10-09

Non-blocking — these did not block w042's archive. Address opportunistically or fold into a future wave.

Deduped by file+description across every unit redteam round for group A1. Round IDs were reused across rounds, so each entry lists the source IDs it merges (r1 = earlier round, r2 = later round). Entries are numbered D-NN here to avoid the ID collisions.

## Findings

### D-01 (r1 RT-002 + r2 RT-002)
- severity: medium
- file: agent_sdk/config.py
- description: `parse_idp_issuer` (lines 38-70) lets boot succeed with issuer strings that can never match at runtime. It lower-cases the tenant GUID it returns, but `app.py` passes the raw `settings.oauth_idp_issuer` into `OidcConfig.issuer`. Failing forms: the `login.windows.net` alias; `https://login.microsoft.com/common/v2.0` (treated as non-Entra, returns None); an upper-case tenant GUID or host; an explicit `:443` port; userinfo. The discovery document's `issuer` (always `https://login.microsoftonline.com/<lowercase tid>/v2.0`) then fails the exact match in `oidc.py:_fetch_discovery` and in `jwt.decode(issuer=...)`. Result: permanent `temporarily_unavailable` on every sign-in with no log naming the setting. The AC also says `common` must be refused at boot with a message naming the setting.
- fix: Have `parse_idp_issuer` return a normalised issuer (lower-case host, lower-case GUID, no default port, no userinfo) and use that value in `OidcConfig`. For Entra, refuse non-canonical issuers at boot: upper-case host or GUID, explicit port, userinfo, or a known alias (`login.windows.net`, `login.microsoft.com`), with one message such as 'AGENT_SDK_OAUTH_IDP_ISSUER must be https://login.microsoftonline.com/<lowercase tenant GUID>/v2.0'. Add `login.microsoft.com` to `_ENTRA_LOGIN_HOSTS`, and parametrise `test_boot_refuses_multi_tenant_issuer_aliases` with these cases.
- codify: A boot-time validator that accepts a config value must hand the same normalised value to the runtime that compares it exactly; otherwise boot passes and runtime fails silently forever.
- sdkCandidate: true

### D-02 (r1 RT-003 + r2 RT-001)
- severity: medium
- file: agent_sdk/auth/oidc.py
- description: During an IdP outage the stale-cache path makes an outbound call on every request while holding the discovery/JWKS asyncio locks. `_refresh` (lines 168-177) returns the old `_Cached` object with its old `fetched_at`, so once the 1-hour TTL has passed every later `_discover`/`_key_for` call sees the TTL as expired and retries. Each retry runs DNS plus up to the 10 s timeout under `_discovery_lock` (and `_jwks_lock` for JWKS, up to about 20 s, since `_fetch_jwks` re-runs discovery inside `_jwks_lock`). Every authorize and callback request queues behind it, and each one writes the 'serving stale copy' WARNING. A probe with the IdP down and the cache past TTL counted 15 outbound attempts and 15 WARNING lines for 10 calls. The '24 h stale grace' in ADR-003 D8 therefore becomes one-at-a-time requests with 10 s+ latency plus a flood of warnings.
- fix: On a failed refresh, keep the stale value but record a retry time (for example `_Cached.retry_after` / `next_attempt_at = now + 60s`, matching `_FORCED_REFETCH_MIN_INTERVAL`). Inside that window serve the stale copy with no network call and no new WARNING; log once per failed attempt, not per request. Do the network fetch outside the lock, or use a single-flight future, so waiters do not queue behind a 10 s timeout. Add a test that counts transport requests across N calls during an outage and asserts at most 1 per backoff window.
- codify: A stale-on-error cache must also back off further refresh attempts; returning the old entry with its old timestamp turns every request into an outbound retry.
- sdkCandidate: true

### D-03 (r2 RT-003)
- severity: medium
- file: agent_sdk/auth/oidc.py
- description: Most fail-closed paths log nothing. Silent cases: discovery issuer mismatch (line 182), an endpoint off the issuer host (187), a non-public resolved IP (117/127), a non-200 discovery or JWKS response (158), malformed JWKS (`except Exception` at 207, which does not even log the exception type, unlike LRN-221's pattern), and every `IdpDenied.reason_code`. The callback in `routes/oauth.py` logs only `client_id` on a deny. An operator whose sign-in never works cannot tell a config mistake from an outage or a missing role.
- fix: Add one fixed-text WARNING per fail-closed branch carrying only a constant reason code (for example `idp discovery rejected: issuer_mismatch`, `endpoint_off_host`, `non_public_ip`, `status_not_200`, `jwks_unparseable`). In the callback, log `IdpDenied.reason_code`, which is already a fixed constant, so it is SI-2 safe. Extend `test_oidc_errors_carry_no_upstream_text` to assert each new record contains only the constant code.
- codify: Fail-closed auth paths still need a constant-text reason in the log; SI-2 bans upstream values, not diagnosability.
- sdkCandidate: true

### D-04 (r1 RT-008 + r2 RT-005)
- severity: medium
- file: agent_sdk/auth/oidc.py
- description: `_check_issuer_host` plus `_request` (lines 108-154) form a second URL-fetching helper next to `common/http.py::safe_get`, copying its resolve-then-check loop and importing the private `_is_non_public_ip`. LRN-016 (severity high) says never to add one and to extend `safe_get` instead; ADR-003 D8 allows the client, so severity is lowered to medium. The helper resolves DNS itself with `getaddrinfo`, then lets httpx resolve the host again, leaving a DNS-rebinding gap between check and connect. The DNS non-public check is also skipped entirely whenever the public `transport` constructor argument is given, so any caller passing a transport turns off the SSRF guard (safe_get keeps the resolver check separate from `_transport`), and no test covers the resolve-and-deny branch.
- fix: Either pull a public `assert_public_host(host, resolver=None)` helper out of `common/http.py` / extend `safe_get` into a shared `safe_request(method, url, *, data, max_bytes, _resolver, _transport)` used by both callers, or pin the connection to the vetted IP (a custom transport connecting to the resolved address with SNI/Host set to the hostname). Inject a resolver for tests instead of tying the check to `transport`, and make the test seams private (`_transport`/`_resolver`). Add a test that a host resolving to 127.0.0.1 or 169.254.169.254 gives `IdpUnavailable` even when a transport is injected.
- codify: An SSRF guard that resolves DNS and then lets the HTTP client resolve again is a check-then-use gap; pin the vetted IP or share one fetch helper.
- sdkCandidate: true

### D-05 (r2 RT-004)
- severity: medium
- file: agent_sdk/auth/middleware.py
- description: The public helper `resolve_identity` (line 88), exported from `agent_sdk.auth`, ignores `AuthRuntime.idp_disable_api_keys`. Only the `require_identity` dependency applies the switch. An agent escape-hatch route that gates data with `resolve_identity(request) is not None` keeps accepting non-admin user API keys while the operator believes ADR-003 D3 turned them off. That helper also skips both rate limiters.
- fix: Apply the same non-admin `api_key` rejection inside `resolve_identity` when `idp_disable_api_keys` is on (return None), or document loudly in its docstring and in DESIGN.md §6 that it must never gate data. Add a test that a non-admin key resolves to None with the switch on.
- codify: When a policy switch is added to an auth dependency, every public identity resolver exported beside it must apply the same switch or be documented as non-gating.
- sdkCandidate: true

### D-06 (r1 RT-004)
- severity: medium
- file: tests/test_gh152_idp_settings_boot.py
- description: The SI-4/SI-6 pin is not what the todo asked for. GH-152-A says `test_boot_warns_when_idp_secret_missing` 'asserts a planted secret sentinel is absent from all log records'. The test (lines 145-150) plants no secret and only counts the warning. No A1 test boots with a stored `__oauth_idp__/client_secret` sentinel and checks it is absent from every `agent_sdk` log record and from boot error text.
- fix: Add a case that stores a sentinel at `NS_OAUTH_IDP/client_secret` before `build_app()`, with sign-in on and a DEBUG-level `sdk_caplog('agent_sdk')`. Assert the sentinel appears in no record and in no ValueError message from the boot-refusal paths.
- sdkCandidate: true

### D-07 (r1 RT-005)
- severity: medium
- file: tests/test_gh152_idp_settings_boot.py
- description: The AC for the `__oauth_idp__` admin card requires that 'an oauth-kind token and a non-admin key get 403'. `test_idp_secret_requires_admin` (lines 201-213) only covers a non-admin API key. No test shows an OAuth access token is refused on `PUT /admin/api/credentials/__oauth_idp__/client_secret`, the endpoint that holds the IdP signing-relationship secret.
- fix: Mint a real OAuth access token (register_client -> mint_code -> consume_code -> mint_token_pair). Assert PUT, DELETE and GET on the IdP credential endpoints return 403 with it.
- sdkCandidate: true

### D-08 (r2 RT-006)
- severity: medium
- file: workspace/components/README.md
- description: The `agent_sdk/auth/oidc.py` docstring declares itself 'Component C-023 OidcRelyingParty / IdpFlowStore', but the registry has no C-023 row; its last entries are C-021 and C-022. Dimension 8 counts an unregistered reusable component as drift, and a later Dimension 8 check of 'Reuses: C-023' in GH-152-D will find nothing.
- fix: Add a C-023 row (OidcRelyingParty + IdpFlowStore, agent_sdk/auth/oidc.py, present) and a detail paragraph to workspace/components/README.md. Also change the todo's `Reuses: C-022` references in GH-152-B/D to C-023, as the plan redteam asked.
- sdkCandidate: true

### D-09 (r1 RT-006 + r2 RT-009)
- severity: low
- file: agent_sdk/app.py
- description: The ADR-003 D2 warning for `AGENT_SDK_OAUTH_IDP_SURFACES` in `_validate_idp_settings` checks `os.environ` only. `BaseAgentSettings` reads `.env` (env_file='.env', extra='ignore'), so a value set in `.env`, the usual deployment path, is silently dropped with no warning. The check also only runs when `oauth_idp=oidc`, but ADR-003 D2 says 'if the env var is present, boot logs one WARNING'.
- fix: Detect the key in both `os.environ` and the dotenv source (e.g. `dotenv_values(settings.model_config['env_file'])`), or declare it as an ignored `str | None` settings field and warn when it is set. Decide whether the warning also applies when sign-in is off, and test the `.env` path.
- sdkCandidate: true

### D-10 (r1 RT-009 + r2 RT-010)
- severity: low
- file: tests/test_gh152_api_key_optout.py
- description: `test_user_api_key_rejected_on_every_require_identity_route` only asserts the route count is at least 13 (ADR_D3_MIN_ROUTES). It does not check the specific ADR-003 D3 route set. A refactor that removes `require_identity` from one D3 route (e.g. `GET /v1/card`) and adds it to another still passes, and SI-5 coverage shrinks unnoticed. Separately, the todo's SI-5 line names `test_api_key_rejected_on_every_require_identity_route`, which does not exist; only the AC's `test_user_api_key_...` exists. The plan redteam flagged that mismatch and it is still unfixed.
- fix: List the 13 ADR-003 D3 (method, path) pairs as a frozenset constant and assert it is a subset of `_covered_routes(app)`, keeping the at-least-13 check. Fix the todo's SI-5 line to the real test name.
- sdkCandidate: true

### D-11 (r1 RT-007)
- severity: low
- file: agent_sdk/auth/middleware.py
- description: With `idp_disable_api_keys` on, `require_identity` first calls `_resolve_identity`, which sets `request.state.identity` to the user API key's identity and charges that key's `identity_limiter` bucket, and only then rejects with 401. Anything that later reads `request.state.identity` (agent escape-hatch routes, exception handlers, audit middleware) sees a refused caller as authenticated.
- fix: Move the switch check into `_resolve_identity` behind a `reject_user_api_keys` flag, applied before `request.state.identity` is set and before the identity limiter is charged. Or clear `request.state.identity` before raising.
- sdkCandidate: true

### D-12 (r1 RT-010)
- severity: low
- file: agent_sdk/auth/oidc.py
- description: `IdpFlowStore` is a global bounded LRU (1000 flows, 1000 tickets). `GET /oauth/authorize` is unauthenticated and limited only per IP, and dynamic client registration (DCR) is open. An attacker spread across a few dozen IPs can fill the table faster than real users finish signing in at the IdP, evicting their pending flows; those users land on the 'invalid or expired' page. Separately, `mint_token_pair` reports `expires_in=int(access_ttl)`, which drops to 0 when less than 1 s of the session cap is left.
- fix: Cap pending flows per client IP (or per client_id) on top of the global limit, and document the eviction behaviour. Refuse to mint a pair when `remaining` is below a small floor (e.g. 5 s), returning None or invalid_grant instead of issuing tokens with near-zero lifetime.
- sdkCandidate: true

### D-13 (r2 RT-007)
- severity: low
- file: agent_sdk/tasks/store.py
- description: Comments and docstrings still describe the old key shape: the binding is `(kind, subject)` and the per-identity caps are registration-scoped and per-org. `principal_key` and `binding` now include `user` when it is set. Stale places: `tasks/store.py:83` (TaskRecord.identity comment), the `auth/identity.py` module docstring, the `common/admission.py::identity_key` docstring, and the `config.py` RT-001 comment near line 211.
- fix: Update each to say the binding is `(kind, subject)` or `(kind, f"{subject}|{user}")`, and that with IdP sign-in on the caps are per signed-in user, not per org.
- sdkCandidate: true

### D-14 (r2 RT-008)
- severity: low
- file: agent_sdk/auth/oauth_tokens.py
- description: `require_user=True` is enforced only in `rotate_refresh`. `mint_token_pair` (line 277) and `consume_code` still accept `user=None`, and `verify` returns a userless identity, so a userless token family can still be minted under IdP mode. No current route does this (POST /oauth/authorize and one-time consent are both blocked under IdP), so ADR-003 D6's invariant rests entirely on route-level gating.
- fix: In `mint_token_pair`, raise or refuse when `self._require_user and not user`, and add a unit test. This keeps the invariant inside the token store as defence in depth.
- sdkCandidate: true

### D-15 (r2 RT-011)
- severity: low
- file: agent_sdk/auth/oauth_tokens.py
- description: The family-cap branch in `rotate_refresh` (lines 370-375, revoke the family when `family_expires_at` has passed) is effectively dead code. `mint_token_pair` clamps the refresh `expires_at` to `family_expires_at`, so the earlier `expires_at <= now` branch always fires first; it deletes only the presented token and the family-revoke path never runs. `test_family_expires_absolute_despite_rotation` passes through the clamp, so the cap-revoke code has no test.
- fix: Either remove the unreachable branch, or move the family-cap check before the plain expiry check so the whole family's tombstones are revoked at the cap. Add a test asserting the family's rows are gone after the cap.
- sdkCandidate: true

### D-16 (r2 RT-012)
- severity: low
- file: agent_sdk/app.py
- description: The runtime IdP wiring uses a bare `assert settings.oauth_idp_issuer and settings.oauth_idp_client_id` (around line 789) as a production guard. It disappears under `python -O`. It is safe today only because `_validate_idp_settings` ran earlier.
- fix: Replace it with an explicit `if not ...: raise ValueError(...)` naming the settings, or narrow the types through local variables checked by `_validate_idp_settings`.
- sdkCandidate: true
