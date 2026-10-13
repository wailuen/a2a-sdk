wave: w047
scope: group
group: G3
date: 2026-10-13

Non-blocking — these did not block w047's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G3. Two rounds reported overlapping IDs, so entries are renumbered here; `source` lists the original round IDs that were merged (rN = redteam round in which it was reported).

## Findings

### RT-001
- severity: medium
- file: agent_sdk/routes/ag_ui.py
- source: r1 RT-002, r2 RT-002
- description: [SDK] GH-168 raised the per-message replay cap 8x (4000 to 32000 chars) and added no total-history budget. Folded model input was at most about 200K chars (50 x 4000). It is now bounded only by the 1 MB body cap (_MAX_BODY_BYTES, line 72), so up to about 1M chars (roughly 250K tokens), more than many model context windows. The AG-UI client resends the same history every turn, so once a thread passes the model's context window every later run ends in RUN_ERROR — the 'bricked session' failure the _fold_history docstring says history processing must never cause, and which DESIGN.md §5.3 says is never used for large-but-valid client history. CHANGELOG files this under '### Fixed' with no cost or size note and no Migration line (operators can set 4000 to restore the old bound).
- fix: In _fold_history, add a total folded-history char budget (e.g. a validated AGENT_SDK_AGUI_MAX_HISTORY_CHARS setting, or a derived cap such as 4 x max_chars) that drops the oldest whole messages until the total fits, keeps the leading-user invariant, and logs lengths only (warning). Add a test with 50 messages at the cap. At minimum, document the worst-case total in DESIGN.md §5.3 and docs/deployment.md next to the new setting, and move the CHANGELOG entry to '⚠️ Behavior changes' with a Migration line.
- codify: Raising a per-item cap on replayed history must be checked against the total size it allows into the model input, not only the per-item limit.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/app.py
- source: r1 RT-005, r2 RT-001
- description: [SDK] The GH-162 single-replica warning `_warn_single_replica_required` (app.py:559-571, check at :565) fires only when `oauth_idp == 'oidc'` or `oauth_one_time_consent`. But the OAuth server router is always mounted (app.py:907): DCR, admin-key consent, auth codes, access tokens and MCP sessions all stay per-process in the default mode too. A shared Azure Table store with default settings and an MCP OAuth connector (Claude.ai) breaks across replicas — a code issued on replica A is redeemed on replica B — with no warning. docs/deployment.md:233 Replicas also says 'If sign-in is off (API keys only), more than one replica is possible', yet its own Known limitations list MCP sessions as per-process whatever the auth mode, so API-key MCP clients also break across replicas without sticky sessions.
- fix: Warn whenever a shared store is configured (the OAuth server cannot be turned off), or gate on a real 'OAuth disabled' switch if one exists. Reword docs/deployment.md Replicas: with more than one replica, MCP sessions and any OAuth sign-in (admin-key consent included) need one replica or sticky routing; multi-replica is safe only for API-key-only clients that never use /oauth/* or a /mcp session. Add a test: shared store (Azure Table) + default settings gives exactly one WARNING.
- codify: A 'feature on' predicate used for a warning or doc rule must match the code path that actually mounts the feature, not only the opt-in flags that change its behaviour.
- sdkCandidate: true

### RT-003
- severity: medium
- file: workspace/todos/deferred/w042-group-A2-medium-low.md
- source: r1 RT-003
- description: The GH-166 AC 'w042 RT-009 deferred entries cross-referenced as resolved' is not met. Only workspace/todos/deferred/w042-phase-medium-low.md RT-027 got a RESOLVED status line. The RT-009 entries the AC names are still open with no cross-reference: w042-group-A2-medium-low.md:28 ('uvicorn access log carries callback code/state: R5 RT-009') and :411, and w042-group-A2-budget-exhausted.md:62. The CHANGELOG cites only RT-027.
- fix: Add 'status: RESOLVED (GH-166) ...' lines to the R5 RT-009 entries in w042-group-A2-medium-low.md (lines 28 and 411) and w042-group-A2-budget-exhausted.md (line 62). Optionally list them in the CHANGELOG GH-166 entry.
- sdkCandidate: false

### RT-004
- severity: medium
- file: docs/protocols.md
- source: r1 RT-004
- description: docs/protocols.md:102-105 was changed for GH-168, but no todo's Creates/Modifies line declares it (the GH-168 scope lists DESIGN.md §5.3, docs/deployment.md and CHANGELOG only; LRN-322/LRN-202 scope drift). The new sentence is also wrong: '>50 messages or messages over AGENT_SDK_AGUI_MAX_MESSAGE_CHARS ... keep head and tail with an omission marker' says the 50-message cap keeps head and tail. In fact the oldest messages are dropped (`raw_messages[-MAX_HISTORY_MESSAGES:]`).
- fix: Rewrite as: 'only the most recent 50 messages are kept (oldest dropped); a message over AGENT_SDK_AGUI_MAX_MESSAGE_CHARS (default 32000) keeps its start and end with a [... N chars omitted ...] marker'. Add docs/protocols.md to the GH-168 todo's Modifies list.
- sdkCandidate: false

### RT-005
- severity: low
- file: agent_sdk/observability/logging.py
- source: r1 RT-006, r2 RT-004
- description: [SDK] _OAuthQueryFilter strips the query only when the logged path starts with '/oauth/' (logging.py:58). uvicorn 0.49 builds the access-log path from scope['path'] = root_path + path (h11_impl.py:202). Under `--root-path /agent` (prefix-routed ingress) the callback is logged as '/agent/oauth/idp/callback?code=...&state=...' and is not stripped. An absolute-form request target ('GET http://host/oauth/idp/callback?code=...') is also missed. docs/security.md says the SDK strips the query from 'every /oauth/ path'.
- fix: Match on the path part before '?' (after removing any scheme://host prefix): strip the query when '/oauth/' appears as a path segment anywhere in it (e.g. `p = path.split('?',1)[0]; if '/oauth/' in p or p.startswith('oauth/')`). Or state in docs/security.md and docs/deployment.md that root-path deployments are not covered. Add test records for a root_path prefix and an absolute-form target.
- sdkCandidate: true

### RT-006
- severity: low
- file: agent_sdk/routes/ag_ui.py
- source: r1 RT-007, r2 RT-003
- description: The GH-168 AC says the new setting 'replaces the fixed constant', but `MAX_MESSAGE_CHARS = 32000` (line 71) remains as `_fold_history`'s default, so 32000 is defined in two places (config.py:240 and ag_ui.py:71) that can drift. An agent author or test that imports it gets a value that no longer controls the live behaviour.
- fix: Remove the module constant and make `max_chars` a required keyword of `_fold_history`. Or keep it only as a documented alias of the settings default and use it as Field(default=...) in config.py, so there is one source of truth.
- sdkCandidate: true

### RT-007
- severity: low
- file: agent_sdk/routes/ag_ui.py
- source: r1 RT-007, r2 RT-007
- description: `_cut_middle` does not guard `limit < len(marker)`. For a limit below about 30 chars, `keep` is negative, the head and tail slices return nearly the whole content plus the marker, and the output is longer than the limit. Only the settings `ge=1000` guard prevents this; a direct call to `_fold_history` with a small max_chars breaks the 'marker counted within the limit' contract.
- fix: Clamp at the top of `_cut_middle`: if limit is below a safe minimum (shorter than the shortest possible marker, or e.g. `if limit < 100: return content[:limit]`), return `content[:limit]`. Or assert limit >= 1000 there so the invariant does not rely only on the config validator.
- sdkCandidate: true

### RT-008
- severity: low
- file: tests/test_gh168_agui_truncation.py
- source: r1 RT-008, r2 RT-006
- description: The GH-168 SI-2 annotation requires that an invalid AGENT_SDK_AGUI_MAX_MESSAGE_CHARS fails boot without echoing the value. test_invalid_setting_fails_boot (line 35) only asserts that a ValidationError is raised; it never checks that the bad value is absent from str(error). The behavior is correct today (checked by hand: a marker value is not echoed), but nothing stops a regression if hide_input_in_errors is later lost for this field (LRN-320 pattern: an SI annotation without a proving test).
- fix: Use distinctive bad values (e.g. '-98765', 'abcSENTINEL' / 'zzzMARKER') and assert that neither the value nor 'input_value' appears in str(exc_info.value), while 'AGENT_SDK_AGUI_MAX_MESSAGE_CHARS' still does.
- sdkCandidate: true

### RT-009
- severity: low
- file: tests/test_gh152_idp_no_secret_leak.py
- source: r2 RT-005
- description: test_uvicorn_access_log_strips_oauth_query (line 167) reads filters from the process-global 'uvicorn.access' logger and does not clear them before build_app. If any earlier test calls configure_access_log_filter() directly, the test still passes after build_app stops installing the filter. The AC 'after build_app' is therefore not proven on its own.
- fix: In a fixture, remove every filter with _agent_sdk=True from logging.getLogger('uvicorn.access') (and restore on teardown). Then build the app and assert exactly one SDK filter is present before rendering the record.
- sdkCandidate: true
