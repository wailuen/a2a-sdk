wave: w047
scope: group
group: G2
date: 2026-10-13

Non-blocking — these did not block w047's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G2.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/auth/oauth_tokens.py
- description: revoke_user() (GH-163) leaves the user's unredeemed auth codes in self._codes (user field set, TTL 5 min) and pending IdP consent tickets alone. A code minted just before the admin revokes can still be exchanged at /oauth/token (routes/oauth.py:851-857, 1004). That exchange mints a brand-new refresh family with a full SESSION_HOURS lifetime, so the revocation is undone.
- fix: In revoke_user also drop every self._codes entry whose .user == user. Add an IdpFlowStore helper that drops pending consent tickets for that user, and call it from the admin route. Add a test: mint_code(user=X), revoke_user(X), then consume_code returns None.
- codify: A revoke-by-identity must purge every in-flight grant for that identity (auth codes, consent tickets), not just the refresh and access tokens that already exist.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/app.py
- description: _warn_single_replica_required fires only for oauth_idp=oidc or oauth_one_time_consent. But /oauth/* is always mounted (app.py:907), and the default admin-key-gated OAuth connector flow keeps auth codes and access tokens in process memory too. MCP Streamable HTTP sessions are also per-process (routes/mcp.py:234) whatever the auth mode. So a multi-replica Azure Table deployment that uses Claude.ai connectors through admin consent breaks with no warning. docs/deployment.md Replicas also says 'If sign-in is off (API keys only), more than one replica is possible' without saying that admin-consented OAuth connectors and MCP sessions break as well.
- fix: Either warn whenever a shared store is configured (OAuth and MCP sessions are always per-process), or reword docs/deployment.md Replicas and the warning so they say that any OAuth connector (admin-key consent included) and any MCP Streamable HTTP client needs exactly one replica. Add a test for shared store + defaults that matches whichever rule is chosen.
- codify: A 'feature on' gate for a warning must match every code path that uses the per-process state, not just the opt-in settings.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/auth/oauth_tokens.py
- description: list_identities() skips rotated tombstones and takes created_at only from the live refresh row. Each rotation mints that row fresh (mint_token_pair sets created_at=now), so 'earliest_created' is really the time of the last refresh, not when the family started. The console labels it 'First sign-in' (console.js renderSignedInUsers). The GH-163 AC asks for 'earliest created', and the test only checks earliest_created <= latest_expiry, which is always true.
- fix: Store a family_created_at field at first mint and copy it through rotate_refresh, the same way family_expires_at is copied. Report min(family_created_at). Add a test that rotates a token and checks that earliest_created does not change.
- codify: A per-family summary field must come from a value copied through rotation, never from the newest row of the rotation chain.
- sdkCandidate: true

### RT-004
- severity: medium
- file: tests/test_gh162_single_replica_warning.py
- description: The plan's SI-2 annotation requires a test showing the warning text holds no part of a marker connection string. No such test exists: every case uses 'UseDevelopmentStorage=true' and never asserts absence. The AZURE_STORAGE_ACCOUNT_NAME branch is untested. _boot() also swallows every exception, and build_app() raises in every case (it gets connection refused from Azurite at 127.0.0.1:10002, or 'No model backend configured'; confirmed by probe). So the two negative tests would still pass if the warning call were moved after a failing step, and the suite depends on network behaviour.
- fix: Test the warning directly: construct the Agent and call _warn_single_replica_required(), or monkeypatch _build_credential_store and the model backend so build_app completes. Add a test with a marker connection string (e.g. 'DefaultEndpointsProtocol=https;AccountName=MARKERACCT;AccountKey=MARKERKEY==') that asserts no fragment appears in any log record. Add an account_name case. Remove the bare 'except Exception: pass'.
- codify: Boot-warning tests must not swallow build_app exceptions. A negative 'no warning' assertion is vacuous unless the code path is proven to have run.
- sdkCandidate: true

### RT-005
- severity: medium
- file: harness/workflows/wave-cycle.js
- description: GH-165 Archive step 3 says the test name 'must be cited in ' + WAVE_FILE (workspace/todos/active/...). Step 1 of the same prompt has already moved that file to workspace/todos/completed/. The agent is told to verify citations in a path that no longer exists, so the Test: backfill either silently never fires or reads the wrong file. wave-cycle.js also never passes this wave's pytest results to the archive agent, so 'passed in this wave' cannot be checked. The same defect is in .claude/workflows/wave-cycle.js, template/.claude/workflows/wave-cycle.js and .claude/workflows/sdk-wave.js (line ~2382).
- fix: In step 3, point at 'workspace/todos/completed/' + WAVE_BASENAME, or move the FR backfill ahead of the file move. Pass the last green pytest-gate result (or the list of passed node ids) into the archive prompt. Apply to all four copies, keep the three wave-cycle.js copies byte-identical, and push the template repo.
- codify: Multi-step agent prompts must reference artifacts by their location after earlier steps in the same prompt have moved them.
- sdkCandidate: true

### RT-006
- severity: medium
- file: docs/deployment.md
- description: The new Known-limitations entry 'Revoking is slow across replicas' says a revoked key or token is honoured by other replicas 'until they restart or the entry expires'. That is wrong for API keys and refresh tokens: they live in reserved namespaces that bypass the Azure Table read cache (credentials/azure_table.py:36-38, 182-185), so revocation takes effect on every replica at once. Only in-memory OAuth access tokens lag, for at most ACCESS_TTL_SECONDS (1 h). This contradicts DESIGN.md and the ADR a003 GH-163 text, which state the lag correctly.
- fix: Reword: API-key and refresh-token revocation is immediate on all replicas. An OAuth access token revoked on one replica stays valid on the others until it expires (max 1 hour).
- codify: Limitation docs must name the exact state that lags and its bound, checked against the cache-bypass rules in the store.
- sdkCandidate: true

### RT-007
- severity: medium
- file: workspace/todos/deferred/gh162-shared-oauth-state.md
- description: The plan's Reuses: C-024 annotation requires the deferred note to name the planned C-024 BoundedTtlSingleUseStore (and its C-028 per-source quota option) as the abstraction to back with a shared store. The note names neither component and describes the store needs from scratch. This invites a second, separate store design later (Dimension 8 reuse mismatch).
- fix: Add a line saying the shared backing should implement C-024 BoundedTtlSingleUseStore (agent_sdk/common/bounded_store.py, planned), with C-028 per-key quota, backed by an atomic conditional-delete table store.
- codify: Deferred design notes must cite the registered component they will extend, so future work does not fork the abstraction.
- sdkCandidate: true

### RT-008
- severity: low
- file: agent_sdk/auth/oauth_tokens.py
- description: revoke_user() lists and reads every refresh row, then calls revoke_family() once per family. Each call lists and reads every row again, so the cost is (F+1)*N store reads. On Azure Table the NS_OAUTH_REFRESH namespace is uncached, so each read is a network call, run synchronously inside the async admin route, and it blocks the event loop. list_identities() has the same N-read pattern.
- fix: Use one pass: collect the user's family ids, then delete every row whose family_id is in that set during the same listing, and drop matching access tokens. Run the store work in the admin routes through asyncio.to_thread.
- sdkCandidate: true

### RT-009
- severity: low
- file: agent_sdk/routes/admin.py
- description: revoke_oauth_identity returns the caller-supplied path value raw ({'user': user}). The plan's C-007 annotation says it must never be logged or echoed raw. The log line also leaves out the user entirely, so there is no audit record of who was revoked.
- fix: Return and log safe_error_text(user, max_len=128) (C-007), or return only the count. Include the sanitized user in the warning log so revocations can be audited.
- sdkCandidate: true

### RT-010
- severity: low
- file: agent_sdk/routes/admin.py
- description: DELETE /admin/api/oauth/identities/{user} uses a plain path parameter. Starlette matches on the percent-decoded path, so a generic-OIDC 'sub' that contains '/' (legal per OIDC Core) becomes %2F, then '/', and gets a 404. That user can never be revoked through the API or the console.
- fix: Declare the route as '/admin/api/oauth/identities/{user:path}', or take the user in a query or body parameter. Add a test with a '/'-containing user.
- sdkCandidate: true

### RT-011
- severity: low
- file: agent_sdk/auth/oauth_tokens.py
- description: revoke_user's returned count includes families that list_identities hides: expired families, tombstone-only families, and an empty family_id. So the console toast ('Revoked N session(s)') can disagree with the 'Sessions' column the admin just saw. Separately, the sdk-wave.js Archive phase detail (line 12) was not updated to mention the Test: backfill, though the GH-165 AC asks for the phase detail text to be updated.
- fix: Count only live families with a non-empty family_id, using the same predicate as list_identities. Update the sdk-wave.js Archive phase detail string.
- sdkCandidate: true
