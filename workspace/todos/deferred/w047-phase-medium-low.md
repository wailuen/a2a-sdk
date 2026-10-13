wave: w047
scope: phase
date: 2026-10-13

Non-blocking — these did not block w047's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every phase redteam round. Where several rounds raised the same
finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. sdkCandidate is true if any merged round marked it true. The IDs below are renumbered
for this note; they do not match any single round's IDs. Some later rounds saw partial fixes; where the
code moved between rounds, the entry says so.

## Findings

### RT-001
- severity: medium
- file: workspace/todos/deferred/w042-group-A2-medium-low.md
- description: Raised in five rounds. GH-166 AC "w042 RT-009 deferred entries cross-referenced as resolved" is only partly met. Only w042-phase-medium-low.md RT-027 got a RESOLVED line. The RT-009 entries the AC actually names (uvicorn access log records /oauth/idp/callback code and state) are still open with no cross-reference: w042-group-A2-medium-low.md ~line 28 (index) and ~411 ("R5 RT-009"), and w042-group-A2-budget-exhausted.md ~62. The CHANGELOG Security entry cites only RT-027. They will come back as open backlog.
- fix: Add a 'status: RESOLVED (GH-166)' line to each of the three entries, the same way RT-027 was marked. Declare both files on the GH-166 Modifies: line. Optionally cite both IDs in the CHANGELOG Security entry.
- codify: When an AC names deferred-finding IDs, grep every deferred file for the finding text, not just one renumbered copy.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/auth/oauth_tokens.py
- description: Raised in five rounds. revoke_user() (~line 514-530, GH-163) deletes refresh families and this process's access tokens, but leaves the user's unredeemed auth codes in self._codes (each _AuthCode carries `user`, CODE_TTL_SECONDS = 300) and any pending IdP consent ticket. A code minted, or a consent clicked, just before the admin revoke can still be exchanged at /oauth/token, which mints a brand-new refresh family with a full SESSION_HOURS lifetime. That silently undoes the revocation, and the admin sees the user reappear in the list.
- fix: In revoke_user, also pop every self._codes entry whose .user equals the target, and drop pending consent tickets for that user (expose a way on IdpFlowStore), or record a per-user revoked_at and refuse code exchange/consent for codes or tickets issued before it. Include them in the count/log. Add a test: mint_code(user=X), revoke_user(X), then consume_code -> None / token exchange -> invalid_grant.
- codify: Revoke-by-identity must cover every credential stage that carries the identity (codes, consent tickets, refresh, access), not only the long-lived ones.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/auth/oauth_tokens.py
- description: Raised in three rounds. list_identities() takes 'earliest_created' from the live (non-rotated) refresh row's created_at. mint_token_pair sets created_at=now on every rotation, so the value is the last refresh time, not when the family started. The console labels it 'First sign-in' (console.js renderSignedInUsers, ~567), so a user signed in 29 days ago looks freshly signed in. The GH-163 AC asks for 'earliest created'.
- fix: Store family_created_at when a family is first minted and copy it through rotate_refresh (as family_expires_at is). Report min(family_created_at). Add a test that rotates and asserts earliest_created is unchanged. Otherwise rename the field and column to 'Last refreshed'.
- sdkCandidate: true

### RT-004
- severity: low
- file: agent_sdk/auth/oauth_tokens.py
- description: Raised in two rounds. revoke_user deletes the user's refresh records in one full scan, then calls revoke_family per family, and each call re-lists and re-reads every NS_OAUTH_REFRESH record: O(families x records) store reads. It runs synchronously inside an async admin route; on the Azure Table backend each read is blocking network I/O on the event loop.
- fix: Collect the user's family ids and delete every matching record in one list_fields sweep, then purge in-memory access tokens by family or user once without re-scanning. Consider run_in_threadpool for the store work.
- sdkCandidate: true

### RT-005
- severity: medium
- file: agent_sdk/routes/admin.py
- description: Raised in four rounds. DELETE /admin/api/oauth/identities/{user} uses a plain path parameter. For generic OIDC issuers Identity.user is the raw `sub`, which may contain '/' (URL-shaped subs are allowed). Starlette percent-decodes %2F before routing, so the request 404s. Verified: user 'https://idp.example/users/42' gave 404 and stayed in list_identities(). The console Revoke button fails the same way.
- fix: Declare the route as `/admin/api/oauth/identities/{user:path}` (or take the user in a query or body field). Add a test in tests/test_gh163_revoke_user.py that revokes a user id containing '/'.
- codify: Admin routes keyed on an IdP-issued identifier must accept any character that identifier allows, '/' included; use a path converter or a body field, never a bare path segment.
- sdkCandidate: true

### RT-006
- severity: low
- file: agent_sdk/routes/admin.py
- description: Raised in two rounds. revoke_oauth_identity echoes the caller-supplied path value raw in the response ({'user': user}), though the C-007 annotation says never log or echo it raw. Early rounds saw the log line carry only 'families=%d' (no target, no acting key id); a later round shows it now logs `user=%s families=%d` with a sanitized user. The test makes only negative caplog assertions and never checks that a revocation record was emitted (AC 'log the revocation').
- fix: Echo the sanitized value (safe_error_text / sanitize_text, max_len=128) or omit it. Include the admin key id in the log line if not already. Add a positive assertion (via sdk_caplog) that exactly one revocation record was emitted.
- codify: An admin destructive action needs a positive audit-log test, not only an absence-of-secrets test.
- sdkCandidate: true

### RT-007
- severity: low
- file: tests/test_gh163_revoke_user.py
- description: The GH-163 AC 'refresh after revoke -> invalid_grant' is tested only at the store level (rotate_refresh returns None). No test drives POST /oauth/token grant_type=refresh_token after DELETE /admin/api/oauth/identities/{user} and checks the wire error.
- fix: Add a wire test: mint a pair for user X, call the DELETE route, then POST /oauth/token with the old refresh_token and assert 400 with error=invalid_grant.
- sdkCandidate: true

### RT-008
- severity: medium
- file: agent_sdk/app.py
- description: Raised in four rounds, in two directions. Early rounds: _warn_single_replica_required (~559-571) fired only when oauth_idp=oidc or oauth_one_time_consent was on, though the OAuth server is always mounted (app.py:907) and default admin-gated OAuth (the normal Claude.ai connector path) also keeps auth codes and access tokens per-process, so a shared Azure store with defaults and 2 replicas broke sign-in with no warning. The code was then changed to warn on every shared store. Later rounds: that now contradicts the ruled GH-162 AC ("no warning when sign-in is off ... Tests for each case"; issue 162 ruling: "when a shared store is configured with OAuth/IdP on"). There is no recorded ruling update, the todo AC still says the opposite, test_warns_for_shared_store_with_default_oauth_mode asserts the opposite of the AC, pure API-key A2A/AG-UI operators get a WARNING they cannot silence, and the AZURE_STORAGE_ACCOUNT_NAME branch has no test.
- fix: Record the deviation as a maintainer-ratified comment on GH-162 (per the self-signoff rule) and update the todo AC; or gate the warning on real OAuth use (oauth_idp != 'none', one-time consent, registered OAuth clients or MCP exposure) and add the 'sign-in off -> no warning' test. Add a test for the account-name branch. Optionally reword the warning so API-key-only A2A deployments see conditional advice.
- codify: When a ruling says 'when feature X is on' and X is always mounted, either the condition is 'always' or the narrowing needs a ruling; both a silent narrowing and a silent widening of a ruled AC are wave self-signoffs (LRN-319).
- sdkCandidate: true

### RT-009
- severity: medium
- file: docs/deployment.md
- description: Raised in four rounds. The GH-162 replica guidance contradicts itself. Early text said 'If sign-in is off (API keys only), more than one replica is possible', which is wrong for any MCP client or OAuth connector (MCP sessions in routes/mcp.py _sessions are per-process with any auth; unknown Mcp-Session-Id -> 404) and contradicted the doc's own Known-limitations entry. After rewording, item 1 (~line 10) still says 'With OAuth or IdP sign-in on, run exactly one replica', as does the config.py _deployment_invariants comment, while the Replicas section says the OAuth server is always mounted. The '## Azure Container Apps + multi-replica' heading still pitches multi-replica. The bullet 'Access logs keep no sign-in secrets only inside uvicorn.' is garbled.
- fix: Use one rule everywhere, the warning wording ('serving /mcp or OAuth connectors requires exactly one replica; only pure A2A/AG-UI API-key traffic tolerates more'). Apply it to item 1, the Replicas section and the config.py comment. Rename the section to 'Azure Table Storage backends'. Reword the access-log bullet, e.g. 'uvicorn access log: /oauth/ query strings are stripped'.
- sdkCandidate: true

### RT-010
- severity: medium
- file: workspace/todos/deferred/gh162-shared-oauth-state.md
- description: Raised in two rounds. The plan's 'Reuses: C-024' annotation on GH-162 requires the deferred note to name the planned C-024 BoundedTtlSingleUseStore (and its C-028 per-source quota option) as the abstraction to back with a shared store. The note names neither C-024, C-028 nor BoundedTtlSingleUseStore and describes a free-standing design.
- fix: Add a line saying shared sign-in storage must be built by backing C-024 BoundedTtlSingleUseStore (agent_sdk/common/bounded_store.py, planned), with the C-028 per-source quota for IdP flows, on a shared backend that does atomic conditional delete. It is the single abstraction for IdP flows, codes, consent tickets and MCP sessions.
- codify: A Reuses: C-NNN directive on a docs-only deliverable is met only when the doc names that component.
- sdkCandidate: true

### RT-011
- severity: medium
- file: tests/test_gh162_single_replica_warning.py
- description: Raised in two rounds. The SI-2 annotation required a test that the warning text holds no part of a marker connection string; none asserts that (AZURITE is never checked against the message). `_boot` wraps build_app() in `except Exception: pass`; build_app actually fails with ServiceRequestError after a real network attempt to Azurite. The 'no warning' cases become vacuous if anything above _warn_single_replica_required raises or the call moves below _build_credential_store, and the tests depend on network behavior. The `caplog` parameter is unused.
- fix: Use a marker secret in the connection string (e.g. AccountKey=MARKERxyz...) and assert neither the marker, its head/tail, nor the account name appears in any captured record. Call agent._warn_single_replica_required() directly, or stop at the credential-store build with a narrow expected exception type.
- sdkCandidate: true

### RT-012
- severity: medium
- file: CHANGELOG.md
- description: Raised in two rounds (also against DESIGN.md / docs/content-types.md as reference). The GH-167 entry says the renderers use safe_line_text for '... EntityList item names and summaries, and `EmailList` previews'. The code still renders EmailList.preview with _sanitize_cell (agent_sdk/models/content_types.py ~1124), and DESIGN.md §4.0 and docs/content-types.md say preview deliberately keeps safe_cell_text. The release notes contradict the code.
- fix: Remove 'and `EmailList` previews' from the safe_line_text list. Add EmailList.preview to the 'keep safe_cell_text' exceptions next to the KpiCard and ComparisonTable titles.
- codify: CHANGELOG lists of affected call sites must be checked against the landed code (grep each named site), not against the draft plan.
- sdkCandidate: true

### RT-013
- severity: medium
- file: CHANGELOG.md
- description: Raised in two rounds. The GH-167 text-format changes are filed under '### Changed', not '### 🔴 Breaking changes'. EntityList to_plain_text moves '  - Name (id)' to '  - Name' plus '    id: <id>', breaking the documented GH-156 text fallback that MCP tools/call text, the A2A TextPart and the admin try-tool carry (the entry itself says parsers must change). It also changes MarketBriefing.to_markdown(), which DESIGN.md §4 names as the A2UI wire data value (Standard Profile stable core). Separately, GH-161 is a voluntary stable-core break of BaseAgentSettings boot behavior, so per §4.0 the next release must not be a patch bump (LRN-153/LRN-321).
- fix: Move the GH-167 format change under '### 🔴 Breaking changes' with a **Migration:** line (read the '    id:' line under each '  - ' item; name MarketBriefing.to_markdown() and the per-type layouts), citing GH-156 / DESIGN §4.0. Release as 0.12.0 (minor in 0.x), not 0.11.1.
- codify: A changed wire value of a Standard Profile type is a breaking change for CHANGELOG purposes even when its JSON type is unchanged.
- sdkCandidate: true

### RT-014
- severity: low
- file: CHANGELOG.md
- description: Raised in four rounds. Wording does not match the code: (a) GH-162 appears twice in [Unreleased] (Security ~line 22 and Fixed ~line 27) with overlapping text, and the Security entry says the warning 'now fires' as if it already existed; (b) the GH-163 entry says 'the revocation is logged with the count only', but admin.py:331 logs `user=%s families=%d`; (c) the GH-163 caveat says 'with several workers', but WEB_CONCURRENCY > 1 is refused at boot, so the real case is several replicas.
- fix: Merge the two GH-162 bullets into one under Fixed (or Changed). Say the log line carries the sanitized user id and family count, never token material. Change 'workers' to 'replicas'.
- sdkCandidate: true

### RT-015
- severity: low
- file: CHANGELOG.md
- description: Raised in five rounds (filed against CHANGELOG.md, harness/workflows/wave-cycle.js and .claude/workflows/sdk-wave.js). Two runner behavior changes landed undeclared: SHARED_TREE_GIT_BAN (RT-003 origin), now appended to every agent prompt in sdk-wave.js and all wave-cycle.js copies, and the Archive gate that now treats unpushed template commits as offending paths (RT-001 origin). Neither is in any w047 todo AC nor in the CHANGELOG (LRN-267/LRN-322).
- fix: Add one CHANGELOG [Unreleased] line for each (Fixed/Changed), citing w047 RT-003 and RT-001, and cite them in the GH-164 todo body, or split them into their own tracked item.
- sdkCandidate: true

### RT-016
- severity: low
- file: harness/workflows/wave-cycle.js
- description: SHARED_TREE_GIT_BAN (line ~665) is appended to every prompt in callAgent (~698), including the parse:scope-scan prompt. That prompt ends in a shell heredoc ('PY') and says 'Run this script exactly as written', so rule text with backticked `git stash`/`git reset` lands right after the heredoc terminator. An agent that pastes the prompt tail into bash would run those as command substitutions. Same in sdk-wave.js and the mirrors.
- fix: Prepend the ban before the prompt body, or fence the scan script in a clearly delimited code block and say only the fenced block is to be run.
- sdkCandidate: true

### RT-017
- severity: medium
- file: agent_sdk/common/redact.py
- description: safe_line_text defaults to max_len=256 and cuts with no marker (safe_error_text slices value[:max_len]). EntityList summaries and the TimeSeries/Bar/Waterfall/MultiCategory/EntityList titles used to render full length through safe_cell_text(max_len=None). They are now silently cut at 256 chars in the A2A TextPart and MCP text — the same lost-tail failure GH-168 fixes for AG-UI history. The CHANGELOG does not mention the new truncation.
- fix: Pass max_len=None from _sanitize_line for summaries and titles (keeping the line-break collapse), or add an explicit '…' marker when cutting. Add a CHANGELOG note and a test that a 300-char summary is not silently cut.
- sdkCandidate: true

### RT-018
- severity: medium
- file: agent_sdk/common/redact.py
- description: safe_line_text keeps ':' and '|' and relies on the title sitting at column 0 so it cannot look like an indented KpiCard or ComparisonTable row. str.strip() does not remove invisible or blank-looking non-whitespace characters. Verified: KpiCard(title='​  Revenue: 999', ...) renders '​  Revenue: 999\n  Revenue: 100'; U+2800 does the same. The title reads as a forged metric row. Before GH-167, safe_cell_text swapped ':' in the title, so this could not happen.
- fix: In safe_line_text, strip leading default-ignorable and blank-glyph characters before the column-0 guarantee (U+200B-U+200F, U+2060-U+2064, U+FEFF, U+2800, U+3164, U+115F, U+1160, U+FFA0, all Cf). Or keep safe_cell_text for titles above delimited rows (KpiCard, ComparisonTable). Extend test_kpi_title_cannot_forge_metric_row and test_comparison_table_title_cannot_forge_data_row with zero-width and braille-blank prefixes.
- codify: A layout-based anti-forgery rule ('starts at column 0') must also neutralise invisible and blank-rendering code points, not only str.isspace() characters.
- sdkCandidate: true

### RT-019
- severity: medium
- file: agent_sdk/__init__.py
- description: Raised in five rounds (also against agent_sdk/common/redact.py and workspace/components/README.md). safe_line_text (and LINE_TEXT_MAX_LEN) is a new public reusable helper that docs/content-types.md tells third-party ContentModel authors to use. It is not exported from agent_sdk (siblings safe_cell_text, safe_block_text and safe_error_text are, line 23/46 and __all__) and is not registered under C-007 in workspace/components/README.md next to safe_cell_text / safe_id_text (C-030) (Dimension 8: unregistered reusable utility; LRN-185).
- fix: Add safe_line_text to the agent_sdk/__init__.py import and __all__ and extend the public-API export test. Change docs/content-types.md to cite `agent_sdk.safe_line_text`. Add a C-007 sibling registry entry for safe_line_text(value, *, max_len=256, separators="") — standalone slots, 256-char cap, separators kept, no truncation marker — saying when to use it versus safe_cell_text and safe_id_text. Add a CHANGELOG 'Added' line.
- codify: Every sanitiser a public authoring guide tells third parties to use must be exported at top level and registered in the component registry in the same wave.
- sdkCandidate: true

### RT-020
- severity: low
- file: agent_sdk/common/redact.py
- description: The frame_locations docstring still says it is 'Not yet wired into any local dispatch catch-all'. This wave wires it into routes/mcp.py::_dispatch, and admin.py already uses it.
- fix: Update the docstring to list its call sites (mcp.py _dispatch and tools/call, admin.py try_tool) and the SI-2 contract.
- sdkCandidate: true

### RT-021
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in two rounds. The GH-167 ruling names 'as-of headers' and titles as slots that keep ASCII. An early round found MarketBriefing.to_markdown still rendering f'{title} ({as_of})' with _sanitize_cell on both (~853-855), and FundPerformance 'as of {date}' still joined (~1063), noted in CHANGELOG rather than restructured or ruled (LRN-319/323). A later round shows MarketBriefing now emits title and 'as of: X' separated by a single newline, which in markdown is a soft break, so A2UI renderers show 'Title as of: X' on one line, which reads worse than before. FundPerformance status not re-checked.
- fix: Join the MarketBriefing title and as-of lines with a blank line or a markdown hard break ('  \n') in to_markdown() only. Split FundPerformance's as-of onto its own labelled line, or record a maintainer ruling URL that approves keeping it joined. Add a 'Toshiba (Tokyo)' MarketBriefing title test.
- codify: If a ruling lists slot kinds by name, every listed kind must change or the deviation must cite a ruling URL. A CHANGELOG footnote is not approval.
- sdkCandidate: true

### RT-022
- severity: low
- file: tests/test_content_types.py
- description: safe_line_text now renders TimeSeriesChart, WaterfallChart and MultiCategoryChart titles, but the GH-167 tests cover only BarChart and EntityList (LRN-315). The EntityList fallback title _sanitize_cell(f'{entity_type} list') still uses the joined helper on a standalone line.
- fix: Parametrize the standalone-slot test over every type now using safe_line_text (ASCII kept, newline collapsed, length capped). Decide and document whether the EntityList fallback title should use _sanitize_line.
- sdkCandidate: true

### RT-023
- severity: low
- file: DESIGN.md
- description: The §4.0 GH-167 paragraph is garbled. The parenthetical describing safe_line_text '(line-break and control-char collapse, 256-char cap, separators kept)' follows the EmailList.preview clause, so it reads as if the preview keeps separators, the opposite of the code.
- fix: Move the parenthetical to directly after the first mention of `safe_line_text`.
- sdkCandidate: true

### RT-024
- severity: medium
- file: agent_sdk/config.py
- description: GH-160: hide_input_in_errors=True only cleans str(ValidationError). exc.errors() and exc.json() still carry the raw settings dict, including MASTER_KEY. DESIGN.md ('validation errors strip input values') and the CHANGELOG Security entry overstate the protection, and tests/test_config.py checks only str().
- fix: Narrow the CHANGELOG and DESIGN wording (message string is clean; errors()/json() are not; never log them), or wrap settings construction in build_app/the CLI so a ValidationError is re-raised as a ValueError built only from loc and msg. Add a test for the chosen contract.
- sdkCandidate: true

### RT-025
- severity: medium
- file: agent_sdk/routes/ag_ui.py
- description: Raised in three rounds. GH-168 raised the per-message replay cap 8x (4000 to 32000) with no total-history budget (_fold_history ~95; raw_messages[-50:] ~116). With MAX_HISTORY_MESSAGES = 50, folded model input grows from ~200K chars to ~1M chars (~250K tokens), bounded only by the 1 MB body cap. That exceeds many model context windows; AG-UI clients resend full history, so a long thread then fails every turn with RUN_ERROR, which DESIGN.md §5.3 says large-but-valid history must never cause. It also multiplies cost per turn. The CHANGELOG files it under Fixed with no size or Migration note.
- fix: Add a total folded-history budget (e.g. AGENT_SDK_AGUI_MAX_HISTORY_CHARS or a cap derived from max_chars) that drops the oldest whole messages while keeping the leading-user invariant, logging lengths only. Add a test with 50 near-cap messages. Document the worst case and how to restore 4000 in DESIGN.md §5.3 and docs/deployment.md.
- sdkCandidate: true

### RT-026
- severity: low
- file: agent_sdk/routes/ag_ui.py
- description: Raised in seven rounds. `MAX_MESSAGE_CHARS = 32000` (line ~71-72) is now dead: _fold_history takes max_chars as a required argument and the route passes settings.agui_max_message_chars. The constant is public, was quietly changed from 4000 to 32000, and duplicates config.py:240, so the two can drift and any importer or monkeypatcher gets a value that controls nothing. The AC says the setting 'replaces the fixed constant'. (Deferred G3 RT-006 describes an earlier state.)
- fix: Delete MAX_MESSAGE_CHARS, or keep it as a deprecated alias of BaseAgentSettings.model_fields['agui_max_message_chars'].default (or define one shared constant in config.py used as the Field default), and note in the CHANGELOG that AGENT_SDK_AGUI_MAX_MESSAGE_CHARS replaces it.
- sdkCandidate: true

### RT-027
- severity: medium
- file: tests/test_gh168_agui_truncation.py
- description: Raised in two rounds. The GH-168 SI-2 note requires that the truncation warning logs only lengths, the marker holds only the count, and an invalid AGENT_SDK_AGUI_MAX_MESSAGE_CHARS fails boot without echoing its value. test_invalid_setting_fails_boot only checks that ValidationError is raised; no test asserts message content is absent from the warning or the bad value / 'input_value' absent from str(exc). Behavior is correct today by hand check (LRN-128/LRN-292).
- fix: In the over-limit test assert caplog.text has no 'HEAD'/'TAIL-ID' content. Use a marker bad value (e.g. 'abcMARKER') and assert neither it nor 'input_value' appears in str(exc), while AGUI_MAX_MESSAGE_CHARS does.
- codify: Each clause of an SI-2 annotation needs its own negative assertion; a passing positive test does not cover it.
- sdkCandidate: true

### RT-028
- severity: low
- file: docs/protocols.md
- description: The new GH-168 sentence says '>50 messages or messages over AGENT_SDK_AGUI_MAX_MESSAGE_CHARS ... keep head and tail with an omission marker'. The 50-message cap drops the oldest messages; it does not keep head and tail.
- fix: Reword: 'only the most recent 50 messages are kept; a message over AGENT_SDK_AGUI_MAX_MESSAGE_CHARS keeps its start and end with a [... N chars omitted ...] marker'.
- sdkCandidate: true

### RT-029
- severity: low
- file: agent_sdk/observability/logging.py
- description: Raised in three rounds. _OAuthQueryFilter matches only when the logged path (args[2]) starts with '/oauth/'. uvicorn (0.49) builds it as root_path + path, so under --root-path / prefix-routed ingress '/agent/oauth/idp/callback?code=...&state=...' is logged in full. gunicorn+UvicornWorker access lines (gunicorn.access) are not covered either, and the docs do not say so.
- fix: Strip the query when '/oauth/' appears as a path segment anywhere (`'/oauth/' in path.split('?', 1)[0]`), with a test for a prefixed path. Mention gunicorn.access in docs/security.md alongside proxies.
- sdkCandidate: true

### RT-030
- severity: low
- file: docs/security.md
- description: Raised in five rounds. Wording left stale by GH-161/GH-163/GH-164: docs/security.md:43 calls AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE/_REQUIRED_GROUP 'Optional'; :44 says who may sign in is managed in Entra 'not in the SDK'; the 'Removal lag' bullet does not mention the new admin revoke route; DESIGN.md:408 says 'applies the optional required role/group claim'; the ADR a003 settings table still lists both as optional and D13 is not marked superseded; the harness/wave_scope.py docstring lists root-level extensions without .lock or the known dotfiles (LRN-313).
- fix: Reword all of these as 'required unless ALLOW_ALL_ISSUER_USERS=true (D14)' for every oidc issuer. Add '(superseded in part by D14)' to D13. Point Removal lag to GET/DELETE /admin/api/oauth/identities and the console panel, noting access tokens on other replicas stay valid up to 1 hour. Update the wave_scope.py docstring extension list.
- sdkCandidate: true

### RT-031
- severity: medium
- file: tests/test_a2ui_wire.py
- description: Raised in two rounds. The GH-169 regression test (test_system_prompt_forbids_model_written_component_json) ignores the plan's 'Reuses: C-020' annotation: it uses new substring checks and calls neither _declared_wire_keys nor _compact_schema_top_level_keys, so the reworded prompt section can drift from registered ContentModel fields. The section heading is still '## A2UI Output Format'.
- fix: Iterate registered types, rebuild get_system_prompt_section(), and assert _FEW_SHOT_EXAMPLES/_COMPACT_SCHEMAS parity with the C-020 helpers. Rename the heading (e.g. '## A2UI cards (delivered by tools)').
- codify: Check Reuses: directives on test deliverables by confirming the named helper is called in the new test.
- sdkCandidate: true

### RT-032
- severity: low
- file: agent_sdk/a2ui/catalog.py
- description: GH-169 says model-written component JSON must not appear in replies, but the section still shows full JSON few-shot bodies with concrete values, now under 'Reference shapes of tool output (not for you to write)'. Models often copy shown JSON regardless of the heading, which is the root cause of GH-169. The regression test checks wording only.
- fix: Cut the examples down to key lists (the compact schemas already carry required fields), or add an option to leave them out. At least add a test that no example line starts with '{' when allowed_components filters to types whose tools emit them.
- sdkCandidate: true

### RT-033
- severity: medium
- file: harness/workflows/wave-cycle.js
- description: Raised in three rounds (also against .claude/workflows/sdk-wave.js). GH-165 Archive step 1 moves WAVE_FILE (workspace/todos/active/...) to completed/, but step 3 (~2724-2730; sdk-wave.js ~2399) tells the agent to backfill Test: only for test names 'cited in ' + WAVE_FILE, a path that no longer exists. A literal agent finds nothing and leaves every Test: as [pending], so GH-165 quietly does nothing. No pytest pass list reaches the Archive prompt either, so 'exists and passed in this wave' cannot be checked. Same text in the .claude and template mirrors.
- fix: Reference 'workspace/todos/completed/' + WAVE_BASENAME in step 3, or do the Test: backfill before step 1 moves the file. Pass the pre-archive pytest gate's / phase-redteam's passing node ids into the prompt and allow only those (or drop the 'passed' claim). Keep all three wave-cycle.js copies byte-identical, update sdk-wave.js, push the template.
- codify: Archive prompt steps that run after a file move must reference the post-move path, never the pre-move variable.
- sdkCandidate: true

### RT-034
- severity: low
- file: .claude/workflows/sdk-wave.js
- description: The GH-165 AC says 'Phase detail text updated. Same change in sdk-wave.js.' The wave-cycle.js meta Archive detail mentions Implementation: and Test: backfill, but the sdk-wave.js meta Archive detail (line 12) does not mention FR backfill. test_phase_detail_mentions_test_field covers only the wave-cycle copies.
- fix: Update the sdk-wave.js Archive phase detail to mention backfilling FR Implementation: and Test: fields, and add sdk-wave.js to test_phase_detail_mentions_test_field.
- sdkCandidate: true

### RT-035
- severity: medium
- file: harness/wave_scope.py
- description: Raised in five rounds (also against .claude/workflows/sdk-wave.js and tests/test_wave_scope_extraction.py). The GH-164 Parse scope scan is an inline Python copy of _looks_like_path in sdk-wave.js and all three wave-cycle.js copies, with its own extra rule: it rejects any token starting with 'template/'. _looks_like_path accepts them, and test_gh164_known_lockfiles_and_dotfiles_are_scope asserts 'template/.gitignore' and 'template/uv.lock' are scope, though the Parse prompt calls the two 'twins; keep the two in step'. The AC cases (uv.lock, .env.example, src/config.py, rejected tokens) run only against wave_scope.py; the only test that runs the inline script checks just template exclusion, and only from harness/workflows/wave-cycle.js. test_gh164_parse_has_deterministic_scan_and_widened_rule only greps strings like 'scope-scan-mismatch'. No test checks the inline EXT/ROOT/DOT lists against _PATH_EXTENSIONS/_ROOT_LEVEL_EXTENSIONS/_KNOWN_DOTFILES. A regex bug like RT-001 (bare paths -> empty result) would pass CI (LRN-131/137).
- fix: Choose one template/ rule and apply it in both places (fix the parametrize list). Add a parametrized parity test that extracts the inline scan from each runner (sdk-wave.js included), runs it with python3 -I on fixture wave files (backticked, bare planner form, (modifies …) form, [~] todo skip, uv.lock, .env.example, rejected glob, directory, bare extension, template/ path) and asserts its output equals extract_wave_scope. Add a parity test on the EXT/ROOT/DOT lists. Assert the sdk-wave.js script matches byte for byte.
- codify: When a workflow embeds a copy of a Python spec function, a parity test must run both on the same fixtures; prose 'keep in step' notes do not stop drift.
- sdkCandidate: true

### RT-036
- severity: medium
- file: harness/workflows/wave-cycle.js
- description: The deterministic scope scan's ok() drops only `template/` tokens, but the AI Parse prompt tells the model to EXCLUDE 'any path that resolves to another repo'. A Creates:/Modifies: token for a peer repo (e.g. `../a2a-sdk/agent_sdk/config.py`, or a sibling-repo path in an agent repo using wave-cycle.js) passes the scan but is correctly dropped by the AI, so Parse aborts with scope-scan-mismatch on a valid wave file. Same code in .claude/workflows/sdk-wave.js.
- fix: Make the scan's exclusions match the prompt: reject tokens with a `..` segment and list the same peer-repo prefixes in both places, ideally from one constant that builds both the prompt text and the script. Add a subprocess test with a `../peer/x.py` token.
- sdkCandidate: true

### RT-037
- severity: medium
- file: tests/test_wave_scope_extraction.py
- description: Raised in four rounds. Mirror-parity tests repeat the LRN-325 / LRN-226 anti-pattern. test_gh164_workflow_copies_are_byte_identical (~547) compares the template copy only under `if tpl.exists()`; test_gh164_template_mirror_is_committed_and_pushed is skipif'd when template/.git is absent; test_gh165_archive_test_field.py::test_template_archive_step_matches is skipif(template absent). In CI or any checkout without the peer repo, they pass silently even if the mirror drifted — and the template is the third copy the GH-164 AC requires to be byte-identical.
- fix: Fail, or xfail(strict) with an explicit reason, when template/.claude/workflows/wave-cycle.js is absent and the wave declares a template deliverable; or compare against `git show origin/main:` from the template remote. Never pass silently.
- codify: Mirror-sync guards must fail or loudly mark themselves unverified when the peer repo is absent; never pass silently.
- sdkCandidate: true

### RT-038
- severity: medium
- file: harness/skills/wave/SKILL.md
- description: The companion skill still documents the old workflow contract (LRN-086/LRN-229). Line ~102 says Archive updates only FR `Implementation:` fields (no Test: backfill). Step 3's outcome list does not cover the new Parse aborts `scope-scan-failed` and `scope-scan-mismatch`, so the caller may treat them as a normal return and move on to the next wave.
- fix: Update harness/skills/wave/SKILL.md plus the .claude and template mirrors: Archive also backfills Test:, and an `error` return (scope-scan-mismatch or scope-scan-failed, with `missed` paths) stops the run and is reported.
- codify: Every new early-return error code in a workflow must be handled in its companion SKILL.md outcome list in the same wave.
- sdkCandidate: true

### RT-039
- severity: medium
- file: tests/test_gh165_archive_test_field.py
- description: Raised in three rounds. This new untracked test file is not declared in any todo's Creates:/Modifies: line (GH-165 lists only the workflow files and CHANGELOG.md), so the archive commit check, undeclared-path gates and scope-keyed reviews miss it (LRN-168/LRN-207/LRN-322).
- fix: Add `tests/test_gh165_archive_test_field.py` to the GH-165 Creates: line in workspace/todos/active/w047-gh-issues.md and make sure it is committed with the wave.
- codify: Every new test file a todo lands must appear in that todo's Creates: line, or it escapes the scope gates.
- sdkCandidate: true

### RT-040
- severity: medium
- file: tests/test_rt001_agui_stream_no_value_log.py
- description: This untracked regression test for the ag_ui.py stream catch-all change (LRN-214 names it in its Check clause) is not declared on any Creates:/Modifies: line in workspace/todos/active/w047-gh-issues.md. Scope-keyed commit and archive gates will not pick it up, so the LRN-214 regression guard may not land.
- fix: Add it to the GH-168 (or GH-169 RT-001) Modifies: line and make sure it is committed with the wave.
- sdkCandidate: false

### RT-041
- severity: medium
- file: workspace/todos/active/w047-gh-issues.md
- description: Raised in four rounds. This wave ran under the pre-GH-164 Parse (the AC forbids running the new one), so the bug GH-164 fixes narrowed this wave's own review. The computed scope (32 paths) omits 9-10 declared paths that the new deterministic scan finds (40-44 paths): agent_sdk/routes/mcp.py, agent_sdk/console/static/console.js, docs/protocols.md, uv.lock, tests/test_rt001_mcp_dispatch_no_value_log.py, tests/test_ag_ui_group_b.py, tests/test_gh148_reuse_kind_substitution.py, tests/test_gh152_idp_authorize_flow.py, tests/test_gh159_reject_non_text_parts.py, workspace/todos/deferred/w042-phase-medium-low.md. The Archive commit-intent gate, the FR backfill and the undeclared-scope gate key off wave.allScope, so this run will not check those files. One round covered them by hand: full suite 3053 passed, 3 skipped; mypy clean.
- fix: Before /sdk-release, run the extracted scan on w047-gh-issues.md and confirm every path is committed in the release commit (`git status --porcelain` clean for all of them). Backtick the GH-169 RT-001 Modifies line. Note in the archive/closing note that this wave ran under the pre-GH-164 Parse and these paths were reviewed outside the computed scope.
- codify: When a wave fixes the scope parser, the same run's gates still use the old scope, so the release step must re-check commit status against the fixed scan.
- sdkCandidate: true
