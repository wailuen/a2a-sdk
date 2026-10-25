# w067 — LRN capture cap exceeded

- Wave: w067
- Date: 2026-10-25
- MAX_LRN_PER_WAVE: 20
- Overflow findings: 5

These findings were already fixed but not codified as LRN files due to the 20-per-wave cap. Review and codify opportunistically, or fold into a future wave.

## RT-002 (high) — tests/test_gh260_rate_limit.py:126

- Quote: `r = await _req(app, "POST", "/admin/bootstrap/exchange", json={"token": BAD})`
- Description: [SDK] test_bootstrap_401_keeps_bare_challenge posts to /admin/bootstrap/exchange, which does not exist (it returns 404). Its assert sits inside `if r.status_code == 401`, so it never runs. The real bootstrap 401 site (admin.py:277, POST /admin/api/keys with an X-Bootstrap-Token header) is not tested, which breaks the AC that every bare-challenge site is asserted.
- Fix: POST /admin/api/keys with json={'label':'x'} and header X-Bootstrap-Token set to a bad value. Assert status_code == 401 and that www-authenticate starts with BARE. Remove the conditional.
- Codify: Never wrap a test's only assertion in an `if` on the response. Assert the precondition, so a wrong route fails the test instead of passing it silently.

## RT-003 (high) — tests/test_gh260_rate_limit.py:1

- Quote: `"""GH-260: separate failed-bearer limiter, 429 surface split, invalid_token challenge.`
- Description: [SDK] The rewrite deleted the shipped GH-260 regression tests test_bearerless_mcp_never_429 and test_non_oauth_429_unchanged, and nothing replaces them. A grep of tests/ finds no other test that a missing bearer never 429s after 31 requests, or that a non-/oauth/ 429 (e.g. /admin/api/keys) keeps the {"detail": "rate limit exceeded"} body. The GH-265 ruling says 'Missing-bearer 401s stay uncounted (GH-260)', but that is no longer pinned by any test.
- Fix: Restore test_bearerless_mcp_never_429 (more than 30 bearer-less POST /mcp calls, all 401 with the bare challenge) and test_non_oauth_429_unchanged (bad bearer on /admin/api/keys drains bearer_limiter, last response 429 with {'detail': 'rate limit exceeded'}). Keep the new tests next to them.
- Codify: When a todo rewrites a test file that guards an earlier issue's fix, carry every earlier regression test forward or move it. Do not replace the file's contents.

## RT-004 (high) — CHANGELOG.md:10

- Quote: `- GH-260: an invalid, expired or refused bearer now gets WWW-Authenticate: Bearer error="invalid_token", ...` (GH-265 entry mislabelled GH-260)
- Description: [SDK] The GH-265 Unreleased entry fails LRN-491. It names none of its changed files, and agent_sdk/auth/middleware.py and agent_sdk/routes/oauth.py appear nowhere in [Unreleased] (the LRN-491 check reports both MISSING). It is also labelled GH-260, a different issue already released in 0.23.0, so release and issue-close tooling that keys on the GH ID will not find GH-265.
- Fix: Relabel the bullet 'GH-265' and add 'Changed: `agent_sdk/auth/middleware.py`, `agent_sdk/routes/oauth.py`, `agent_sdk/app.py`, `DESIGN.md`, `docs/protocols.md`. Tests: `tests/test_gh260_rate_limit.py`, `tests/test_gh152_api_key_optout.py`.'
- Codify: A CHANGELOG bullet carries the issue ID of the todo that wrote it, not the ID of the test file or earlier fix it touches, and it names every changed agent_sdk/ path.

## RT-001 (high, sdkCandidate) — CHANGELOG.md:10

- Quote: `- GH-265: an invalid, expired or refused bearer now gets ... Changed: agent_sdk/auth/middleware.py, agent_sdk/routes/oauth.py, ...`
- Description: [SDK] LRN-379 check fails: GH-265 adds new top-level public names `BROWSER_OAUTH_ROUTES` and `RATE_LIMITED_PAGE_TEXT` in agent_sdk/routes/oauth.py, the new `AuthRuntime.bearer_limiter` field, and the new keyword `invalid_token` on `_prm_challenge`/`_unauthorized`, but none of them has an `### Added` bullet in [Unreleased]; GH-265 appears only under Breaking changes.
- Fix: Add a GH-265 bullet under `### Added` naming `AuthRuntime.bearer_limiter` (agent_sdk/auth/middleware.py), `BROWSER_OAUTH_ROUTES` and `RATE_LIMITED_PAGE_TEXT` (agent_sdk/routes/oauth.py) and the `invalid_token` keyword on `_prm_challenge`; move the non-breaking parts (Cache-Control/Pragma headers) to `### Fixed`.
- Codify: Every new non-underscore module-level name and every new dataclass field needs its own ### Added bullet, even when the issue's main entry sits under Breaking changes.

## RT-001 (high, sdkCandidate) — CHANGELOG.md:25

- Quote: `- GH-267: w066 leftovers. loads_strict gains a keyword-only reject_duplicate_keys=False`
- Description: [SDK] LRN-527 Check fails. The GH-267 bullet changes several files but never names `agent_sdk/common/json_strict.py` by path; `grep -c json_strict.py` over [Unreleased] returns 0. It also lists no test paths (`tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh251_ingress.py`), unlike every sibling bullet. It also says the deep-metadata test 'now sends an otherwise valid message', which is false (see RT-002).
- Fix: Add 'Changed: `agent_sdk/common/json_strict.py`, `agent_sdk/credentials/forwarding.py`, `agent_sdk/routes/{mcp,ag_ui}.py`, `agent_sdk/contrib/action_gate/gate.py`, `agent_sdk/example/agent.py`. Tests: `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh251_ingress.py`.' Correct the 'otherwise valid' claim once RT-002 is fixed. Put the new public `reject_duplicate_keys` option in an `### Added` line, since it is new API, not a fix.
- Codify: A multi-file CHANGELOG bullet must name the module whose public signature changed by its file path, not only by its symbol name.
