# w068 — group G5 deferred medium/low findings

- Wave: w068
- Scope: unit:G5
- Date: 2026-10-25

> Non-blocking — these did not block w068's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — agent_sdk/routes/oauth.py:1203
Quote: `raise _rate_limited()`
- Description: The failed-bearer 429 on POST /oauth/revoke has Retry-After but no WWW-Authenticate invalid_token challenge. The revoke 401 three lines below carries that challenge. Ruling item 1 says revoke returns 'the same 429', and docs/protocols.md:175-178 places 'When that window is spent, the 429 carries ... the same Bearer error="invalid_token" challenge' right after the revoke sentence. A client with a dead token that hits a spent limiter on revoke gets a bare 429, which is the GH-272 defect on one more route.
- Fix: Raise the limiter 429 with the challenge the revoke 401 already uses, built by C-099 _prm_challenge(runtime.prm_url, invalid_token=True). One way: give _bearer_rate_limited an optional prm argument and call it here. The _a2a_auth_envelope OAuth 429 branch already copies exc.headers, so the JSON body, Retry-After and no-store stay. In test_revoke_bad_bearer_counts_and_429s, assert r.headers['www-authenticate'].startswith(INVALID). If revoke is meant to stay bare, change docs/protocols.md so it says the challenge is only on /v1, /ag-ui and /mcp.
- Codify: When a ruling says a second call site returns 'the same' error response, reuse the same builder at that site and assert every header, not just the status.
- SDK candidate: yes

## RT-002 (medium) — tests/test_gh152_api_key_optout.py:116
Quote: `assert (await _call(app, "GET", "/v1/tasks", user_key)).status_code == 429`
- Description: The todo lists tests/test_gh152_api_key_optout.py under Modifies, issue item 4 names this exact line as status-only, and the CHANGELOG GH-272 entry lists the file under Tests. The file is unchanged. So the second changed call site, the refused-key branch of require_identity (agent_sdk/auth/middleware.py:174-175, raise _bearer_rate_limited), has no test for its WWW-Authenticate challenge, Retry-After or key absence. The test name still says 'unauth_limiter' although it drains bearer_limiter.
- Fix: Rename the test to test_switch_rejections_count_against_bearer_limiter. On the 429, assert retry-after == '60', that www-authenticate starts with 'Bearer error="invalid_token", resource_metadata="', and that user_key is in neither r.text nor the headers. Or remove the file from the CHANGELOG Tests list and the todo Modifies list, and add the same assertions in tests/test_gh260_rate_limit.py.
- Codify: Every call site changed by a fix needs its own test with full header assertions, and a CHANGELOG Tests list must name only files the wave actually changed.
- SDK candidate: yes

## RT-003 (medium) — tests/test_gh260_rate_limit.py:224
Quote: `assert BAD not in r.text and BAD not in str(dict(r.headers))`
- Description: The SI-2 AC requires a test on /v1, /ag-ui/run, /mcp and /oauth/revoke showing that the presented bearer, its prefix and client_id never appear in header, body or log. The new GH-272 tests check only the full token against body and headers. No test uses caplog, and none checks redact.key_prefix(BAD) or the client_id, which LRN-209 calls for.
- Fix: Add the caplog fixture (at DEBUG level) to test_bearer_429_carries_invalid_token_challenge, test_expired_token_429_carries_challenge and test_revoke_bad_bearer_counts_and_429s. Assert that BAD and redact.key_prefix(BAD) appear in neither caplog.text, r.text nor the headers. For the expired case, also assert that the minted pair's client_id is absent.
- Codify: An SI-2 redaction AC must have tests that check logs (caplog) and the key prefix as well as the response body and headers.
- SDK candidate: yes

## RT-004 (medium) — agent_sdk/auth/middleware.py:201
Quote: `use ``bearer_limiter`` instead (GH-265)."""`
- Description: The new docstring says failed bearers use bearer_limiter 'instead'. docs/protocols.md:174-175 says the two windows are separate 'so one cannot drain the other'. Both are false for /oauth/revoke. That route still has Depends(unauth_rate_limit), so a bad-bearer revoke now counts in BOTH unauth_limiter and bearer_limiter. A flood of bad-bearer revokes from a shared Claude.ai IP drains the OAuth bucket and blocks /oauth/token refresh. That is the cross-drain GH-265 was meant to stop, and the refreshed docs now hide it.
- Fix: Choose one. (a) Stop counting a bearer-carrying revoke in unauth_limiter: drop the route dependency, call unauth_rate_limit(request) only on the client_id path, and keep bearer_limiter on the bad-bearer path. Add a test that a drained bearer_limiter plus bad-bearer revokes does not 429 /oauth/token. Or (b) state the double count plainly in this docstring, DESIGN.md:447 and docs/protocols.md:174-176, and remove 'instead' and 'cannot drain'.
- Codify: When a request moves into a new rate-limit bucket, check that it has also left the old route-level dependency, or document that it counts in both.
- SDK candidate: yes

## RT-005 (low) — tests/test_gh260_rate_limit.py:147
Quote: `async def test_non_oauth_429_unchanged(app):`
- Description: _bearer_rate_limited is raised from _resolve_identity, so every require_identity, require_api_key_identity and require_admin route (/admin/*, key management, /mcp/sse) now sends WWW-Authenticate on its failed-bearer 429. The CHANGELOG GH-272 line names only /v1, /ag-ui and /mcp. This test is still called 'unchanged' and checks only the body, so it hides the new admin header.
- Fix: Rename the test (for example test_admin_bearer_429_body_and_challenge), assert the new www-authenticate header and Retry-After, and change the CHANGELOG GH-272 line to say the challenge is on every bearer-protected route, /admin/* included.
- SDK candidate: yes

## RT-006 (low) — tests/test_gh260_rate_limit.py:215
Quote: `("POST", "/mcp", {"json": {}}, True),`
- Description: Ruling item 4 asks for a test of the POST /mcp 429 shape. The parametrized test checks status, Retry-After and the challenge, but not the /mcp 429 body. The expired-token case is tested only on /v1, and the 401 it gets before the limiter is spent is checked for status only, not for the invalid_token challenge (SI-5 AC: expired bearers still 401 with resource_metadata).
- Fix: For the /mcp case, assert the exact 429 body (today {'detail': 'rate limit exceeded'}). In test_expired_token_429_carries_challenge, assert that the first response's www-authenticate starts with INVALID, and parametrize over /mcp so the MCP-suffixed PRM is checked.
- SDK candidate: yes

---

Autoloop cycle 4 (2026-10-26): critical/high-only filter. The 4 high candidates (sdk-candidates 2/4/5, G3 migration line) were re-verified at v0.25.0: all fixed or low. Nothing filed; loop finished.
