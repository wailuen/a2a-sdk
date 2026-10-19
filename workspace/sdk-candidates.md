# SDK issue candidates — w058 (2026-10-19)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: RT-001: A revoked API key can come back. verify() now runs in a worker thread and writes the whole old record back for last_used. If revoke() deletes the row in between, the upsert re-creates it with the hash, so the key works again (Azure MERGE upsert and SQLite ON CONFLICT both re-create the row). Fix: one threading.Lock in ApiKeyStore; re-read before the last_used write and skip it if the row is gone or the hash changed; hold the lock across revoke's read, admin check and delete; add forced-interleaving tests; note cross-replica race in DESIGN.md section 6.
- Severity: critical
- Component: security
- File: agent_sdk/auth/api_keys.py
- Rationale: Core SDK auth code (agent_sdk/auth/api_keys.py, middleware, oauth and admin routes). It breaks key revocation for every agent built on the SDK. Not agent-domain code.

## Candidate 2: RT-002: Two revokes at the same time can delete the last two admin keys. Both pass the other-admin check (api_keys.py:134-138) and both delete, leaving zero admin keys. This breaks the 'lockout is impossible' promise in the module docstring and DESIGN.md section 6. Fix: hold the same ApiKeyStore lock across all of revoke(); add a Barrier test asserting one succeeds and one raises AgentError(VALIDATION).
- Severity: high
- Component: security
- File: agent_sdk/auth/api_keys.py
- Rationale: SDK auth invariant (last-admin-key protection) in agent_sdk/auth and agent_sdk/routes/admin.py. Affects all SDK agents.

## Candidate 3: RT-001 (lock contention): _touch_last_used blocks on one process-wide _write_lock and holds it across two store round trips; revoke() holds it across a full list_items scan. With many active keys on Azure Table, waiting threads fill the shared asyncio.to_thread pool and stall auth traffic, similar to GH-202. Fix: make the last_used write best-effort with a non-blocking acquire, or use per-key locks plus a separate last-admin lock; add a test that a verify of another stale key returns quickly while revoke is paused in list_items.
- Severity: high
- Component: sdk/credentials
- File: agent_sdk/auth/api_keys.py
- Rationale: SDK internals: API key store and credential store I/O in the shared thread pool. Applies to every deployment using the SDK key store.

## Candidate 4: RT-001 (test gap): test_admin_listing_does_not_block_event_loop does not prove list_keys/count/revoke run off the event loop. The slow store also slows the auth verify, so the /health probe finishes during auth. Reverting the GH-202 admin route fix still passes. revoke_key and overview count() have no off-loop test. Fix: make only list_items slow (or pre-set last_used), assert the thread id differs from the loop thread, add the same check for DELETE /admin/api/keys/{id} and GET /admin/api/overview, and confirm the test fails with the fix reverted.
- Severity: high
- Component: sdk/console
- File: tests/test_gh202_api_key_store_off_loop.py
- Rationale: SDK regression test for the admin console routes (agent_sdk/routes/admin.py). It is the SDK's own test suite, not an agent test, and leaves the GH-202 fix unguarded.

## Candidate 5: RT-002 (changelog): The [Unreleased] entry fails LRN-379 and LRN-202. Five of seven changed agent_sdk files are not named. New public method CredentialStore.list_items has no ### Added line. The lock and race fixes and tests/test_gh202_api_key_races.py are not mentioned. Fix: add an ### Added bullet for list_items, name every changed file, describe the lock and re-read-before-write, list both test files.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: SDK release documentation and public API record; required by the SDK release gate.

## Candidate 6: RT-003 (scope check): LRN-361 fails. tests/test_gh202_api_key_races.py and tests/test_gh183_184_service_key_mint_step.py are on no Creates/Modifies line. The second change hides a behavior change: stores passed to ApiKeyStore must now subclass CredentialStore (or provide list_items), or count() raises AttributeError at startup via bootstrap.arm_if_needed(). Fix: add both paths to the todo; note the new subclass requirement in the todo and CHANGELOG.
- Severity: high
- Component: harness/workflow
- File: workspace/todos/active/w058-gh-issues.md
- Rationale: Wave workflow scope tracking for SDK work, plus an SDK credential-store contract change. Not agent-domain.
