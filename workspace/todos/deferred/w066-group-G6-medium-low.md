# w066 — Group G6 deferred medium/low findings

- **Wave:** w066
- **Scope:** unit:G6
- **Date:** 2026-10-25

> Non-blocking — these did not block w066's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — DESIGN.md:445 [sdkCandidate]
- **Quote:** "(2) **per-IP windows on all unauthenticated paths** (auth failures, `/oauth/register`, `/oauth/token`, consent) ..."
- **Issue:** [SDK] DESIGN.md §6 still says the per-IP window covers all unauthenticated paths including every auth failure. After GH-260, a request with no bearer token is exempt (agent_sdk/auth/middleware.py:119-120), and an /oauth/* 429 now has its own OAuth error body. The design spec contradicts the code and docs/protocols.md:154-158.
- **Fix:** Edit layer (2) in place: per-IP windows on invalid-bearer attempts, the /oauth/* endpoints (register, authorize, idp callback/consent, token, revoke), the bootstrap mint and webhooks; a request with no bearer always gets the 401 + PRM challenge and is not counted (GH-260); an /oauth/* 429 body is `{error: temporarily_unavailable, error_description: rate limit exceeded}` + Retry-After. Add DESIGN.md (§6 rate-limiting bullet only) to the G6 Modifies line and to the GH-260 CHANGELOG entry.
- **Codify:** When a fix narrows what a limiter or auth layer covers, the DESIGN.md section that lists that layer's scope must change in the same todo.

## RT-002 (medium) — tests/test_gh260_rate_limit.py:45 [sdkCandidate]
- **Quote:** `async def test_invalid_bearer_still_rate_limited(app_client):`
- **Issue:** [SDK] No test covers the root cause (shared-bucket draining): nothing checks that 31 bearer-less /mcp requests leave /oauth/register or /oauth/token under the limit. A regression where the bearer-less path calls `unauth_limiter.allow()` but ignores the result would pass. The test checks only `codes[-1]`, not that the first 30 are 401 with the PRM challenge, nor Retry-After (LRN-209 pattern). AC (b) is tested only on /oauth/token, not register, authorize or revoke.
- **Fix:** Add a test over `build_app()`: send 31 bearer-less POST /mcp (plus a few bearer-less /v1/tasks and /ag-ui/run), then POST /oauth/register and assert not 429. In `test_invalid_bearer_still_rate_limited`, assert `codes[:30]` are all 401 and the 31st has `Retry-After == '60'`. Parametrize the OAuth 429 body test over /oauth/register, /oauth/token and /oauth/revoke.
- **Codify:** A fix for a shared-bucket bug needs a test that fills the bucket through one path and checks that the other path is unaffected, not just that the exempt path never fails.

## RT-003 (low) — agent_sdk/auth/middleware.py:8 [sdkCandidate]
- **Quote:** "Bearer is header-borne only. Two rate-limit layers: per-IP on every"
- **Issue:** [SDK] Module docstring still says the per-IP limit applies to every unauthenticated or failed attempt; a bearer-less request is no longer counted. The `unauth_rate_limit` docstring (lines 173-174) lists only register, token and consent, but the dependency also guards GET/POST /oauth/authorize, /oauth/idp/callback, /oauth/idp/consent, /oauth/revoke, the bootstrap mint and webhooks.
- **Fix:** Reword lines 8-10: per-IP on invalid-bearer attempts and intrinsically unauthenticated endpoints (a missing bearer is never counted, GH-260), per-identity after auth. List every route that uses `unauth_rate_limit` in its docstring.

## RT-004 (low) — agent_sdk/app.py:928 [sdkCandidate]
- **Quote:** `if exc.status_code == 429 and request.url.path.startswith("/oauth/"):`
- **Issue:** [SDK] The new OAuth 429 body carries only the exception's own headers (Retry-After). It omits the `Cache-Control: no-store` every other OAuth JSON response in routes/oauth.py sends (oauth.py:415, :1004, :1008). Inconsistent with RFC 6749 §5.1/§5.2 practice and the module's own pattern.
- **Fix:** Merge headers in the branch, e.g. `headers={**(getattr(exc, 'headers', None) or {}), 'Cache-Control': 'no-store'}`. Assert the header in `test_oauth_429_body_and_header`.

## RT-005 (low) — agent_sdk/routes/oauth.py:334 [sdkCandidate]
- **Quote:** `@router.post("/oauth/register", dependencies=[Depends(unauth_rate_limit)])`
- **Issue:** [SDK] The G6 todo lists agent_sdk/routes/oauth.py under Creates/Modifies, but the file has no diff. The OAuth 429 shape was correctly placed in the app.py handler per C-082, so the todo scope line is inaccurate (Dimension 5: listed files not modified).
- **Fix:** Remove agent_sdk/routes/oauth.py from the GH-260 Modifies line, or move it to Reads, so the todo matches the landed change set and LRN-413/LRN-437 audits stay accurate.

---
Filed 2026-10-25 by /sdk-autoloop cycle 2: verified still-present mediums (and lows sharing a fix) are in #261–#267. Other lows stay here, unfiled.
