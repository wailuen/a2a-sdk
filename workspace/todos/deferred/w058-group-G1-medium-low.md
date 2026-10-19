wave: w058
group: G1
date: 2026-10-19

Non-blocking — these did not block w058's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from
each round is folded in. IDs below are renumbered after the merge (round IDs collided: RT-002..RT-008
were reused across rounds for different findings). All findings are SDK-level (sdkCandidate: true).

Note on lock findings: early rounds saw one process-wide `_write_lock`; the last round saw 64 hash-striped
per-key locks, a separate `_admin_lock`, and a non-blocking last_used write. RT-005 below records what is
still open after that change.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/auth/middleware.py
- description: Every bearer request now runs api_keys.verify on asyncio's shared default executor (min(32, cpu+4) workers, about 5 on a 1-vCPU container). That pool is also used by asyncio getaddrinfo (DNS lookups for adapter HTTP), contrib/scheduler, contrib/obo/exchange and validate_credential_url. A slow list_keys/revoke scan, or a flood of bogus regex-matching `ak_<16hex>_x` tokens, can fill the pool. Such tokens each do a store get before unauth_limiter runs at middleware.py:128. Authenticated requests then queue behind them. DESIGN.md §6 line 423 says a slow store "cannot stall /health or other routes", but other routes still stall at the pool. bedrock.py avoids the default pool for exactly this reason (DESIGN §8).
- fix: Give ApiKeyStore I/O its own bounded ThreadPoolExecutor, as BedrockModelClient does, and run it via loop.run_in_executor in middleware/admin/oauth. Or reword DESIGN §6 to say only the loop (not the routes) is protected. Optionally apply unauth_limiter.peek before the threaded verify.
- codify: Moving per-request blocking work off the event loop onto the shared default executor moves the stall to the pool; per-request hot paths need a dedicated bounded executor.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/auth/api_keys.py
- description: (Merged from three rounds.) `count()` (line 57-58) changed from `list_fields` to `list_items`, so it now reads and decrypts every API-key row just to get a number. Before, it was one query, no values, no decrypt. This makes three things worse. (1) On any third-party store the base-class default turns `count()` into 1 + N `get` calls — the exact GH-202 shape — reached at every boot (`app.py:710` `BootstrapManager.arm_if_needed()`) and on every admin overview load. (2) On the built-in stores it decrypts all ~56k rows on each overview load. (3) One row that cannot be decrypted (corrupt, wrong AAD, partial write, or written under another MASTER_KEY) now makes `list_items` raise AgentError. That stops the agent from booting in the lifespan and returns 500 on /admin/api/overview. Before, only the key listing failed. Such a row is rare (the master-key check row catches whole-store key mismatch), but it is a new boot-time failure mode.
- fix: Preferred: have `count()` use `len(self._store.list_fields(NS_API_KEYS))` — already one query with zero per-key `get` calls in both built-in stores, which meets the GH-202 intent (the ruling targeted per-key gets, not list_fields). Amend the todo AC and the DESIGN.md §6 line to say only `list_keys` and revoke's admin check need `list_items` (record a ruling note, since the AC names list_items). Alternatives: make count() tolerate per-row decrypt failure; or catch AgentError in arm_if_needed and treat it as 'keys exist' (fail closed: do not arm bootstrap) with a logged warning that has no row content; or at minimum document in DESIGN.md §6 that count() fails on a corrupt key row. Add a test that pins whichever behaviour is chosen.
- codify: A count/existence probe on the boot path must not take a dependency on decrypting every row; one corrupt record must not brick startup.
- sdkCandidate: true

### RT-003
- severity: medium
- file: tests/test_gh202_api_key_store_off_loop.py
- description: The event-loop test does not prove that GET /admin/api/keys runs list_keys() off the loop. The /health request goes out at t=0.1 s. At that moment the require_admin verify() is still sleeping in a worker thread (0 to 0.5 s), so the loop is free whatever list_keys does. Confirmed: with to_thread in agent_sdk/routes/admin.py swapped for a synchronous shim, test_admin_listing_does_not_block_event_loop still passes. A regression that puts list_keys back on the loop (the actual GH-202 outage) would go green.
- fix: Make only list_items slow, for example SlowStore.get with no sleep and a 0.5 s list_items, so verify() returns at once. Or start /health only after the listing has entered list_items (signal with a threading.Event set inside list_items). Then assert /health returns while list_items is still sleeping. Add the same test for the overview count() and the revoke route.
- sdkCandidate: true

### RT-004
- severity: medium
- file: tests/test_gh202_api_key_store_off_loop.py
- description: (Merged from four rounds.) No test proves that `verify` runs off the event loop at any of its three call sites: `middleware._resolve_identity` (line 124), `oauth_authorize_approve` (oauth.py:918/919) and `oauth_revoke` (oauth.py:1069). `SlowStore` (lines 205-218) slows only `list_items`, and the warm-up keeps `get` fast on purpose (see also RT-003). If any of the three `asyncio.to_thread(runtime.api_keys.verify, ...)` wrappers is turned back into a direct call, all 3655 tests still pass. Separately, the Azure tests build the store with `object.__new__` and set private attributes by hand; a new required attribute added in `__init__` would make list_items fail in production while these tests still pass.
- fix: Add probe tests with a store whose `get` does `time.sleep(0.5)` on __api_keys__ and records `threading.get_ident()`. Hit (a) one `require_identity` route (authenticated A2A/MCP), (b) POST /oauth/authorize (approve) with an api_key, and (c) POST /oauth/revoke with an `ak_` bearer. For each, assert that `get` ran on a thread other than the loop thread and that a concurrent GET /health returns in under 0.3 s while verify is still sleeping. Build the Azure fixture through a constructor seam, or assert that the attributes it sets match the ones `__init__` sets.
- codify: Every off-loop call site named in an AC needs its own loop-not-blocked probe, or a revert at that site passes silently.
- sdkCandidate: true

### RT-005
- severity: medium
- file: agent_sdk/auth/api_keys.py
- description: Lock contention between revoke and last_used writes. As first raised: one process-wide `_write_lock` (line 53) serialised every last_used write (`_touch_last_used`, line 133), and revoke() held it across its full `list_items(NS_API_KEYS)` scan (lines 141-156). Measured: with a 2 s list_items, a concurrent verify of an unrelated key took 1.9 s. At GH-202 scale (~56k keys on Azure, one HTTP get+upsert per touch) touches pile up, use up the default to_thread pool, and every verify queues — bringing back, for the length of the scan, the stall GH-202 set out to remove. A later round shows the code moved to 64 hash-striped locks + `_admin_lock` with a non-blocking touch. Still open per the last round: a non-admin revoke of any key on the same stripe blocks (blocking `with`) for the whole admin list_items scan.
- fix: Confirm the striped scheme fully separates the admin scan from per-key work: the admin revoke should hold `_admin_lock` for the scan and take the per-key stripe only around the delete, so an unrelated revoke never waits on the scan. Keep tests/test_gh202_api_key_races.py green, and add a test that verify and revoke of an unrelated key are not delayed by a slow admin revoke.
- sdkCandidate: true

### RT-006
- severity: medium
- file: DESIGN.md
- description: (Merged from two rounds.) DESIGN.md §6 overstates the lock guarantees. (1) The 'Key-store I/O (GH-202)' bullet says 'revocation is immediate on every replica', and the 'Last-key protection' bullet says lockout is impossible; the api_keys.py module docstring (lines 5-6) makes the same lockout claim. Neither holds across replicas. The race across replicas existed before but is not mentioned, although the todo's SI-5 annotation asked for that note. (2) §6 line 421 says ApiKeyStore 'serialises revoke() and the last_used write behind one lock'. The code uses 64 hash-striped per-key locks plus a separate `_admin_lock`, and `_touch_last_used` acquires without blocking: when the lock is busy it skips the write instead of being serialised. CHANGELOG [Unreleased] says 'per-key locks' (they are striped) and 'a slow admin revoke never stalls other keys', which is false (see RT-005).
- fix: Rewrite the §6 sentence to describe the real scheme: striped per-key locks guard revoke and the last_used re-read+write; the last_used write is skipped if its stripe is busy; a separate admin lock serialises the last-admin check+delete — all within one replica. State that a verify last_used write racing a revoke on another replica, and two concurrent last-admin revokes on different replicas, are known gaps that are out of scope. Fix the api_keys.py docstring and the CHANGELOG wording the same way; drop or qualify the 'never stalls other keys' claim.
- sdkCandidate: true

### RT-007
- severity: low
- file: agent_sdk/routes/admin.py
- description: (Merged from three rounds.) POST /admin/api/keys `mint_key` still calls `auth.api_keys.mint(...)` directly on the event loop (lines 279 and 284). Each call is one synchronous `store.set`, which on AzureTableCredentialStore is one HTTP upsert round trip that blocks every route while it runs. This goes against the new DESIGN.md §6/§credentials rule 'All store methods block; async callers use asyncio.to_thread', and the §6 'Key-store I/O' bullet leaves mint out without saying so. (runtime.oauth.verify is also still on the loop at middleware.py:126, but that is excluded by the ruling.)
- fix: Wrap both calls: `await asyncio.to_thread(auth.api_keys.mint, body.label, admin=..., service=...)` (or the dedicated executor from RT-001). Keep the bootstrap `consume()` on the loop before it so the single-use check stays atomic. Or narrow the DESIGN.md sentence / state in §6 that mint stays on the loop on purpose.
- sdkCandidate: true

### RT-008
- severity: low
- file: agent_sdk/auth/middleware.py
- description: (Merged from two rounds.) `_resolve_identity` (line 124) sends every bearer token to a worker thread, including OAuth access tokens that can never match `_API_KEY_RE`. `verify()` returns None right after the regex check with no I/O. So each OAuth-authenticated request pays for a thread hop and holds a slot in the shared default pool for nothing (compounds RT-001).
- fix: Check the token shape on the loop first: run `_API_KEY_RE.fullmatch` (or `token.startswith("ak_")`, or a cheap `ApiKeyStore.looks_like_key(token)`) and only then `await asyncio.to_thread(runtime.api_keys.verify, token)`; else set `identity = None`.
- sdkCandidate: true

### RT-009
- severity: low
- file: tests/test_gh202_api_key_races.py
- description: (Merged from two rounds.) `test_revoked_key_is_not_resurrected_by_inflight_verify` pauses only on the verifier's first `get`, which runs outside the lock in `verify()`. It never forces a revoke to land between the `_record` re-read inside `_touch_last_used` and its `set`, which is the gap the lock exists to close. If the lock is removed from `_touch_last_used`, the test still passes. The interleaving where revoke arrives while `_touch_last_used` holds the stripe lock (revoke must block, then delete) is also untested.
- fix: Add a second interleaving test. Pause on the verifier's second `get` (the re-read inside `_touch_last_used`) or block `store.set` inside it, start `revoke(key_id)` in another thread, release, then assert the row is absent after revoke finishes. Without the lock, the `set` must bring the row back and the test must fail.
- sdkCandidate: true

### RT-010
- severity: low
- file: tests/test_gh202_api_key_races.py
- description: The race test file imports MinimalStore from another test module (tests.test_gh202_api_key_store_off_loop), so the two test modules depend on each other. The CHANGELOG [Unreleased] entry's 'Tests:' line lists only test_gh202_api_key_store_off_loop.py and does not mention the in-process lock or the race tests.
- fix: Move MinimalStore/DictStore into tests/conftest.py or a small tests/_stores.py helper and import from there. Add tests/test_gh202_api_key_races.py and a short note on the in-process revoke/last_used lock to the CHANGELOG GH-202 entry.
- sdkCandidate: true

### RT-011
- severity: low
- file: CHANGELOG.md
- description: The [Unreleased] section describes CredentialStore.list_items twice, once under Added and again inline in the Fixed entry, with slightly different wording. The Fixed entry is also one paragraph of more than 15 clauses that mixes the fix, the docs and lock internals.
- fix: Keep list_items under Added only. Trim the Fixed entry to the user-visible fix: off-loop key-store calls, one query per listing, last_used accurate to about 60 s, response shape unchanged, ruling URL and tests (including the RT-010 additions).
- sdkCandidate: true
