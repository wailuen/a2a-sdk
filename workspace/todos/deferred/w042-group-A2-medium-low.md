wave: w042
group: A2
date: 2026-10-09
status: non-blocking (medium/low)

Non-blocking — these did not block w042's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every unit redteam round for group A2 and deduped by file+description. Redteam IDs restart each round, so each heading carries its round number (R1–R5). Several findings recur across rounds with different wording. They are kept separately because their descriptions differ, and the theme index below groups them.

## Theme index

- IdP test gaps (PyJWT dev extra, SI-2 no-leak pin, discovery-unchanged tautology, off-regression goldens): R1 RT-002, R1 RT-003, R1 RT-004, R2 RT-002, R2 RT-003, R3 RT-002, R3 RT-003, R4 RT-009, R5 RT-007
- Per-flow browser-binding cookie (`__Host-agent_sdk_idp`) and lifecycle: R1 RT-010, R2 RT-007, R3 RT-007, R4 RT-004, R5 RT-003
- IdpFlowStore eviction / denial of sign-in: R3 RT-008, R5 RT-004
- IdP failure reason codes not logged: R1 RT-005, R4 RT-003
- Issuer canonicalisation (uppercase GUID, login.windows.net): R4 RT-002
- docs/security.md (API-key column, issuer-host pinning, revoke row): R1 RT-006, R2 RT-004, R3 RT-004, R4 RT-007, R5 RT-006
- Setup skill Entra section (restart, DISABLE_API_KEYS, secret step, Phase 3 .env): R1 RT-007, R2 RT-011, R3 RT-010, R4 RT-005, R5 RT-005
- Template peer-repo mirror not committed/pushed: R1 RT-008, R2 RT-005, R3 RT-006, R4 RT-006
- Foreign hunks absorbed into wave-cycle.js mirrors / stale meta text: R2 RT-013, R3 RT-005
- IdP routes mounted when IdP off (405, openapi, rate-limit charge): R1 RT-009, R2 RT-006, R4 RT-012, R5 RT-008
- SURFACES warning ignores .env; secret-missing falsy check: R1 RT-011, R5 RT-002
- http PUBLIC_URL with `__Host-` cookie: R2 RT-008
- Duplicated code / two secret sources / bare assert: R1 RT-012, R2 RT-009, R3 RT-012, R4 RT-010, R4 RT-011, R5 RT-012
- CHANGELOG labels and reconciliation note: R2 RT-010, R3 RT-009, R4 RT-008, R5 RT-010
- Stale docstrings / DESIGN.md auth tree / component registry: R1 RT-013, R2 RT-012, R3 RT-011, R5 RT-011
- Consent POST returns JSON on bad body: R1 RT-014
- uvicorn access log carries callback code/state: R5 RT-009

## Findings

### R1 RT-002
- severity: medium
- file: tests/test_gh152_idp_authorize_flow.py
- description: [SDK] tests/test_gh152_idp_authorize_flow.py (line 16), tests/test_gh152_oidc_rp.py, and test_gh152_idp_no_secret_leak.py (which imports the first file) all import `jwt` at module level. PyJWT is not in the `[dev]` extra; it is only present because `msal` (the `[obo]` extra) pulls it in. The /sdk-test gate installs `-e ".[dev]"`, so in a clean venv collection fails and the whole gate goes red. test_gh152_idp_off_regression.py::test_idp_off_admin_key_approve_and_token_have_no_user also imports from the authorize-flow module, so an IdP-OFF regression test depends on the optional extra.
- fix: Add "PyJWT[crypto]>=2.8" to the `[dev]` extra (preferred, so these security tests always run), or reference `oidc` from dev. Do not use importorskip, which would silently skip the SI-2/SI-5 pins. Move the `pkce()` helper the off-regression test uses into a jwt-free helper module.
- codify: Tests for an optional extra must have that extra in the [dev] install the release gate uses; a transitive install from another extra hides the gap until a clean CI venv.
- sdkCandidate: true

### R1 RT-003
- severity: medium
- file: tests/test_gh152_idp_no_secret_leak.py
- description: [SDK] The SI-2 pin test_no_idp_secrets_in_logs_or_responses is weaker than its AC. (1) IDP_AT='AT' is a 2-character non-sentinel, and FakeIdp returns no refresh_token, so the 'IdP access/refresh token never leaks' clause is effectively untested. (2) Collector reads record.exc_text, which stays None unless a Formatter has run, so traceback text from exc_info logs is never scanned. (3) idp.claims['id_token'] is overwritten by later callbacks, so the success-path ID token is never checked. (4) The AC asks it to drive every failure path, but it skips the missing secret, an outage at exchange, an IdP 4xx at the token endpoint, consent Deny, consent replay and cookie mismatch.
- fix: Use long unique sentinels for the IdP access_token and a new refresh_token in the FakeIdp token response. In Collector.emit, format exc_info with logging.Formatter().formatException(record.exc_info). Capture each path's id_token in a list and check all of them. Add the missing failure paths (secret deleted, idp.down at exchange, a 400 token response, deny, ticket replay, cookie mismatch) to the scanned response and log set.
- codify: A no-leak test must use high-entropy sentinels, format exc_info itself (exc_text is lazy), and keep every planted value instead of overwriting it.
- sdkCandidate: true

### R1 RT-004
- severity: medium
- file: tests/test_gh152_idp_authorize_flow.py
- description: [SDK] test_idp_on_discovery_documents_unchanged (line 456) mostly compares the PRM document to values taken from itself (resource is rebuilt from prm['resource'], authorization_servers from prm['authorization_servers']). It never compares the IdP-on output with IdP-off output, and it does not cover the 401 + WWW-Authenticate challenge or the CORS preflight the AC lists. Related gap: test_refresh_keeps_user_and_family_cap (line 427) only checks that family_expires_at is present, not that rotation copied the original value instead of setting a new one.
- fix: Build an IdP-off app and an IdP-on app from the same base settings and assert byte-equal PRM (both paths) and AS metadata. Assert that an unauthenticated POST /mcp returns 401 with an identical WWW-Authenticate value on both, and that OPTIONS preflight returns 204 with identical CORS headers. In the refresh test, record family_expires_at before rotation and assert it is unchanged after.
- codify: An 'X unchanged when the feature is on' test must diff against a feature-off instance, never against values taken from its own response.
- sdkCandidate: true

### R1 RT-005
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: [SDK] An operator cannot diagnose an IdP misconfiguration. In oauth_idp_callback (lines 769-773) and _federate (line 673), IdpUnavailable is swallowed with no log line, and IdpDenied logs only 'sign-in denied' without its fixed reason_code. oidc._fetch_discovery also raises IdpUnavailable with no log for an issuer mismatch or an endpoint off the issuer host. So an operator with a wrong tenant, a missing app role, a Google-style off-host JWKS or a wrong issuer string sees only 'temporarily_unavailable'/'access_denied' at the client and nothing in the agent logs.
- fix: Log IdpDenied.reason_code at INFO/WARNING in the callback; it is a fixed constant, so SI-2 is safe. Give IdpUnavailable a fixed reason_code too (e.g. 'issuer_mismatch', 'endpoint_off_issuer_host', 'http_status', 'oversize', 'secret_missing') and log it at WARNING in _federate and in the callback. Never interpolate hosts, statuses or bodies.
- codify: Fail-closed auth errors must log a fixed reason code server-side; a generic client error plus a silent server log makes misconfiguration undiagnosable.
- sdkCandidate: true

### R1 RT-006
- severity: medium
- file: docs/security.md
- description: [SDK] The GH-152-E docs AC is not fully met. The security.md section at line 38 does not mention that ADR-003 D8 pins discovery, token and JWKS endpoints to the issuer host (IdPs such as Google that serve JWKS from another host are unsupported and fail closed). DESIGN.md §5.5/§6 and the setup skill also omit it. The AC asked for an 'API-key switch column' in the surface table, but it is only a bullet. The DESIGN.md §5.5 addendum (line 399) says 'token, refresh and revoke are unchanged', which contradicts §6: refresh now has an absolute family cap and refuses user-less families, and oauth-caller revoke is now scoped per (client, user).
- fix: Add to security.md's IdP section and to the DESIGN.md addendum: endpoints are pinned to the issuer host, Google is unsupported in v1, and the 10 s / 512 KiB / no-redirect client limits. Add an API-key column to the surface table. Reword the DESIGN.md addendum to 'DCR, PKCE, PRM and AS metadata are unchanged; refresh gains the absolute family cap and revoke is scoped per (client, user)'.
- sdkCandidate: true

### R1 RT-007
- severity: medium
- file: harness/skills/setup/SKILL.md
- description: [SDK] The setup skill's new Entra section (lines 78-95) leaves out part of the GH-152-E AC. It has no restart step after setting the env vars, and it never mentions AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS: what it does, that it rejects only non-admin keys, and that admin keys still reach protocol routes. It also does not say that the client secret can only be set after first boot. Before it is set, /oauth/authorize returns temporarily_unavailable.
- fix: Add steps covering: restart the agent; log in to /admin and set __oauth_idp__/client_secret (sign-in returns temporarily_unavailable until then); optionally set AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true, which rejects user API keys while admin keys keep working (protect them). Mirror the text byte-identically into template/.claude/skills/setup/SKILL.md.
- sdkCandidate: true

### R1 RT-008
- severity: medium
- file: harness/workflows/wave-cycle.js
- description: [SDK] The template mirror changes for this group (template/.claude/workflows/wave-cycle.js with the src/auth/oidc AUTH_SURFACE member, and template/.claude/skills/setup/SKILL.md) are uncommitted in the template peer repo. `git -C template status` shows both as M, and `git -C template log -1` shows no propagation commit. That fails LRN-085's Check, and the plan's explicit commit+push step (LRN-071) has not happened. Downstream agents seeded from wailuen/a2a-agent-template will not get the new member.
- fix: In template/, stage only this wave's two files and commit them. Leave the other pre-existing uncommitted template edits untouched. Then push to wailuen/a2a-agent-template. If that is blocked, name both files plus the `diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js` check as an open deliverable in the wave's closing note.
- sdkCandidate: true

### R1 RT-009
- status: openapi.json part CLOSED by GH-231 (docs routes are dev-only); 405 and rate-limit parts remain
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] With AGENT_SDK_OAUTH_IDP=none, /oauth/idp/callback and /oauth/idp/consent are still registered on the router (lines 746, 778). So they show up in the default /openapi.json, wrong-method requests return 405 with an Allow header instead of 404, and each probe uses up the per-IP unauth limiter before the 404. 'Off = byte-identical' holds only for the endpoints the test pins.
- fix: Register the two IdP routes only when oauth_idp=oidc (a separate APIRouter included conditionally in build_app), or set include_in_schema=False and run the _require_idp 404 check before the rate-limit dependency. Add an off-mode test that /openapi.json has no /oauth/idp paths.
- sdkCandidate: true

### R1 RT-010
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] The __Host-agent_sdk_idp cookie is a single fixed name and is never cleared. A second /oauth/authorize in the same browser (for example two connectors authorizing at once) overwrites the first flow's binding, so the first callback fails and burns its state. Any page can also top-level-navigate a victim to /oauth/authorize?client_id=<any registered client> to replace the cookie and abort an in-progress sign-in. The cookie also lingers after consent or a terminal error.
- fix: Key the cookie per flow (for example __Host-agent_sdk_idp_<short hash of state>), or store the binding hash per state and accept any of a small set of cookie values. Send an expiring Set-Cookie on the consent 303/302 and on callback terminal errors.
- sdkCandidate: true

### R1 RT-011
- severity: low
- file: agent_sdk/app.py
- description: [SDK] The AGENT_SDK_OAUTH_IDP_SURFACES warning (line 522) checks only os.environ. Settings load from .env (env_file='.env', extra='ignore'), and the setup skill tells operators to configure in .env, so a SURFACES value there is silently ignored with no warning. _warn_idp_secret_missing also tests `is None` while _federate treats any falsy secret as missing, so an empty stored secret gives no boot warning but sign-in stays unavailable.
- fix: Detect SURFACES via the settings source: read the .env file through pydantic-settings' dotenv source, or add an excluded alias field. Make _warn_idp_secret_missing use `if not credential_store.get(...)` so it matches _federate.
- sdkCandidate: true

### R1 RT-012
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] There is duplicated logic. _redirect_with (line 647) was added, but _error_redirect (line 442) and the two existing success-redirect sites (approve POST around line 878, one-time-consent around line 621) still inline the same `sep = '&' if query else '?'` + urlencode construction, so there are 4 copies. _pkce_pair (line 641) re-implements base64url(sha256(verifier)), which oauth_tokens.verify_pkce_s256 already computes.
- fix: Route _error_redirect and both success-redirect sites through _redirect_with. Extract `pkce_s256_challenge(verifier)` in auth/oauth_tokens.py and use it in both verify_pkce_s256 and _pkce_pair.
- sdkCandidate: true

### R1 RT-013
- severity: low
- file: workspace/components/README.md
- description: [SDK] The registry is out of date. The C-014 AUTH_SURFACE entry still describes '5 members' and lists them without agent_sdk/auth/oidc and src/auth/oidc. The module docstring in agent_sdk/auth/oidc.py claims 'Component C-023 OidcRelyingParty / IdpFlowStore', but the registry has no C-023 row. Imported by routes/oauth.py, it is an unregistered reusable component (Dimension 8).
- fix: Update the C-014 entry to 6 members, including oidc. Add a C-023 row for OidcRelyingParty + IdpFlowStore (agent_sdk/auth/oidc.py) in the index table and the detail section, and confirm the codify step does not reuse C-022.
- sdkCandidate: true

### R1 RT-014
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] POST /oauth/idp/consent calls _parse_form without a try (line ~783). An oversize or non-UTF-8 body raises HTTPException, which FastAPI turns into a JSON {"detail": ...} response. The page gives the browser JSON, not the HTML error page that every other failure on this browser-facing route returns.
- fix: Wrap _parse_form in try/except HTTPException and return _idp_local_error() (HTML, _CONSENT_SECURITY_HEADERS), matching the callback's local-error behaviour.
- sdkCandidate: true

### R2 RT-002
- severity: medium
- file: tests/test_gh152_idp_no_secret_leak.py
- description: The SI-2 pin is weaker than the AC claims. (a) `idp.claims["id_token"]` (line 81) is read after the q4 replay call, which overwrote it with a fresh token that was never sent through the server, so the ID-token check is vacuous. (b) `verifier` is the CLIENT's PKCE verifier, which this test never sends to the server; the server's own IdP PKCE verifier (`idp.last_token_form["code_verifier"]`) is never checked. (c) Several paths the AC says to drive are skipped: consent deny, IdpUnavailable at exchange, callback cookie mismatch, the missing-secret authorize, and the /oauth/token exchange. (d) The IDP_AT sentinel is the 2-character "AT", which is collision-prone. (e) There is a dead line: `_, _, q5, c5 = (None, ...)`.
- fix: Capture every minted ID token (append to a list inside FakeIdp.handler) and every server verifier sent to the token endpoint, and assert none of them reach logs, response bodies/headers or the final redirect. Drive the remaining failure paths (deny, exchange outage, cookie mismatch, missing secret, token exchange). Use a long unique sentinel for the IdP access token, and delete the dead tuple line.
- sdkCandidate: true

### R2 RT-003
- severity: medium
- file: tests/test_gh152_idp_authorize_flow.py
- description: `test_idp_on_discovery_documents_unchanged` (line 456) does not meet the AC 'PRM, AS metadata, 401 + WWW-Authenticate, CORS preflight unchanged with IdP on and off'. The PRM assertion builds its expected `resource` and `authorization_servers` from the actual response, so it is tautological. The bare PRM is checked only for its key set. Neither the 401 + WWW-Authenticate challenge nor the CORS OPTIONS preflight is probed with IdP on. Separately, `test_refresh_keeps_user_and_family_cap` (line 427) only checks that `family_expires_at` exists; it never checks that rotation copied the same value.
- fix: Build an IdP-off and an IdP-on app with the same base URL. Assert the three discovery documents are byte-identical, or match the GOLDEN_METADATA SHAs. Assert an unauthenticated POST /mcp returns 401 with the same WWW-Authenticate header, and OPTIONS preflight returns the same 204 and headers in both modes. In the refresh test, assert the rotated record's `family_expires_at` equals the original.
- sdkCandidate: true

### R2 RT-004
- severity: medium
- file: docs/security.md
- description: GH-152-E's docs/security.md AC is partly unmet. The surface table (lines 6-14) gained the IdP routes but no API-key-switch column or marking. Issuer-host pinning of the discovery/token/JWKS endpoints (ADR-003 D8) is not documented anywhere in the file. The IdP material went into a separate subsection (line 38) instead of the required 'OAuth 2.1' section coverage.
- fix: Add an 'API key with DISABLE_API_KEYS' column, or per-row annotation, to the surface table: A2A/AG-UI/MCP rows → non-admin keys rejected, admin keys accepted; admin/revoke rows unchanged. Add bullets on endpoint host pinning (https, same host as issuer, no redirects, 512 KiB cap) and on 'no IdP access/refresh token is kept'. Put them under, or cross-reference them from, the OAuth 2.1 section.
- sdkCandidate: true

### R2 RT-005
- severity: medium
- file: harness/workflows/wave-cycle.js
- description: Mirror propagation per LRN-071/LRN-085 is not done. template/.claude/workflows/wave-cycle.js and template/.claude/skills/setup/SKILL.md carry the GH-152-E edits only as uncommitted working-tree changes in the template repo: `git -C template status` shows them modified, and template HEAD is ce6dbb5. The plan-redteam annotation required an explicit commit + push of only this wave's hunks, or a closing note naming the unpropagated files. Neither exists. The template working-tree wave-cycle.js also differs heavily from template HEAD (for example, the 'mutex' wording from 1eb744e is gone), so a blind `git add` would ship unrelated changes.
- fix: Stage only the GH-152 hunks with `git -C template add -p` (the AUTH_SURFACE 'src/auth/oidc' member and the setup-skill Entra section), then commit and push to wailuen/a2a-agent-template. Or, if blocked, write the closing note naming both files and the `diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js` check as an open deliverable.
- sdkCandidate: true

### R2 RT-006
- severity: low
- file: agent_sdk/routes/oauth.py
- description: 'Off = byte-identical' is not strictly true. /oauth/idp/callback and /oauth/idp/consent are always mounted on the module-level router (lines 746, 778). Probed with IdP off: GET /oauth/idp/consent and POST /oauth/idp/callback return 405 (not 404), and `unauth_rate_limit` runs before `_require_idp`, so each probe of the dead routes uses up the caller's per-IP unauth budget (limiter=1 → [404, 429, 429]).
- fix: Put the two IdP routes on a separate `idp_router` that build_app() includes only when oauth_idp=oidc. Then off mode is a true unknown-route 404 with no limiter charge. Extend test_idp_off_idp_routes_404 to cover the other methods and a limiter-unchanged assertion.
- sdkCandidate: true

### R2 RT-007
- severity: low
- file: agent_sdk/routes/oauth.py
- description: The browser-binding cookie lifecycle is incomplete. (a) The callback does not re-issue `__Host-agent_sdk_idp`, so a callback landing near the 600 s cookie Max-Age leaves the 300 s consent ticket unusable: the cookie expires, and Allow gives 'invalid or expired'. (b) The cookie is never cleared after consent, deny or error. (c) A second authorize in the same browser overwrites the cookie, and IdpFlowStore burns the first flow on mismatch, so two concurrent sign-ins (two connectors, or a retried popup) make the earlier one fail with a generic page.
- fix: On a successful callback, re-set the cookie with Max-Age equal to the consent TTL. On consent completion and on every terminal error redirect, delete the cookie. Either key the cookie name by a flow-id suffix, or document the one-flow-per-browser limit in DESIGN.md §5.5.
- sdkCandidate: true

### R2 RT-008
- severity: low
- file: agent_sdk/app.py
- description: _validate_idp_settings (line 498) does not refuse oauth_idp=oidc when the public base URL is plain http on a non-loopback host. The `__Host-` cookie requires Secure, so browsers drop it on such an origin. Every callback then fails with the generic 'invalid or expired' page and nothing is logged, a silent misconfiguration.
- fix: In _validate_idp_settings, refuse (or at least WARN, naming AGENT_SDK_PUBLIC_URL) when resolved_base_url is not https, unless the host is localhost/127.0.0.1/::1. Add a boot test.
- sdkCandidate: true

### R2 RT-009
- severity: low
- file: agent_sdk/routes/oauth.py
- description: There are now two code paths for the IdP secret, and the redirect builder is duplicated. `_federate` (line 665) decrypts the client secret straight from app.state.credential_store just to test whether it exists, separate from the RP's injected secret_provider. `_redirect_with` (line 647) repeats the body of `_error_redirect` and the inline one-time-consent redirect. Consent deny answers a POST with 302 via `_error_redirect`, while allow uses 303.
- fix: Add `OidcRelyingParty.has_secret()`, which calls its own secret_provider, and use it in `_federate`; drop the NS_OAUTH_IDP import from routes. Make `_error_redirect` call `_redirect_with(..., 302)`, and reuse `_redirect_with` in the one-time-consent path. Use 303 for the consent-deny redirect.
- sdkCandidate: true

### R2 RT-010
- severity: low
- file: CHANGELOG.md
- description: The [Unreleased] entries are mislabelled and the note is wrong. Line 11 attributes the federated routes to 'GH-152-B/C'; they are GH-152-D. Line 15 attributes the API-key switch to 'GH-152-D'; it is GH-152-C. The new '### Added' heading was inserted above w041's existing GH-151 and Profile v1.1 paragraphs, which re-categorises them. The rewritten reconciliation note (line 33) says GH-152 is 'the only work sitting ahead of [0.8.0]', which is false because GH-151 and the Profile v1.1 amendment are also unreleased.
- fix: Fix the sub-todo labels. Keep w041's entries outside, or under their own heading, below the GH-152 '### Added' block. Reword the note to list all unreleased work, or drop the claim.
- sdkCandidate: true

### R2 RT-011
- severity: low
- file: harness/skills/setup/SKILL.md
- description: The new Entra section (line 78) leaves out parts of the AC and practical setup. It never mentions AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS or its effect: user API-key clients break, while admin-key console chat, /acceptance and /agent-verify keep working per the D3 ruling. It has no restart step after setting the env vars and storing the secret. It does not say PUBLIC_URL must be https for the redirect URI and the __Host- cookie. The template copy is identical, so it has the same gaps.
- fix: Add a step for the optional AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS setting and its effects, an explicit 'restart the agent' step, and an https PUBLIC_URL requirement. Mirror the change to template/.claude/skills/setup/SKILL.md.
- sdkCandidate: true

### R2 RT-012
- severity: low
- file: DESIGN.md
- description: The DESIGN.md module tree (auth/ block, around lines 106-110) still lists only middleware.py, api_keys.py, oauth_tokens.py and usage.py. The new agent_sdk/auth/oidc.py, the OIDC relying party and IdP flow store, and identity.py are missing, so the layout section drifts from the code that §5.5's new addendum describes.
- fix: Add `oidc.py  # OIDC relying party (discovery/JWKS, ID-token validation) + IdpFlowStore (ADR-003)` and identity.py to the auth/ tree.
- sdkCandidate: true

### R2 RT-013
- severity: low
- file: harness/workflows/wave-cycle.js
- description: This group's Modifies set for the three workflow mirrors carries a working-tree diff of about 1,000 lines, versus the single AUTH_SURFACE member the AC asks for. The diff includes rewritten `meta.description` and Unit Redteam phase text (lines 3, 8) that no longer mention concurrent unit redteam with mutex-serialised fix/gate or the single-group phase skip. The code still runs groups concurrently (lines 1453-1485), so the user-visible phase description is now wrong about runtime behaviour.
- fix: Restore the meta description and phase detail strings to match the concurrent Unit Redteam code in all three mirrors, or split the unrelated reconciliation diff out of this wave's change set so the GH-152-E diff is only the AUTH_SURFACE member and its test pin.
- sdkCandidate: true

### R3 RT-002
- severity: medium
- file: tests/test_gh152_idp_authorize_flow.py
- description: test_idp_on_discovery_documents_unchanged is tautological. It builds the expected PRM 'resource' from the actual response's own host, and it checks for 'login.example.com', a host the fixture never uses (the issuer is login.microsoftonline.com). It never compares the IdP-on documents to the IdP-off golden hashes. It also never checks the 401 + WWW-Authenticate challenge or the CORS preflight, which the AC names explicitly. A live probe shows the behaviour is correct today (401 with resource_metadata, preflight 204), but nothing pins it.
- fix: Assert the IdP-on PRM/bare PRM/AS-metadata bodies hash to the GOLDEN_METADATA values in test_gh152_idp_off_regression.py (same default PUBLIC_URL). Add assertions that POST /mcp without a Bearer returns 401 with the same WWW-Authenticate as IdP-off, and that OPTIONS /mcp preflight returns 204 with Expose-Headers including WWW-Authenticate.
- sdkCandidate: true

### R3 RT-003
- severity: medium
- file: tests/test_gh152_idp_off_regression.py
- description: The 'Off = byte-identical' AC requires POST approve, token, refresh and revoke responses to equal today's. The regression file byte-pins only the GET consent page and the three discovery documents. Approve/token are checked for status and user-is-None only. Refresh and revoke are not exercised at all. The /oauth/token label change (meta.get('label') or client_name) and the new rotate_refresh branches could change IdP-off output without a failing test.
- fix: Add golden captures (with token/code values normalised) for the POST /oauth/authorize 303 Location shape and headers, the /oauth/token code and refresh JSON key sets and headers, and the /oauth/revoke 200 body. Also assert that the persisted refresh record's key set under IdP-off equals the pre-GH-152 set.
- sdkCandidate: true

### R3 RT-004
- severity: medium
- file: docs/security.md
- description: GH-152-E ACs are only partly met. The surface table has no API-key-switch column (only a bullet was added). The IdP section does not mention endpoint host pinning (discovery endpoints must be https on the issuer host, Google unsupported). The '/oauth/revoke | oauth callers for their own tokens only' row is stale: under ADR-003 D5 an oauth caller may revoke only tokens whose client_id AND user both match its own.
- fix: Add a column to the surface table showing which rows reject non-admin API keys when AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true. Add a bullet on issuer-host pinning, the redirect refusal and the 512 KiB/10 s client limits. Reword the /oauth/revoke row to 'same client_id and same user'.
- sdkCandidate: true

### R3 RT-005
- severity: medium
- file: harness/workflows/wave-cycle.js
- description: GH-152-E's Modifies paths carry about 1,100 added and 270 removed lines per wave-cycle.js mirror (and ~1,000/220 in sdk-wave.js). These include GH-131 args normalisation and RT-001/RT-004 schema changes, none of them part of the one-line AUTH_SURFACE change this todo owns, and none named in the GH-152 CHANGELOG entry. In the process the wave-cycle.js meta.description and the 'Unit Redteam'/'Phase Redteam' phase details in all three mirrors (.claude/, harness/, template/) went back to text that no longer mentions concurrent Unit Redteam groups, the mutex-serialised fix+gate step, or the single-group Phase Redteam skip. The code still does all three (lines ~1464 and ~1507), and sdk-wave.js's meta still describes them. The tests/test_workflows.py gh132 assertion was also relaxed to accept the lrnBatches form, which is unrelated to GH-152.
- fix: Split the unrelated merge-restoration changes into their own commit with their own CHANGELOG line, so the GH-152-E commit holds only the AUTH_SURFACE additions and the parity-test members. Restore HEAD's meta.description and Unit/Phase Redteam detail strings in all three wave-cycle.js mirrors so they match the concurrent and single-group-skip code paths. Keep the three mirrors byte-identical.
- codify: When a wave's Modifies paths already have uncommitted changes from another lineage, the wave commit absorbs them silently; diff against HEAD and isolate foreign hunks before signing off.
- sdkCandidate: true

### R3 RT-006
- severity: medium
- file: template/.claude/workflows/wave-cycle.js
- description: The todo annotation (LRN-071/LRN-085) requires the template peer-repo copies (template/.claude/workflows/wave-cycle.js and template/.claude/skills/setup/SKILL.md) to be committed and pushed to wailuen/a2a-agent-template as an explicit final step. Both are still uncommitted in template/: git -C template status shows ' M' for both, and the last template commit is ce6dbb5, unrelated to GH-152. Agent repos seeded from the template therefore lack src/auth/oidc in AUTH_SURFACE and the Entra setup steps.
- fix: In template/, stage only .claude/workflows/wave-cycle.js and .claude/skills/setup/SKILL.md, then commit and push them. Leave the other pre-existing uncommitted template edits alone. If pushing is blocked, name both files and the diff command in the wave closing note as an open deliverable.
- sdkCandidate: true

### R3 RT-007
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: There is one browser-binding cookie name (__Host-agent_sdk_idp) for every flow. A second GET /oauth/authorize in the same browser before the first completes overwrites the cookie, so the first flow's /oauth/idp/callback fails with a 400 'invalid or expired' page and the flow is burned. A live probe confirmed it: callback(q1, cookie2) returns 400. This happens on a connector retry, a double-click on Connect, or two connectors authorizing at once. The cookie is also never cleared after consent completes (no Set-Cookie on the consent 303).
- fix: Bind per flow: either name the cookie per flow (e.g. __Host-agent_sdk_idp_<first 8 chars of sha256(state)>) or keep a small bounded list of bindings in one cookie value and accept any match. Send a deleting Set-Cookie (Max-Age=0) on the consent redirect and on the callback error paths.
- sdkCandidate: true

### R3 RT-008
- severity: medium
- file: agent_sdk/app.py
- description: app.py wires IdpFlowStore() with its default global 1,000-entry LRU that evicts the oldest entry. Unauthenticated GET /oauth/authorize mints one flow per request, limited only per IP. A handful of IPs at the unauth rate limit can therefore push out every legitimate in-flight flow inside the 10-minute TTL. Any real user mid-sign-in then gets a 400 at callback, a cheap denial of sign-in.
- fix: Cap flows per client IP (or per client_id) inside IdpFlowStore. Make a full store refuse new flows with a temporarily_unavailable redirect instead of evicting live entries, or at least evict per-IP first. Add a test that floods from one IP and checks that another IP's flow survives.
- sdkCandidate: true

### R3 RT-009
- severity: low
- file: CHANGELOG.md
- description: The [Unreleased] GH-152 entries mislabel the todos: the federated authorize/callback/consent routes are tagged 'GH-152-B/C' (they are GH-152-D), and the API-key switch is tagged 'GH-152-D' (it is GH-152-C). The new '### Added' heading was put above w041's GH-151 and 'Profile v1.1 metadata amendment' paragraphs, so they now sit under 'Added' too. The reconciliation note was rewritten to say GH-152 is 'the only work sitting ahead of [0.8.0]', which is false because GH-151 and the Profile v1.1 change are also under [Unreleased].
- fix: Fix the todo labels. Put w041's entries under their own heading (or move the GH-152 '### Added' block after them). Reword the reconciliation note to 'GH-152, GH-151 and the Profile v1.1 amendment under [Unreleased] are the work ahead of [0.8.0]'.
- sdkCandidate: true

### R3 RT-010
- severity: low
- file: harness/skills/setup/SKILL.md
- description: The new Entra section never mentions AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS. The ratified behaviour is that only user keys are rejected, admin keys still work, and a holder of the admin key can call protocol routes without signing in. The GH-152-E AC requires the setup skill to state the switch's effect. The section also has no explicit 'restart the agent' step after the .env change, and no step to set the secret once the agent is up (it says to keep the value for later but not when to enter it).
- fix: Add a step covering the optional DISABLE_API_KEYS switch and the admin-key trade-off. Add 'restart, then enter the client secret in /admin → Credentials → __oauth_idp__' as an explicit ordered step. Mirror the change byte-identically into template/.claude/skills/setup/SKILL.md.
- sdkCandidate: true

### R3 RT-011
- severity: low
- file: agent_sdk/routes/oauth.py
- description: The module docstring is stale. It still says 'Approval requires a REAL admin API key' and lists only the pre-GH-152 routes, without /oauth/idp/callback, /oauth/idp/consent, or the POST /oauth/authorize disable under IdP. The section header 'Authorization endpoint — consent gated on a real admin API key' is also stale. DESIGN.md's §3 module tree has no auth/oidc.py entry.
- fix: Update the module docstring and the section header to describe both approval modes and the two IdP routes. Add 'oidc.py  # OIDC relying party + IdP flow store (C-023, ADR-003)' under auth/ in DESIGN.md's tree.
- sdkCandidate: true

### R3 RT-012
- severity: low
- file: agent_sdk/routes/oauth.py
- description: _federate reads the IdP secret straight from request.app.state.credential_store, while OidcRelyingParty has its own secret_provider closure, so 'secret present' has two sources of truth that can drift (e.g. if the provider changes namespace). app.py also guards a runtime invariant with a bare `assert settings.oauth_idp_issuer and settings.oauth_idp_client_id`, which python -O strips. The consent page shows the redirect host only as inline <code> after the attacker-controllable DCR client_name, not 'prominently' as ADR-003 D9 requires.
- fix: Add OidcRelyingParty.has_secret() that uses the same secret_provider, and call it from _federate. Replace the assert with an explicit check that raises. Render the redirect host as its own prominent line (e.g. 'You will be sent to: <host>') above the Allow/Deny buttons.
- sdkCandidate: true

### R4 RT-002
- severity: medium
- file: agent_sdk/app.py
- description: [SDK] The app passes OidcConfig.issuer as the raw setting, but tenant_id is the lowercased GUID from parse_idp_issuer. Discovery and ID-token checks compare the issuer exactly. Two configs pass boot but then fail every sign-in with no explanation. (1) An uppercase tenant GUID: Entra returns a lowercase issuer, so the match fails. (2) An issuer on login.windows.net, which _ENTRA_LOGIN_HOSTS accepts: Entra discovery very likely reports login.microsoftonline.com as the issuer. Every /oauth/authorize then returns temporarily_unavailable forever.
- fix: Have the config parser return a canonical issuer (lowercase GUID, canonical login host) and pass that into OidcConfig. Or refuse at boot any issuer that is not already canonical: an uppercase GUID, or the login.windows.net alias. Add a boot test for each case.
- sdkCandidate: true

### R4 RT-003
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: [SDK] The callback and consent routes never log why a sign-in failed. On IdpDenied the callback logs only the client_id. It drops exc.reason_code, a fixed constant such as missing_role, bad_tid, group_overage or unknown_kid. IdpUnavailable from a discovery problem (issuer mismatch, endpoint on another host, non-200 reply) is not logged anywhere. An operator cannot tell a missing app role from a wrong tenant or a bad issuer setting.
- fix: Log exc.reason_code at INFO on IdpDenied; it is a fixed constant, so it is safe under SI-2. In oidc.py, log a fixed reason constant at WARNING for each discovery check that fails. Never interpolate values into these messages.
- sdkCandidate: true

### R4 RT-004
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: [SDK] Every flow uses the same cookie name, __Host-agent_sdk_idp. A second authorize in the same browser overwrites the first flow's cookie. This happens with a double-clicked Connect, two connectors, or a retry. When the first flow's callback arrives, IdpFlowStore._take pops and burns that flow on the mismatch, and the user sees 'link is invalid or has expired'. The cookie is also never cleared after consent finishes.
- fix: Name the cookie per flow, for example __Host-agent_sdk_idp-<first 16 hex chars of sha256(state)>. The callback can work out the name from state, and consent can work it out from a value stored on the ticket. Delete the cookie (Max-Age=0) on the consent response and on every terminal callback response. Add a test with two flows in parallel in one browser.
- sdkCandidate: true

### R4 RT-005
- severity: medium
- file: harness/skills/setup/SKILL.md
- description: [SDK] The setup skill only partly meets the GH-152-E AC. The Phase 0 Entra block says 'In .env (Phase 3)', but Phase 3's list of vars to write (around line 297) has no AGENT_SDK_OAUTH_IDP* entries. An agent following Phase 3 to the letter will never write them. No step after first boot stores __oauth_idp__/client_secret through the Credentials card or API. The block also does not mention the restart, or what AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS does (user keys are rejected, admin keys still work).
- fix: Add the IdP vars to Phase 3's .env list, guarded by 'if Entra sign-in was chosen'. Add a post-bootstrap step that stores the client secret in __oauth_idp__/client_secret, next to the __model__ seeding step. Add a restart line and one line on the API-key switch. Apply the same text to template/.claude/skills/setup/SKILL.md.
- sdkCandidate: true

### R4 RT-006
- severity: medium
- file: harness/workflows/wave-cycle.js
- description: [SDK] The mirror edits in template/.claude/workflows/wave-cycle.js and template/.claude/skills/setup/SKILL.md are uncommitted and unpushed in the template peer repo. They are mixed in with about 1,300 lines of older uncommitted changes in the same two files. The todo's annotation (LRN-071/LRN-085) requires a commit and push of only this wave's hunks, or a closing note that names the files left unpropagated. Neither exists yet.
- fix: Use git -C template add -p to stage only the src/auth/oidc AUTH_SURFACE line and the Entra setup block, then commit and push. If that is blocked by the older edits, write both paths and the diff check (diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js) into the wave closing note as an open deliverable.
- sdkCandidate: true

### R4 RT-007
- severity: low
- file: docs/security.md
- description: [SDK] docs/security.md only partly meets the GH-152-E AC. The surface table has no API-key switch column; the switch is covered only in a bullet. The IdP section never mentions that endpoints are pinned to the issuer host or that Google is unsupported in v1. The /oauth/revoke row still says 'own tokens' without saying that under IdP an oauth caller's user must also match.
- fix: Add the API-key-switch column (or a matching row annotation) to the surface table. Add a host-pinning bullet saying non-issuer-host JWKS (Google) fails closed. Update the /oauth/revoke row to say the client_id and the user must both match.
- sdkCandidate: true

### R4 RT-008
- severity: low
- file: CHANGELOG.md
- description: [SDK] The [Unreleased] entries carry the wrong todo labels. The federated routes are tagged GH-152-B/C but belong to GH-152-D. The API-key switch is tagged GH-152-D but belongs to GH-152-C. GH-152 is described twice (bullets plus the GH-152-A paragraph). The GH-151 mirror re-sync and the Profile v1.1 paragraphs sit under '### Added' even though neither adds anything.
- fix: Relabel: routes and wiring = GH-152-D, Identity.user / session cap / API-key switch = GH-152-C. Merge the duplicate GH-152 text. Move the GH-151 and Profile v1.1 paragraphs under ### Changed (or a 'Docs/tests' heading).
- sdkCandidate: true

### R4 RT-009
- severity: low
- file: tests/test_gh152_idp_no_secret_leak.py
- description: [SDK] test_no_idp_secrets_in_logs_or_responses does not drive every failure path, though the SI-2 AC says it must. It never covers IdpUnavailable at the code exchange, consent deny, consent ticket replay or cookie mismatch, or the disabled POST /oauth/authorize. The Collector also reads record.exc_text, which stays None until a formatter runs. So a future logger.exception or exc_info=True that leaks a token in a traceback would not be caught.
- fix: Add the missing paths to the sentinel run. In Collector.emit, format exc_info with logging.Formatter().formatException(record.exc_info) when it is set, and scan that text too.
- sdkCandidate: true

### R4 RT-010
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] There is duplicated and stale code. _redirect_with copies the URL-building and security-header logic of _error_redirect and of the admin-approve redirect. _pkce_pair re-implements the S256 computation that auth/oauth_tokens.py already owns. The module docstring and the oauth_authorize_page docstring still say approval always needs an admin API key and do not list /oauth/idp/*. DESIGN.md's auth/ module tree omits oidc.py and identity.py.
- fix: Make _error_redirect call the shared _redirect_with(…, 302). Expose an s256_challenge helper from oauth_tokens and use it in _pkce_pair. Update both docstrings and the DESIGN.md auth/ tree.
- sdkCandidate: true

### R4 RT-011
- severity: low
- file: agent_sdk/app.py
- description: [SDK] The IdP wiring in build_app() uses a bare 'assert settings.oauth_idp_issuer and settings.oauth_idp_client_id'. Python drops asserts when run with -O, so the guard silently disappears in an optimised build.
- fix: Bind local str variables after _validate_idp_settings() (or have it return them), so the type checker can narrow without an assert. Or raise ValueError explicitly.
- sdkCandidate: true

### R4 RT-012
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] With AGENT_SDK_OAUTH_IDP=none the two IdP routes are still registered, so the off mode is not fully unchanged. /openapi.json now lists /oauth/idp/callback and /oauth/idp/consent. GET /oauth/idp/consent and POST /oauth/idp/callback return 405, not 404. Hits on these dead routes still count against the per-IP unauthenticated rate limit.
- fix: Set include_in_schema=False on both routes, or mount them only when the IdP is on (for example a separate router included from build_app when oauth_idp=oidc). Add an IdP-off assertion that /openapi.json is unchanged.
- sdkCandidate: true

### R5 RT-002
- severity: medium
- file: agent_sdk/app.py
- description: [SDK] The ADR-003 D2 warning for the unsupported AGENT_SDK_OAUTH_IDP_SURFACES setting checks only `os.environ` (app.py:522). BaseAgentSettings loads `.env` through pydantic-settings with extra="ignore", and that loader does not copy values into os.environ. So an operator who puts the variable in `.env` (the location the setup skill tells them to use) gets no warning, and the variable is silently ignored. The test only uses monkeypatch.setenv, so it misses this path.
- fix: Detect the key from both sources: os.environ and the parsed dotenv file (for example `dotenv_values(settings.model_config['env_file'])`, or a declared `oauth_idp_surfaces: str | None` settings field used only to trigger the warning). Add a test that writes the key to a tmp `.env` file and asserts exactly one WARNING.

### R5 RT-003
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: [SDK] Every federated authorize uses one fixed cookie name (`__Host-agent_sdk_idp`, line 93). `_federate` overwrites it on each call. When one browser has two authorize flows open (two connectors, a retried popup, or Claude.ai re-opening authorize), the later Set-Cookie replaces the earlier binding. The first flow's callback then fails `flows.pop(state, cookie)` and the user lands on the dead-end 400 page 'This sign-in link is invalid or has expired'. No test covers two concurrent flows.
- fix: Key the cookie per flow, for example `__Host-agent_sdk_idp_<first 16 chars of sha256(state)>`, or store a small set of bindings in one cookie. Look up the binding at callback and consent by the flow's state. Add `test_two_concurrent_flows_same_browser_both_complete`.

### R5 RT-004
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: [SDK] Anyone can make `_federate` insert a server-side flow: DCR is open and GET /oauth/authorize is unauthenticated. The flows sit in IdpFlowStore's 1,000-entry LRU with a 600 s TTL. At the default unauth limit of 30/min per IP, about 4 source IPs can keep the table full and evict every real user's in-flight flow before they return from Entra. Those users see the 400 'invalid or expired' page, so attackers can block sign-in for the whole tenant.
- fix: Bound flows per client IP or per client_id inside IdpFlowStore. Alternatively, make the authorize leg stateless: put the flow in an HMAC- or AES-GCM-sealed `state` value tied to the cookie, and keep only a single-use nonce set. At minimum, add a test proving one IP cannot evict another IP's flows, and document the limit.

### R5 RT-005
- severity: medium
- file: harness/skills/setup/SKILL.md
- description: [SDK] The Entra section of the setup skill is missing two items the GH-152-E acceptance criteria require. First, there is no restart step after setting the client secret in the admin Credentials card. Second, AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS is not mentioned at all: not its existence, not that it rejects user keys only, and not that admin keys (console chat, /acceptance, /agent-verify) keep working. Separately, the AC text and ADR-003's Consequences line ('With the API-key switch on, console chat and protocol-level harness probes need it off') contradict the D3 maintainer ruling that admin keys stay accepted. The docs are therefore internally inconsistent about what the switch breaks.
- fix: Add a restart step and a line on the API-key switch to both harness/skills/setup/SKILL.md and template/.claude/skills/setup/SKILL.md, kept identical. The line should say the switch rejects non-admin keys only, admin keys still work, and the admin key should therefore be protected. Fix ADR-003's Consequences bullet to match D3.

### R5 RT-006
- severity: medium
- file: docs/security.md
- description: [SDK] Two GH-152-E acceptance criteria for docs/security.md are not met. (1) The surface table has no API-key-switch column. The switch behaviour only appears as a bullet in the new section, so the per-surface table still does not show which routes reject user keys under the switch. (2) Issuer-host pinning is not described: discovery, token and JWKS endpoints must be https on the issuer host, and Google and other split-host IdPs fail closed in v1. Operators trying Google will get only 'temporarily_unavailable' with no documented reason.
- fix: Add a column such as 'With AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS' to the Identities and surfaces table (A2A, AG-UI and /mcp: user keys rejected, admin keys accepted; admin, revoke, token and register unchanged). Add a host-pinning bullet to the 'Optional IdP sign-in' section.

### R5 RT-007
- severity: medium
- file: tests/test_gh152_idp_off_regression.py
- description: [SDK] The off=byte-identical AC requires that, with AGENT_SDK_OAUTH_IDP=none, POST approve, token, refresh and revoke responses equal today's. The regression file golden-pins only the GET consent page and the three metadata documents. test_idp_off_admin_key_approve_and_token_have_no_user checks status codes and `user is None` only, and refresh and revoke are not exercised at all. Separately, test_admin_key_consent_disabled_under_idp checks only status 400 and no Location header. It never asserts that no code was minted or that `mark_consented` was not called, so a regression that verifies the key and mints a code before returning 400 would still pass.
- fix: Capture normalized golden hashes (token values masked) for the approve 303 headers, the token and refresh JSON key sets and headers, and the revoke response with IdP off. In the IdP-on POST test, assert that `store.get_client(cid)['consented']` stays False and that no code record exists.

### R5 RT-008
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] With IdP off, /oauth/idp/callback and /oauth/idp/consent are still mounted and only raise 404 inside the handler. As a result, `Depends(unauth_rate_limit)` runs first and charges the caller's unauth budget (a 429 can come back where an unrouted path gives 404). Other methods also return 405 instead of 404: POST to the callback and GET to consent. So the off state is not byte-identical to an unrouted path, and the 405 reveals that the feature exists.
- fix: Mount the two routes only when IdP is enabled, for example via a separate `idp_router` that build_app includes when `oauth_idp == 'oidc'`. Alternatively, run the `_require_idp` 404 check as a dependency ahead of the rate limiter. Extend test_idp_off_idp_routes_404 to cover the cross-method requests.

### R5 RT-009
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] The SI-2 AC says the IdP authorization code and flow state never appear in logs. However, the IdP returns both in the /oauth/idp/callback query string (response_mode=query), and the standard uvicorn access log records the full path with that query. test_no_idp_secrets_in_logs_or_responses only attaches to the `agent_sdk` logger, so it cannot see this. The code is single-use and needs the client secret plus the PKCE verifier to redeem, so the impact is low, but the documented guarantee is wrong.
- fix: Either document that the access log carries the callback query and advise operators to filter it, or add a small logging filter on `uvicorn.access` that strips the query from /oauth/idp/callback. Narrow the AC wording to the SDK's own loggers.

### R5 RT-010
- severity: low
- file: CHANGELOG.md
- description: [SDK] The [Unreleased] entries mislabel the todo IDs: the federated routes are tagged 'GH-152-B/C' (they are GH-152-D), and the API-key switch is tagged 'GH-152-D' (it is GH-152-C). The new `### Added` heading now also sits above w041's GH-151 and Profile v1.1 paragraphs, re-filing them under Added. And the edited reconciliation note says GH-152 'is the only work sitting ahead of [0.8.0]', which is false because w041's entries are also unreleased.
- fix: Correct the todo IDs. Put the GH-152 bullets under their own `### Added` heading without capturing w041's paragraphs, or give those paragraphs their own headings. Change the reconciliation note to say both w041 and w042 work sits ahead of [0.8.0].

### R5 RT-011
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] Several docs are stale. The oauth.py module docstring (lines 1-37) still says 'The security gate is the admin-gated /authorize' and lists neither /oauth/idp/callback nor /oauth/idp/consent. The oauth_authorize_page docstring does not mention the federation branch. The DESIGN.md §3 package tree under `auth/` does not list the new `oidc.py` (component C-023).
- fix: Add the two IdP routes and the federation branch to the module docstring and to the authorize-page docstring. Add `oidc.py  # OIDC relying party + IdpFlowStore (GH-152, opt-in)` to the DESIGN.md auth/ tree.

### R5 RT-012
- severity: low
- file: agent_sdk/routes/oauth.py
- description: [SDK] The new code duplicates existing logic and has two sources of truth. `_pkce_pair` (line 641) re-implements the S256 base64url-of-sha256 computation that `oauth_tokens.verify_pkce_s256` already contains. `_redirect_with` (line 647) duplicates the redirect-building block that `_error_redirect`, the approve path and the one-time-consent path each spell inline. `_federate` reads the client secret directly from `app.state.credential_store`, separate from the `OidcRelyingParty` secret_provider lambda, so the two checks can drift apart. app.py:789 also uses a bare `assert` for issuer and client_id in production code; `python -O` strips it.
- fix: Extract an `s256_challenge(verifier)` helper in oauth_tokens and use it in both places. Have `_error_redirect` call `_redirect_with`. Expose `rp.has_secret()` that uses the same provider. Replace the assert with an explicit type-narrowing `if` that raises.
