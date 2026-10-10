wave: w042
group: A2
date: 2026-10-09
round_count: 5
status: budget-exhausted

## Findings

### RT-001
- severity: high
- file: template/.claude/workflows/wave-cycle.js
- description: [SDK] The GH-152-E template mirrors are edited but never committed or pushed to wailuen/a2a-agent-template. This covers the AUTH_SURFACE `src/auth/oidc` member and the Entra section of template/.claude/skills/setup/SKILL.md. The todo annotation requires an explicit `git -C template/ commit && git -C template/ push` final step, and LRN-071's Check fails: `git -C template status --short` shows both files modified, and template HEAD is still ce6dbb5. The template's wave-cycle.js diff is also 1,483 lines, so earlier waves' changes are bundled in the same unpushed file. Downstream agents that clone the template get neither the oidc AUTH_SURFACE member nor the Entra setup steps.
- fix: Inside template/, stage only this wave's hunks (`git -C template add -p .claude/workflows/wave-cycle.js .claude/skills/setup/SKILL.md`), then commit and push to wailuen/a2a-agent-template. If the earlier waves' hunks cannot be split out, name the unpropagated files in the wave closing note as an open deliverable. Do not leave the step implicit.
- codify: A todo that names a template/ mirror is not done until `git -C template status --short` is clean for that path or the closing note names it as unpropagated.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/app.py
- description: [SDK] The ADR-003 D2 warning for the unsupported AGENT_SDK_OAUTH_IDP_SURFACES setting checks only `os.environ` (app.py:522). BaseAgentSettings loads `.env` through pydantic-settings with extra="ignore", and that loader does not copy values into os.environ. So an operator who puts the variable in `.env` (the location the setup skill tells them to use) gets no warning, and the variable is silently ignored. The test only uses monkeypatch.setenv, so it misses this path.
- fix: Detect the key from both sources: os.environ and the parsed dotenv file (for example `dotenv_values(settings.model_config['env_file'])`, or a declared `oauth_idp_surfaces: str | None` settings field used only to trigger the warning). Add a test that writes the key to a tmp `.env` file and asserts exactly one WARNING.

### RT-003
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: [SDK] Every federated authorize uses one fixed cookie name (`__Host-agent_sdk_idp`, line 93). `_federate` overwrites it on each call. When one browser has two authorize flows open (two connectors, a retried popup, or Claude.ai re-opening authorize), the later Set-Cookie replaces the earlier binding. The first flow's callback then fails `flows.pop(state, cookie)` and the user lands on the dead-end 400 page 'This sign-in link is invalid or has expired'. No test covers two concurrent flows.
- fix: Key the cookie per flow, for example `__Host-agent_sdk_idp_<first 16 chars of sha256(state)>`, or store a small set of bindings in one cookie. Look up the binding at callback and consent by the flow's state. Add `test_two_concurrent_flows_same_browser_both_complete`.

### RT-004
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: [SDK] Anyone can make `_federate` insert a server-side flow: DCR is open and GET /oauth/authorize is unauthenticated. The flows sit in IdpFlowStore's 1,000-entry LRU with a 600 s TTL. At the default unauth limit of 30/min per IP, about 4 source IPs can keep the table full and evict every real user's in-flight flow before they return from Entra. Those users see the 400 'invalid or expired' page, so attackers can block sign-in for the whole tenant.
- fix: Bound flows per client IP or per client_id inside IdpFlowStore. Alternatively, make the authorize leg stateless: put the flow in an HMAC- or AES-GCM-sealed `state` value tied to the cookie, and keep only a single-use nonce set. At minimum, add a test proving one IP cannot evict another IP's flows, and document the limit.

### RT-005
- severity: medium
- file: harness/skills/setup/SKILL.md
- description: [SDK] The Entra section of the setup skill is missing two items the GH-152-E acceptance criteria require. First, there is no restart step after setting the client secret in the admin Credentials card. Second, AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS is not mentioned at all: not its existence, not that it rejects user keys only, and not that admin keys (console chat, /acceptance, /agent-verify) keep working. Separately, the AC text and ADR-003's Consequences line ('With the API-key switch on, console chat and protocol-level harness probes need it off') contradict the D3 maintainer ruling that admin keys stay accepted. The docs are therefore internally inconsistent about what the switch breaks.
- fix: Add a restart step and a line on the API-key switch to both harness/skills/setup/SKILL.md and template/.claude/skills/setup/SKILL.md, kept identical. The line should say the switch rejects non-admin keys only, admin keys still work, and the admin key should therefore be protected. Fix ADR-003's Consequences bullet to match D3.

### RT-006
- severity: medium
- file: docs/security.md
- description: [SDK] Two GH-152-E acceptance criteria for docs/security.md are not met. (1) The surface table has no API-key-switch column. The switch behaviour only appears as a bullet in the new section, so the per-surface table still does not show which routes reject user keys under the switch. (2) Issuer-host pinning is not described: discovery, token and JWKS endpoints must be https on the issuer host, and Google and other split-host IdPs fail closed in v1. Operators trying Google will get only 'temporarily_unavailable' with no documented reason.
- fix: Add a column such as 'With AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS' to the Identities and surfaces table (A2A, AG-UI and /mcp: user keys rejected, admin keys accepted; admin, revoke, token and register unchanged). Add a host-pinning bullet to the 'Optional IdP sign-in' section.

### RT-007
- severity: medium
- file: tests/test_gh152_idp_off_regression.py
- description: [SDK] The off=byte-identical AC requires that, with AGENT_SDK_OAUTH_IDP=none, POST approve, token, refresh and revoke responses equal today's. The regression file golden-pins only the GET consent page and the three metadata documents. test_idp_off_admin_key_approve_and_token_have_no_user checks status codes and `user is None` only, and refresh and revoke are not exercised at all. Separately, test_admin_key_consent_disabled_under_idp checks only status 400 and no Location header. It never asserts that no code was minted or that `mark_consented` was not called, so a regression that verifies the key and mints a code before returning 400 would still pass.
- fix: Capture normalized golden hashes (token values masked) for the approve 303 headers, the token and refresh JSON key sets and headers, and the revoke response with IdP off. In the IdP-on POST test, assert that `store.get_client(cid)['consented']` stays False and that no code record exists.

### RT-008
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] With IdP off, /oauth/idp/callback and /oauth/idp/consent are still mounted and only raise 404 inside the handler. As a result, `Depends(unauth_rate_limit)` runs first and charges the caller's unauth budget (a 429 can come back where an unrouted path gives 404). Other methods also return 405 instead of 404: POST to the callback and GET to consent. So the off state is not byte-identical to an unrouted path, and the 405 reveals that the feature exists.
- fix: Mount the two routes only when IdP is enabled, for example via a separate `idp_router` that build_app includes when `oauth_idp == 'oidc'`. Alternatively, run the `_require_idp` 404 check as a dependency ahead of the rate limiter. Extend test_idp_off_idp_routes_404 to cover the cross-method requests.

### RT-009
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] The SI-2 AC says the IdP authorization code and flow state never appear in logs. However, the IdP returns both in the /oauth/idp/callback query string (response_mode=query), and the standard uvicorn access log records the full path with that query. test_no_idp_secrets_in_logs_or_responses only attaches to the `agent_sdk` logger, so it cannot see this. The code is single-use and needs the client secret plus the PKCE verifier to redeem, so the impact is low, but the documented guarantee is wrong.
- fix: Either document that the access log carries the callback query and advise operators to filter it, or add a small logging filter on `uvicorn.access` that strips the query from /oauth/idp/callback. Narrow the AC wording to the SDK's own loggers.

### RT-010
- severity: low
- file: CHANGELOG.md
- description: [SDK] The [Unreleased] entries mislabel the todo IDs: the federated routes are tagged 'GH-152-B/C' (they are GH-152-D), and the API-key switch is tagged 'GH-152-D' (it is GH-152-C). The new `### Added` heading now also sits above w041's GH-151 and Profile v1.1 paragraphs, re-filing them under Added. And the edited reconciliation note says GH-152 'is the only work sitting ahead of [0.8.0]', which is false because w041's entries are also unreleased.
- fix: Correct the todo IDs. Put the GH-152 bullets under their own `### Added` heading without capturing w041's paragraphs, or give those paragraphs their own headings. Change the reconciliation note to say both w041 and w042 work sits ahead of [0.8.0].

### RT-011
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] Several docs are stale. The oauth.py module docstring (lines 1-37) still says 'The security gate is the admin-gated /authorize' and lists neither /oauth/idp/callback nor /oauth/idp/consent. The oauth_authorize_page docstring does not mention the federation branch. The DESIGN.md §3 package tree under `auth/` does not list the new `oidc.py` (component C-023).
- fix: Add the two IdP routes and the federation branch to the module docstring and to the authorize-page docstring. Add `oidc.py  # OIDC relying party + IdpFlowStore (GH-152, opt-in)` to the DESIGN.md auth/ tree.

### RT-012
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] The new code duplicates existing logic and has two sources of truth. `_pkce_pair` (line 641) re-implements the S256 base64url-of-sha256 computation that `oauth_tokens.verify_pkce_s256` already contains. `_redirect_with` (line 647) duplicates the redirect-building block that `_error_redirect`, the approve path and the one-time-consent path each spell inline. `_federate` reads the client secret directly from `app.state.credential_store`, separate from the `OidcRelyingParty` secret_provider lambda, so the two checks can drift apart. app.py:789 also uses a bare `assert` for issuer and client_id in production code; `python -O` strips it.
- fix: Extract an `s256_challenge(verifier)` helper in oauth_tokens and use it in both places. Have `_error_redirect` call `_redirect_with`. Expose `rp.has_secret()` that uses the same provider. Replace the assert with an explicit type-narrowing `if` that raises.

## Instruction

Fix remaining findings, then re-run /wave w042.
