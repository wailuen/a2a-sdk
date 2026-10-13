wave: w042
scope: phase
date: 2026-10-09

Non-blocking — these did not block w042's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every phase redteam round. Where several rounds raised the same
finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/config.py
- description: Still open from A1 D-01; raised in four phase rounds. parse_idp_issuer (lines 38-70) accepts issuers that can never match at runtime: an upper-case tenant GUID or host, an explicit `:443` port, userinfo (`https://user@login.microsoftonline.com/<guid>/v2.0`), and the `login.windows.net` alias. `login.microsoft.com/common/v2.0` returns None and is treated as non-Entra. app.py:792 passes the RAW settings.oauth_idp_issuer into OidcConfig.issuer, and oidc.py:_fetch_discovery (line 182) and jwt.decode(issuer=...) compare it exactly against Entra's lower-case canonical issuer. Userinfo also makes _host_of return None, so every request fails as IdpUnavailable. All of these pass boot, then every sign-in returns temporarily_unavailable forever, and no log line names the setting.
- fix: Have parse_idp_issuer return (normalised_issuer, tenant) — lower-case host and GUID, no port, no userinfo — and pass the normalised issuer to OidcConfig. For Entra, refuse non-canonical forms and alias hosts (login.windows.net, login.microsoft.com) at boot with one message naming AGENT_SDK_OAUTH_IDP_ISSUER ('must be https://login.microsoftonline.com/<lowercase tenant GUID>/v2.0'). Refuse userinfo for any issuer. Add login.microsoft.com to _ENTRA_LOGIN_HOSTS. Parametrise test_boot_refuses_multi_tenant_issuer_aliases with all these cases.
- codify: A boot validator that accepts a config value must hand the same normalised value to the runtime code that compares it exactly.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/config.py
- description: `oauth_idp_required_role` and `oauth_idp_required_group` (lines 196-201) take any string without checking it. `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE=` (empty, e.g. an unexpanded `${ROLE}` in compose) loads as '' (verified), and oidc.py:347 `if cfg.required_role:` then skips the role check entirely. The access gate silently fails open to every assigned tenant user. A whitespace-only value instead fails closed for everyone. Boot reports neither.
- fix: Add a field_validator that strips both values, maps '' to None only when the variable is absent, and raises a ValueError naming the setting when the variable is set but blank or whitespace. Or log a boot WARNING naming the setting. Add boot tests for the empty and whitespace cases.
- codify:
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/auth/oidc.py
- description: Still open from A1 D-02; raised in four phase rounds. The stale-on-error cache has no back-off. On a failed refresh, _refresh (lines 168-177) returns the old _Cached entry with its original fetched_at. Once the 1 h TTL has passed, every later _discover/_key_for call retries the network (DNS plus up to a 10 s timeout, about 20 s for JWKS because it nests discovery) while holding _discovery_lock or _jwks_lock. Every authorize and callback request queues behind it, and each one logs a 'serving stale copy' WARNING. During an IdP outage, ADR-003 D8's 24 h stale grace becomes requests served one at a time with 10 s+ latency, plus a log flood.
- fix: On refresh failure, keep the stale value and record a next-attempt time (for example now + 60 s). Inside that window, serve the stale copy with no network call and no new warning. Do the fetch outside the lock, or behind a single-flight future. Add a test that counts transport calls across N requests during an outage and asserts at most one per back-off window.
- codify: A stale-on-error cache must also back off its refresh attempts; returning the old entry with its old timestamp turns every request into an outbound retry.
- sdkCandidate: true

### RT-004
- severity: medium
- file: agent_sdk/auth/oidc.py
- description: Still open from A1 D-03; raised in two phase rounds. Most fail-closed IdP paths log nothing: discovery issuer mismatch, an endpoint off the issuer host, a non-public resolved IP, a non-200 discovery/JWKS response, and unparseable JWKS (a bare `except Exception` in _fetch_jwks that does not even log the exception type, contrary to LRN-221). In routes/oauth.py the callback logs only the client_id on IdpDenied and drops the constant reason_code. Operators cannot tell a misconfiguration (see RT-001) from an outage or a user without the right role.
- fix: Log one fixed-text WARNING per fail-closed branch with a constant reason code only (issuer_mismatch, endpoint_off_host, non_public_ip, status_not_200, jwks_unparseable). Log `exc.reason_code` in the callback's IdpDenied branch; it is a constant, so this is SI-2 safe. Extend test_oidc_errors_carry_no_upstream_text to assert each record carries only the constant.
- codify: Fail-closed auth paths still need a constant reason code in the log; SI-2 bans upstream values, not diagnosability.
- sdkCandidate: true

### RT-005
- severity: medium
- file: agent_sdk/auth/oidc.py
- description: OidcRelyingParty.exchange_code maps every 4xx from the IdP token endpoint to IdpDenied('token_rejected') (line 262), and the callback turns that into an `access_denied` redirect with only an INFO log of the client_id. The most common operational failure takes this path: an expired or wrong Entra client secret (Entra secrets expire after at most 24 months) returns 401 `invalid_client`. Every user then sees 'access denied', as if Entra had refused them, and nothing points the operator to the client secret. RT-004 covers missing reason logs in general; this finding is the wrong classification of the cause.
- fix: Parse the 4xx JSON body's `error` field against a fixed allow-list. Treat `invalid_client` and `unauthorized_client` as IdpUnavailable (leading to `temporarily_unavailable`) and log a constant-text WARNING: 'idp client authentication failed; check __oauth_idp__/client_secret'. Keep `invalid_grant` as IdpDenied. Log only the constant reason code, never the body (SI-2). Add tests for 401 invalid_client and 400 invalid_grant.
- codify:
- sdkCandidate: true

### RT-006
- severity: medium
- file: agent_sdk/auth/oidc.py
- description: Still open from A1 D-04; raised in two phase rounds. _check_issuer_host and _request (lines ~108-154) are a second URL-fetch helper beside common/http.py::safe_get (LRN-016 says extend, do not duplicate). They import the private _is_non_public_ip, resolve DNS with getaddrinfo, then let httpx resolve again, which leaves a DNS-rebinding gap between check and connect. The whole non-public-IP check is skipped whenever the public `transport` constructor argument is set. No test covers the resolve-and-deny branch.
- fix: Extract a shared public helper in common/http.py (for example `assert_public_host(host, resolver=None)` and `safe_request(method, url, *, data, max_bytes, _resolver, _transport)`) that pins the connection to the vetted IP, and use it from both callers. Make the test seam private and keep the resolver check separate from the transport. Test that a host resolving to 127.0.0.1 or 169.254.169.254 gives IdpUnavailable even with a transport injected.
- codify: An SSRF guard that resolves DNS and then lets the client resolve again is a check-then-use gap; pin the vetted IP or share one fetch helper.
- sdkCandidate: true

### RT-007
- severity: medium
- file: agent_sdk/auth/oidc.py
- description: Raised in two phase rounds (low, then medium). IdpFlowStore is one global LRU of 1,000 flows and 1,000 tickets with a 600 s lifetime, filled by the unauthenticated GET /oauth/authorize (DCR is open) and rate-limited only per IP. At the default 30 requests/min per IP, about four source IPs keep the table full, evicting every real user's pending flow while they are at the IdP. Attackers with no credentials can block sign-in for the whole tenant; with AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS on, users have no other way in. Separately, with 3 unauthenticated hits per sign-in on the shared per-IP limiter (30/min), an office behind one NAT IP gets about 10 sign-ins per minute.
- fix: Cap pending flows per client IP (and/or per client_id) inside IdpFlowStore, on top of the global cap. Alternatively, make the authorize leg stateless: put the flow in an AES-GCM-sealed `state` bound to the cookie and keep only a single-use nonce set. Add a test that one IP cannot evict another IP's flows. Document the eviction behaviour and the NAT / trusted-proxy guidance in docs/security.md.
- codify: An unauthenticated endpoint that inserts into a shared bounded LRU needs a per-caller quota, or eviction becomes a denial-of-service lever.
- sdkCandidate: true

### RT-008
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: Raised in three phase rounds. Every federated flow uses the same cookie name, `__Host-agent_sdk_idp` (line 93), and _federate (line 681) overwrites it each time. If one browser has two authorize flows in flight within 10 minutes (a retried popup, connecting both the MCP and A2A surfaces, or Claude.ai reopening authorize), the second Set-Cookie replaces the first flow's binding. The first callback or consent POST then fails flows.pop(state, cookie) and lands on the dead-end 400 'This sign-in link is invalid or has expired' page with no redirect back to the client. No test covers two concurrent flows.
- fix: Either key the cookie per flow (for example `__Host-agent_sdk_idp_<sha256(state)[:16]>`, looked up by state in the callback and consent POST), or reuse an existing valid cookie value as the binding so several flows share it (each keeps its own single-use state). Add test_two_concurrent_flows_same_browser_both_complete with two interleaved flows in one cookie jar.
- codify: A browser-binding cookie for a multi-step login must be keyed per flow, or concurrent flows in one browser break each other.
- sdkCandidate: true

### RT-009
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: `oauth_idp_consent` calls `store.mark_consented(client_id)`. This is the same persisted `consented` flag that the one-time-consent path in `oauth_authorize_page` treats as 'an admin approved this client'. Under IdP mode any signed-in tenant user can set it, including a victim tricked into clicking Allow on an attacker's dynamically registered client. If the operator later switches to `AGENT_SDK_OAUTH_IDP=none` + `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` (the documented alternative mode), that client is auto-issued a userless, org-wide code with no admin key, because client records survive restarts.
- fix: Do not reuse `consented` for IdP consent. Write a separate field (e.g. `idp_consented`), or skip the write and protect clients from eviction under IdP by live refresh alone (`cid not in live`). Alternatively, gate the one-time-consent branch on a marker that only the admin-key approve path writes. Add a test: consent via IdP, rebuild the app with IdP off and one-time consent on, and assert GET /oauth/authorize still renders the admin consent page.
- codify: A persisted approval flag must record WHO approved; reusing an admin-approval flag for a weaker approval path silently upgrades it when the operator changes modes.
- sdkCandidate: true

### RT-010
- severity: medium
- file: agent_sdk/auth/middleware.py
- description: Still open from A1 D-05 and D-11; raised in three phase rounds. The public resolve_identity (line 88-89, exported from agent_sdk.auth beside require_identity) ignores AuthRuntime.idp_disable_api_keys and skips both rate limiters. An agent escape-hatch route that gates on `resolve_identity(request) is not None` keeps accepting non-admin user keys after the operator turns them off (ADR-003 D3). Separately, require_identity calls _resolve_identity first, which sets request.state.identity and charges the identity limiter for a key it then rejects with 401, so later readers of request.state.identity see the refused caller as authenticated.
- fix: Move the non-admin api_key rejection into _resolve_identity behind a flag, so it runs before request.state.identity is set and before the identity limiter is charged. Make resolve_identity return None for a non-admin key when the switch is on. Add tests for both.
- codify: When a policy switch is added to one auth dependency, every exported identity resolver beside it must apply the same switch or be documented as non-gating.
- sdkCandidate: true

### RT-011
- severity: medium
- file: agent_sdk/auth/oauth_tokens.py
- description: Refresh-store growth and scan cost; raised in four phase rounds (medium and low). IdP sign-in makes the refresh store hold one family per (client, person) instead of one per client. Each hourly rotation leaves a tombstone kept until refresh expiry (up to 720 h, about 720 tombstones per 30-day session). `_prune_refresh` (line 506), `revoke_family`, and the new `_clients_with_live_refresh` (line 226) all list and AES-GCM-decrypt every NS_OAUTH_REFRESH row, synchronously on the event loop. `_clients_with_live_refresh` runs on every unauthenticated POST /oauth/register once the client table is at MAX_CLIENTS with IdP on, and it wrongly counts rotated tombstones as live. Measured: 0.13 s per registration with 20k refresh rows. A per-IP DCR stream can force repeated full-table decrypts that block every other request. ADR-003 does not mention refresh-store growth.
- fix: Keep an in-memory or persisted per-client 'last live refresh expiry' index (or `last_refresh_at` on the client record), updated in mint_token_pair, rotate_refresh and revoke_family, instead of scanning. Or cache the live set briefly. Skip rotated tombstones. Index refresh rows by family_id and client_id, or delete tombstones once a family's newer token is used. Do not run a full scan on the unauthenticated DCR path. Add a test that counts store.get calls during an at-capacity registration and asserts they do not scale with refresh rows. Document the ceiling in ADR-003 Consequences and DESIGN.md §5.5.
- codify:
- sdkCandidate: true

### RT-012
- severity: medium
- file: agent_sdk/auth/oauth_tokens.py
- description: Client-capacity lockout; raised in two phase rounds. The new eviction rule (_evict_clients_if_needed) never evicts a user-consented client that holds a live refresh family. Any assigned directory user can register about 200 DCR clients, sign in, and click Allow on each. That pins all MAX_CLIENTS slots for up to SESSION_HOURS (720 h), and every later /oauth/register returns 'client registration capacity reached' for the whole tenant. MAX_CLIENTS=200 also caps legitimate IdP rollouts where the connector registers a client per user. ADR-003 does not mention client capacity.
- fix: Bound protected user-consented clients per user (record the user on mark_user_consented and keep only the newest N per user), or keep user-consented clients evictable after a short idle window. Make MAX_CLIENTS configurable. Add a test that one user cannot exhaust registration capacity. Document the ceiling in ADR-003 and DESIGN.md §5.5.
- codify: A non-admin action that shields a record from eviction needs a per-actor quota, or it turns the capacity cap into a lockout.
- sdkCandidate: true

### RT-013
- severity: medium
- file: docs/security.md
- description: GH-152-E documentation ACs still unmet; carried from A2 RT-006 and raised in five phase rounds. (1) The surface table (lines 9-14) has no API-key-switch column; the switch is only a bullet at line 48 under 'Optional IdP sign-in'. (2) The IdP section never says discovery, token and JWKS endpoints are pinned to the issuer host, so Google and other split-host IdPs fail closed in v1 with only 'temporarily_unavailable'. (3) The `/oauth/revoke` row still reads 'oauth callers for their own tokens only'. It omits that any API key, including a non-admin user key that the switch disables everywhere else, can still revoke any token (oauth.py:1001-1010, the D3 'not covered' column), and that oauth ownership is now client_id AND user.
- fix: Add a 'With AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true' column to the surface table (rejected for non-admin keys on A2A/AG-UI/MCP; accepted on /admin and /oauth/revoke). Add an issuer-host pinning bullet. Reword the revoke row: api_key callers (admin or not) may revoke any token; oauth callers may revoke only their own (client_id and user).
- codify: Docs ACs listing specific columns or steps must be checked item by item; a prose bullet does not satisfy a required table column.
- sdkCandidate: true

### RT-014
- severity: medium
- file: docs/security.md
- description: The new IdP section tells operators to 'Lower it [AGENT_SDK_OAUTH_IDP_SESSION_HOURS] for faster cut-off'. The code does not support this. mint_token_pair stamps family_expires_at once at first mint, and rotate_refresh copies the stored value forward (mint_token_pair(family_expires_at=float(family_cap))). Lowering the setting and restarting does not shorten any existing session. There is also no operator path to revoke one person's tokens: POST /oauth/revoke needs the token value, which the operator never has, and there is no admin revoke-by-user or revoke-all-OAuth route. A fired employee keeps access for the full original cap (default 30 days).
- fix: Either (a) persist `family_started_at` and compute the cap at each rotation as min(stored cap, started_at + current session_ttl), so lowering the setting takes effect at the next refresh, with a test; or (b) correct the doc to say the change applies only to new sign-ins. Also add (or list as an ADR-003 follow-up) an admin route that revokes every refresh family whose `user` matches a given value, and document it as the emergency off-boarding path.
- codify:
- sdkCandidate: true

### RT-015
- severity: medium
- file: harness/skills/setup/SKILL.md
- description: GH-152-E setup-skill AC only partly met; carried from A2 RT-005 and raised in four phase rounds. (1) The Entra section has no restart step after setting the env vars and the __oauth_idp__ client secret. (2) AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS is not mentioned at all. Per the maintainer's 2026-10-09 ruling, the docs must say this switch refuses non-admin user keys only, and admin keys keep working on every route (console, /acceptance, /agent-verify), so the admin key must be protected. (3) The section only says to 'plan' the .env entries; it never ties them to the Phase 3 write step. (4) workspace/adr/a003-oauth-idp-sign-in.md 'Consequences' still says 'With the API-key switch on, console chat and protocol-level harness probes need it off', which contradicts D3.
- fix: Add a restart step and an API-key-switch bullet to the Entra section in both harness/skills/setup/SKILL.md and template/.claude/skills/setup/SKILL.md, kept identical. Make Phase 3 write the AGENT_SDK_OAUTH_IDP* keys. Fix the ADR-003 Consequences bullet to match D3.
- codify:
- sdkCandidate: true

### RT-016
- severity: medium
- file: harness/skills/setup/SKILL.md
- description: The setup skill contradicts itself in a way that guarantees a boot failure. Phase 0 step 4 says 'If OAuth is selected' the operator picks a per-user or per-org one-time consent scope, and 'Either scope sets AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true in .env' (line 74). Phase 3 writes it (line 298). The Entra bullet only adds 'Do not set AGENT_SDK_OAUTH_ONE_TIME_CONSENT with it' (line 93). An agent following the skill for an Entra deployment writes ONE_TIME_CONSENT=true and AGENT_SDK_OAUTH_IDP=oidc, and build_app() refuses to boot (ADR-003 D10). Distinct from RT-015.
- fix: Make the one-time-consent scope question conditional: when Entra sign-in is chosen, skip it and state that IdP sign-in replaces admin-key consent. Guard the Phase 3 `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` line with 'only if Entra sign-in was NOT chosen'. Mirror to template/.claude/skills/setup/SKILL.md and add a parity/text test asserting the guard exists.
- codify:
- sdkCandidate: true

### RT-017
- severity: medium
- file: template/.claude/workflows/wave-cycle.js
- description: Raised in two phase rounds. The GH-152-E template mirror edits (AUTH_SURFACE 'src/auth/oidc' in .claude/workflows/wave-cycle.js, and the Entra block in .claude/skills/setup/SKILL.md) exist only in the template working tree. Template HEAD (ce6dbb5) has neither (`git -C template show HEAD:... | grep -c` returns 0 for both). The working-tree copies match harness/, and the w042 closing note lists this as an OPEN deliverable needing user approval, so the AC's fallback clause is met — but downstream agents seeded from wailuen/a2a-agent-template get neither change (LRN-071/LRN-085).
- fix: After the user approves, stage only the two w042 hunks (`git -C template add -p .claude/workflows/wave-cycle.js .claude/skills/setup/SKILL.md`, splitting the AUTH_SURFACE line out of the larger hunk), commit, and push to wailuen/a2a-agent-template. Verify with `git -C template show HEAD:.claude/workflows/wave-cycle.js | grep src/auth/oidc`. Keep the closing note OPEN until then.
- codify: A template mirror that exists only in the template's working tree is not delivered; keep it on the wave's open-deliverable list until template HEAD contains it.
- sdkCandidate: true

### RT-018
- severity: medium
- file: tests/test_gh152_idp_off_regression.py
- description: Raised in two phase rounds; earlier flagged at A2 R3/R5 RT-007. The GH-152-D 'Off = byte-identical' AC requires POST approve, token, refresh and revoke responses to equal today's output with AGENT_SDK_OAUTH_IDP=none. The file only hashes the GET consent page and the three discovery documents. test_idp_off_admin_key_approve_and_token_have_no_user checks only status and `user is None`. Refresh, revoke and DCR/client-capacity behaviour are not pinned. This gap is how the earlier off-mode eviction change got through. Separately, test_admin_key_consent_disabled_under_idp (test_gh152_idp_authorize_flow.py:242) asserts only a 400 with no Location; a regression that mints a code before returning 400 still passes.
- fix: Add golden captures from the pre-GH-152 code for the approve 303 (Location with the code normalised), the token and refresh JSON key sets, headers and `expires_in`, the revoke response, the persisted refresh-record key set, and an IdP-off DCR-past-capacity scenario that asserts consented clients survive. In the IdP-on POST test, assert store.get_client(cid)['consented'] is falsy and store._codes is unchanged.
- codify: A 'byte-identical when off' AC needs a golden assertion for every listed response, not status-code checks.
- sdkCandidate: true

### RT-019
- severity: medium
- file: tests/test_gh152_idp_settings_boot.py
- description: Still open from A1 D-06/D-07. The SI-4/SI-6 test pins are missing. `test_boot_warns_when_idp_secret_missing` never plants a stored `__oauth_idp__/client_secret` sentinel to prove it appears in no log record or boot error. No test shows that an OAuth-kind access token gets 403 on GET/PUT/DELETE of `/admin/api/credentials/__oauth_idp__/client_secret`, which the GH-152-A AC requires.
- fix: Add a boot test that stores a sentinel at NS_OAUTH_IDP/client_secret, attaches a DEBUG handler to the `agent_sdk` logger (LRN-106), runs the boot paths and asserts the sentinel is absent. Add a test that mints a real OAuth access token and asserts 403 on all three IdP credential endpoints.
- codify:
- sdkCandidate: true

### RT-020
- severity: medium
- file: agent_sdk/common/admission.py
- description: admission.py declares itself component 'C-024' in its docstring (and routes/mcp.py and routes/a2a.py cite C-024), but workspace/components/README.md has no C-024 row — an unregistered reusable component (Dimension 8). Its `identity_key` docstring still says the cap is 'really a per-ORG cap', which is no longer true when `user` is set.
- fix: Register C-024 (shared SSE admission bookkeeping, agent_sdk/common/admission.py, present). Update the `identity_key` docstring to say the key includes the signed-in user when IdP sign-in is on.
- codify:
- sdkCandidate: true

### RT-021
- severity: low
- file: agent_sdk/auth/oidc.py
- description: `_request` calls `await self._check_issuer_host()` outside its try/except (line 133). `_check_issuer_host` catches only OSError from getaddrinfo and ValueError from the literal-IP parse. A UnicodeError from IDNA encoding of an unusual issuer host, or a ValueError from `ipaddress.ip_address(info[4][0])` on a scoped IPv6 result like 'fe80::1%en0', escapes. /oauth/authorize and /oauth/idp/callback then return 500 instead of `temporarily_unavailable`, breaking ADR-003 D8.
- fix: Move the `_check_issuer_host()` call inside the try block of `_request`, or wrap its body so any exception becomes IdpUnavailable after logging only the exception type (LRN-221). Strip any '%scope' suffix before parsing resolved addresses.
- codify:
- sdkCandidate: true

### RT-022
- severity: low
- file: agent_sdk/auth/oidc.py
- description: `validate_id_token` (line 296) catches only `jwt.PyJWTError`. When the JWKS entry for a token's kid is not an RSA key (EC or oct during IdP key rotation), PyJWT raises a bare `TypeError('Expecting a PEM-formatted key.')` (verified against the installed PyJWT). That escapes `oauth_idp_callback`, which handles only IdpDenied/IdpUnavailable, so the request returns 500, contrary to ADR-003 D8.
- fix: In `_fetch_jwks`, keep only keys whose `kty == 'RSA'` (and `use` absent or 'sig'). Add `except (TypeError, ValueError): raise IdpDenied('invalid_token') from None` after the PyJWTError clause. Add a test with an EC key under the token's kid.
- codify:
- sdkCandidate: true

### RT-023
- severity: low
- file: agent_sdk/auth/oidc.py
- description: `json.loads` on a deeply nested body raises RecursionError (verified), which is not a ValueError. In `_get_json` and `exchange_code` it escapes the `except ValueError`, is not an IdpError, and reaches the routes as a 500. ADR-003 D8 says malformed JSON is 'never a 500'. Needs a hostile or broken issuer-host response, so risk is low.
- fix: Catch `(ValueError, RecursionError)` around both `json.loads` calls, or wrap `build_authorize_url`/`exchange_code`/`validate_id_token` so any non-IdpError becomes IdpUnavailable (logging only the exception type).
- codify:
- sdkCandidate: true

### RT-024
- severity: low
- file: agent_sdk/auth/oauth_tokens.py
- description: Raised in two phase rounds (A1 D-12/D-14/D-15). (1) The family-cap revoke branch in rotate_refresh (~lines 422-427) is unreachable: mint_token_pair clamps refresh expires_at to family_expires_at, so the plain-expiry branch fires first and deletes only the presented row. The family-revoke code is untested. (2) require_user is enforced only in rotate_refresh; mint_token_pair and consume_code still accept user=None under IdP mode, so ADR-003 D6 rests only on route gating. (3) `expires_in=int(access_ttl)` can be 0 when less than 1 s of the cap remains.
- fix: Check the family cap before the plain expiry check (or delete the dead branch) and test that the family's rows are gone after the cap. In mint_token_pair, refuse when self._require_user and not user. Refuse to mint when the remaining cap is below a small floor (for example 5 s).
- codify:
- sdkCandidate: true

### RT-025
- severity: low
- file: agent_sdk/app.py
- description: Raised in two phase rounds (A1 D-09/D-16). The runtime IdP wiring relies on a bare `assert settings.oauth_idp_issuer and settings.oauth_idp_client_id` (~line 789), which `python -O` strips. The ADR-003 D2 warning for AGENT_SDK_OAUTH_IDP_SURFACES (~line 522) checks only os.environ, and only when oauth_idp=oidc. pydantic-settings reads .env without copying into os.environ, so a value set in .env (the setup skill's location) is silently ignored.
- fix: Replace the assert with an explicit if/raise ValueError naming the settings. Detect SURFACES in the dotenv source too (dotenv_values(model_config['env_file'])), or declare an ignored oauth_idp_surfaces field, and warn whenever it is set. Add a tmp-.env test.
- codify:
- sdkCandidate: true

### RT-026
- severity: low
- file: agent_sdk/routes/oauth.py
- description: With IdP off, /oauth/idp/callback and /oauth/idp/consent are still mounted and return 404 only inside the handler. Depends(unauth_rate_limit) runs first and charges the caller's unauth budget (a 429 can appear where an unrouted path gives 404). Other methods get 405 instead of 404, revealing the feature exists, so the off state is not identical to having no route.
- fix: Include the IdP routes in a separate router mounted only when oauth_idp == 'oidc', or run the 404 check as a dependency before the rate limiter. Extend test_idp_off_idp_routes_404 to cover POST /oauth/idp/callback and GET /oauth/idp/consent.
- codify:
- sdkCandidate: true

### RT-027
- status: RESOLVED (GH-166): uvicorn.access filter strips /oauth/ query strings; proxy and ingress logs documented as not covered
- severity: low
- file: agent_sdk/routes/oauth.py
- description: The SI-2 AC says the IdP code and state never appear in logs. But response_mode=query puts both in the /oauth/idp/callback URL, which the standard uvicorn access log records in full. test_no_idp_secrets_in_logs_or_responses watches only the agent_sdk logger.
- fix: Add a uvicorn.access logging filter that strips the query from /oauth/idp/callback, or document the exposure and narrow the AC to the SDK's own loggers.
- codify:
- sdkCandidate: true

### RT-028
- severity: low
- file: agent_sdk/routes/oauth.py
- description: Duplicated logic. _pkce_pair re-implements the S256 base64url(sha256) step that oauth_tokens.verify_pkce_s256 already has. _redirect_with duplicates _error_redirect's URL builder. _federate reads the client secret directly from app.state.credential_store, separately from the OidcRelyingParty secret_provider lambda, giving two sources of truth.
- fix: Extract s256_challenge(verifier) in oauth_tokens and use it in both places. Make _error_redirect call _redirect_with. Add rp.has_secret() backed by the same provider and use it in _federate.
- codify:
- sdkCandidate: true

### RT-029
- severity: low
- file: agent_sdk/routes/admin.py
- description: GET /admin/api/credentials always returns the new `oauth_idp` card and reads the __oauth_idp__ field, even with AGENT_SDK_OAUTH_IDP=none. console.js always renders 'IdP sign-in (AGENT_SDK_OAUTH_IDP)', inviting operators to set a secret that does nothing.
- fix: Return the oauth_idp card only when settings.oauth_idp == 'oidc', or label it 'inactive' when off.
- codify:
- sdkCandidate: true

### RT-030
- severity: low
- file: agent_sdk/console/static/console.js
- description: console.js gained the `oauth_idp` credentials card (lines 336-342), the documented way to set the IdP client secret ('/admin -> Credentials' in the setup skill and DESIGN.md). No w042 todo lists console.js in Creates/Modifies (GH-152-A lists only admin.py), and tests/test_card_console.py and tests/test_rt001_client_cap_idp.py are likewise changed/created outside any todo's scope record (LRN-202). No test asserts the console renders the `oauth_idp` group, so a JS regression silently removes the documented path while test_admin_can_set_idp_client_secret still passes.
- fix: Add console.js and test_card_console.py to GH-152-A's Modifies list and test_rt001_client_cap_idp.py to GH-152-D's Creates list. Add a console test asserting renderCredentials handles `data.oauth_idp`.
- codify:
- sdkCandidate: true

### RT-031
- severity: low
- file: tests/test_gh152_api_key_optout.py
- description: Raised in three phase rounds (A1 D-10). test_user_api_key_rejected_on_every_require_identity_route only asserts at least 13 covered routes (ADR_D3_MIN_ROUTES). A refactor that drops require_identity from one ADR-003 D3 route (for example GET /v1/card) and adds it to another still passes. The todo's SI-5 line still cites test_api_key_rejected_on_every_require_identity_route, which does not exist.
- fix: Pin the 13 ADR-003 D3 (method, path) pairs as a frozenset and assert it is a subset of _covered_routes(app), keeping the count check. Correct the SI-5 test name in the todo.
- codify:
- sdkCandidate: true

### RT-032
- severity: low
- file: CHANGELOG.md
- description: Raised in five phase rounds. The [Unreleased] GH-152 bullets carry the wrong todo IDs: the federated authorize/callback/consent routes are tagged 'GH-152-B/C' (line 11; they are GH-152-D) and the API-key switch is tagged 'GH-152-D' (line 15; it is GH-152-C). The new '### Added' heading also captures w041's GH-151 and Profile v1.1 metadata paragraphs. The reconciliation note says GH-152 'is the only work sitting ahead of [0.8.0]', which is false — w041's entries are unreleased too (LRN-145 scope). 'With AGENT_SDK_OAUTH_IDP=none, nothing changes' is unverified while the off-mode regression gaps stand (RT-018). The 'Session cap' bullet reads as always on, but applies only under oidc. The new public `register_client(pinned=)` and `mint_code(label=)` kwargs are not listed among the OAuthTokenStore API additions.
- fix: Relabel line 11 as GH-152-D and line 15 as GH-152-C. Give w041's paragraphs their own heading (or put the GH-152 bullets under a separate Added block). Reword the note to name both w041 and w042 as unreleased work ahead of [0.8.0]. Say 'under AGENT_SDK_OAUTH_IDP=oidc' on the session-cap bullet. Qualify the 'nothing changes' line. Add `register_client(pinned=...)` and `mint_code(label=...)` to the OAuthTokenStore kwargs bullet.
- codify:
- sdkCandidate: true

### RT-033
- severity: low
- file: agent_sdk/tasks/store.py
- description: Stale docs and comments (A1 D-13). TaskRecord.identity's comment (tasks/store.py:83), the auth/identity.py module docstring, admission.identity_key, and the config.py comment near line 211-212 still describe the binding as (kind, subject) and caps as per-org / keyed on Identity.subject; binding and principal_key now include `user` when set. The routes/oauth.py module docstring (line 12) still says 'The security gate is the admin-gated /authorize' and lists neither IdP route. The DESIGN.md §3 auth/ package tree omits oidc.py (C-023).
- fix: Update each comment to say the binding is `(kind, subject)` or `(kind, f"{subject}|{user}")` and that caps are per signed-in user when IdP sign-in is on. Update the oauth.py docstring with the federation branch and the two IdP routes. Add `oidc.py  # OIDC relying party + IdpFlowStore (GH-152, opt-in)` to the DESIGN.md tree.
- codify:
- sdkCandidate: true

### RT-034
- severity: low
- file: harness/workflows/wave-cycle.js
- description: These in-scope workflow files carry about 1,300 lines of uncommitted divergence from HEAD unrelated to GH-152-E's one-line AUTH_SURFACE change: GH-131 `normalizedArgs` (missing from HEAD) and a reworded `meta` description. The working tree's description of Unit Redteam and Codify no longer mentions concurrent groups, the mutex or batched LRN capture, though the code still runs groups in parallel. Committing the w042 scope as-is would ship this unreviewed drift and a misleading phase description.
- fix: Split the w042 AUTH_SURFACE hunk from the unrelated divergence before committing. Reconcile the meta description with the code (concurrent Unit Redteam with mutex-serialised fix step, single-group Phase skip, batched LRN capture) in all mirrors.
- codify:
- sdkCandidate: true
