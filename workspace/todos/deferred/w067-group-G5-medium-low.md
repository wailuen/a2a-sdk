# w067 — group G5 deferred medium/low findings

- Wave: w067
- Scope: unit:G5
- Date: 2026-10-25

Non-blocking — these did not block w067's archive. Address opportunistically or fold into a future wave.

Findings are accumulated across every redteam round and deduped by file+description. Original RT ids repeat across rounds, so each entry has a D-NN id.

## Medium

### D-01 (RT-005) — agent_sdk/routes/oauth.py:1198
- Quote: `# Bad Bearer — reject; do NOT fall through to client_id path.`
- Issue: [SDK] The bad-Bearer 401 on /oauth/revoke never charges `bearer_limiter`; it counts only in the OAuth bucket. docs/protocols.md:171 ("Failed bearers count in their own per-IP window") is false for revoke, and the split raised the per-IP bearer-guessing budget to 30/min on /v1 plus 30/min on /oauth/revoke.
- Fix: In the bad-Bearer branch, check `runtime.bearer_limiter.allow(_client_key(request, runtime))` and raise `_rate_limited()` before the 401 (or reword docs to name revoke as the exception, with a ruling). Add a test that drains `bearer_limiter` and expects 429 on a bad-bearer revoke.

### D-02 (RT-006) — agent_sdk/auth/middleware.py:50
- Quote: `# GH-260: failed-bearer 401s count here, never in the OAuth-endpoint bucket.`
- Issue: [SDK] Ruling item (2) ("Update DESIGN.md §6 and the docstrings") only partly done. This comment, DESIGN.md:447 and the test docstring cite GH-260 for GH-265 work. Module docstring (middleware.py:8-9) is stale. `unauth_rate_limit` docstring (182-183) omits GET /oauth/authorize, /oauth/idp/callback, /oauth/idp/consent, /oauth/revoke and the bootstrap mint.
- Fix: GH-260 -> GH-265 in comment, DESIGN.md:447 and test docstring. Rewrite module docstring for two per-IP windows (failed bearers in `bearer_limiter`, OAuth + bootstrap in `unauth_limiter`, missing bearers uncounted). List all seven /oauth/ routes and bootstrap in `unauth_rate_limit` docstring.

### D-03 (RT-002) — agent_sdk/auth/middleware.py:8
- Quote: `Bearer is header-borne only. Two rate-limit layers: per-IP on every`
- Issue: [SDK] Module docstring still says per-IP limiting covers "every unauthenticated/failed attempt" (missing-bearer 401s are uncounted since GH-260; failed bearers have their own bucket) and that only "MCP surface" 401s carry the PRM challenge.
- Fix: Rewrite lines 8-10: per-IP failed-bearer window (`bearer_limiter`), separate per-IP window for /oauth/* (`unauth_limiter`), no count for missing bearer, per-identity after auth; every protected 401 carries the PRM challenge, with `error="invalid_token"` for a presented-but-bad bearer.
- Codify: When an issue lists stale docstrings by line, the fix is not done until each is rewritten; check them by grep in the redteam.
- sdkCandidate: true

### D-04 (RT-003) — agent_sdk/auth/middleware.py:183
- Quote: `(/oauth/register, /oauth/token, consent POST)."""`
- Issue: [SDK] `unauth_rate_limit` docstring not updated: the dependency guards all seven /oauth/* routes (register, token, revoke, GET+POST authorize, idp callback, idp consent) plus admin bootstrap at admin.py:266, and no longer counts failed bearers.
- Fix: List the real callers and state failed-bearer 401s count in `bearer_limiter`, not here.
- Codify: A limiter's docstring must list every route that depends on it; re-derive by grepping `Depends(<limiter>)` when the limiter is split.
- sdkCandidate: true

### D-05 (RT-004) — DESIGN.md:447
- Quote: `(2) **per-IP windows on all unauthenticated paths** (failed bearers in their own window, separate from /oauth/register, /oauth/token, consent; ... GH-260)`
- Issue: [SDK] §6 keeps the stale phrase, does not say a missing bearer is never counted (GH-260), lists only register/token/consent for the OAuth bucket, and cites GH-260 instead of GH-265.
- Fix: Replace with (2a) per-IP failed-bearer window (invalid, expired or refused; missing bearer never counted); (2b) separate per-IP window on every /oauth/* endpoint and the admin bootstrap; both sized by `AGENT_SDK_UNAUTH_RATE_LIMIT` (GH-265). Name all seven /oauth/* routes.
- Codify: A design sentence named stale in an issue must lose the stale phrase, not just gain a parenthetical.
- sdkCandidate: true

### D-06 (RT-005) — tests/test_gh260_rate_limit.py:75
- Quote: `async def test_invalid_and_missing_challenges(app):`
- Issue: [SDK] SI-5 AC requires 401 + resource_metadata for missing, invalid AND expired bearers on every protected route; no test sends an expired OAuth access token and /ag-ui/run is never checked.
- Fix: Mint an OAuth token pair via the token store, age it past expiry, assert the INVALID challenge on /v1/tasks, /mcp and /ag-ui/run, token absent from header and body.
- Codify: When an AC names several bearer states and surfaces, test each state on each surface.
- sdkCandidate: true

### D-07 (RT-006) — CHANGELOG.md:10
- Quote: GH-265 entry, `**Migration:** clients that matched the exact bare challenge string must accept the error="invalid_token" form.`
- Issue: [SDK] Migration covers only the challenge string. Missing: (a) the four browser OAuth routes' 429 changed from JSON to text/html; (b) code/tests that tune `app.state.auth.unauth_limiter` to throttle failed bearers now silently stop throttling them.
- Fix: Extend Migration: parse browser-route 429 by status + Retry-After, not JSON; code that tuned `unauth_limiter` for failed bearers must set `bearer_limiter`.
- Codify: A breaking entry's Migration line must cover every observable change, including content-type flips and moved runtime hooks.
- sdkCandidate: true

### D-08 (RT-001) — agent_sdk/auth/middleware.py:8 (and agent_sdk/routes/oauth.py:33-34)
- Quote: `Bearer is header-borne only. Two rate-limit layers: per-IP on every`
- Issue: Module docstring never names the separate failed-bearer bucket or the invalid_token challenge. oauth.py module docstring (line 34, "401s carry WWW-Authenticate pointing at the PRM") not updated either.
- Fix: Rewrite middleware.py:8-10 naming `identity_limiter`, `bearer_limiter`, `unauth_limiter` (/oauth/* + bootstrap); missing bearer never counted, bare challenge; invalid/expired/refused gets `error="invalid_token"`. Update oauth.py:33-34 likewise, adding the 429 split (HTML for four browser routes, JSON + no-store for register/token/revoke).
- Codify: When a ruling says "update the docstrings", check module and function docstrings of every touched file, not only DESIGN.md.
- sdkCandidate: true

### D-09 (RT-002) — tests/test_gh260_rate_limit.py:49
- Quote: `assert (await _req(app, "GET", "/v1/tasks", headers=h)).status_code == 429`
- Issue: New failed-bearer 429 tests (:49, :62, tests/test_gh152_api_key_optout.py:116) check status only — no Retry-After, no -32000 envelope on /v1, no check that the bearer is absent from the 429. LRN-209 pattern; SI-2 AC asks for these.
- Fix: Assert `retry-after == '60'`, /v1 body `{'error': {'code': -32000, 'message': 'rate limit exceeded'}}`, and BAD/user_key absent from body and headers.
- Codify: Every new 429 path needs a test of Retry-After, body shape and token redaction (LRN-209 applies to every new limiter).
- sdkCandidate: true

### D-10 (RT-003) — tests/test_gh260_rate_limit.py:57
- Issue: Rewrite deleted GH-260 regression test `test_invalid_bearer_still_rate_limited` (31 invalid-bearer POST /mcp -> 429). Nothing now tests the failed-bearer 429 on MCP. GH-260 ruling link dropped from module docstring.
- Fix: Parametrize `test_bearer_limiter_wired_from_setting` over /v1/tasks and POST /mcp, asserting MCP 429 shape and Retry-After. Keep the GH-260 ruling link next to GH-265's.
- Codify: When a wave rewrites an older issue's regression test file, every old test must survive or be replaced by one covering the same surface.
- sdkCandidate: true

## Low

### D-11 (RT-007) — agent_sdk/auth/middleware.py:50
- Issue: [SDK] Comment and test module docstring (tests/test_gh260_rate_limit.py:1) attribute the work to GH-260, not GH-265; GH-260 ruling link dropped, so GH-260 bearerless-never-429 tests cite only GH-265's ruling.
- Fix: Comment -> "GH-265"; test docstring header -> "GH-260 + GH-265", keeping both ruling links.
- sdkCandidate: true

### D-12 (RT-008) — agent_sdk/app.py:947
- Quote: `headers={**retry, "Cache-Control": "no-store"},`
- Issue: [SDK] The /oauth/token 429 has `Cache-Control: no-store` but no `Pragma: no-cache`, unlike every other token response (`_TOKEN_NO_CACHE`).
- Fix: Use `{**retry, **_TOKEN_NO_CACHE}` (at least for /oauth/token) and assert `pragma` in `test_api_routes_429_is_json_no_store`.
- sdkCandidate: true

### D-13 (RT-004) — tests/test_gh260_rate_limit.py:75
- Issue: No invalid-bearer test on /ag-ui/run; no expired or revoked OAuth access token test for the `error="invalid_token"` challenge (overlaps D-06; adds the revoked case and PRM URL variant check).
- Fix: Extend `test_invalid_and_missing_challenges` over POST /ag-ui/run; add a mint-then-revoke/expire case asserting the INVALID-prefixed challenge with the route's matching PRM URL (bare or MCP-suffixed).
- sdkCandidate: true

### D-14 (RT-005) — DESIGN.md:447
- Issue: §6 credits the failed-bearer split to GH-260 (which only kept missing-bearer 401s uncounted); split is GH-265. OAuth bucket listed as only register/token/consent (overlaps D-05).
- Fix: Cite GH-265 (keep GH-260 for "missing bearer never counted"); list all /oauth/* endpoints plus the X-Bootstrap-Token mint.
- sdkCandidate: true

### D-15 (RT-006) — agent_sdk/auth/middleware.py:50
- Issue: Wrong issue cited (GH-260 vs GH-265) in comment and test docstring (overlaps D-02/D-11).
- Fix: Change both citations to GH-265, as the CHANGELOG entry does.
- sdkCandidate: true

### D-16 (RT-007) — agent_sdk/auth/middleware.py:182
- Quote: `"""Per-IP window for intrinsically unauthenticated paths`
- Issue: Docstring lists only register/token/consent POST; does not say failed bearers are excluded and counted in `bearer_limiter` (overlaps D-04).
- Fix: List every route using the dependency; add a sentence that failed/refused bearers count in `AuthRuntime.bearer_limiter`.
- sdkCandidate: true

### D-17 (RT-008) — agent_sdk/app.py:947
- Issue: /oauth/token 429 lacks Pragma (overlaps D-12).
- Fix: Add `Pragma: no-cache` (or reuse `oauth._TOKEN_NO_CACHE`); assert pragma in `test_api_routes_429_is_json_no_store`.
- sdkCandidate: true

### D-18 (RT-009) — tests/test_gh260_rate_limit.py:195
- Quote: `async def test_token_responses_have_pragma_no_cache(app):`
- Issue: Pragma test covers only `_token_error` (grant_type=bogus); not `_token_success` or `_invalid_client`. Browser-route 429 test (:171-178) sends no client_id/redirect_uri, so cannot prove the HTML page omits them; never asserts `RATE_LIMITED_PAGE_TEXT`.
- Fix: Add a successful PKCE (or refresh) exchange and an invalid_client case asserting `pragma == 'no-cache'` and `cache-control == 'no-store'`. In `test_browser_routes_429_is_branded_html`, send distinctive client_id/redirect_uri, assert absent from r.text, and assert `html.escape(RATE_LIMITED_PAGE_TEXT)` in r.text.
- sdkCandidate: true
