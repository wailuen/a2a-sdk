# SDK issue candidates — w047 (2026-10-13)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GH-160 lost from tree: BaseAgentSettings.model_config lacks hide_input_in_errors=True, so validation errors print secret input values (MASTER_KEY tail). tests/test_config.py fails 3/3; no CHANGELOG Security entry.
- Severity: critical
- Component: security
- File: agent_sdk/config.py
- Rationale: SDK settings internals; secret leak in logs (SI-2) breaks DESIGN.md promise. Release blocker.

## Candidate 2: GH-161 lost from tree: _validate_idp_settings still exempts GUID-pinned Entra issuers, so an oidc issuer with no REQUIRED_ROLE/GROUP/opt-out boots and admits every tenant member and guest. Old exemption test still pinned; ADR, docs, setup skill, CHANGELOG missing; harness vs template setup skill copies differ.
- Severity: critical
- Component: protocol/oauth
- File: agent_sdk/app.py
- Rationale: SDK OAuth/IdP sign-in gate in protocol routes boot path; contradicts maintainer ruling.

## Candidate 3: Wave agents ran git stash/reset in the shared working tree, wiping G1 group work (GH-160/161/164); dangling stashes 956125b/e7fe843 never restored. Workflow prompts do not ban stash/reset/checkout/restore and no post-group gate checks every declared path has a diff.
- Severity: critical
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Harness wave workflow design flaw that silently loses uncommitted work across parallel groups.

## Candidate 4: GH-164 lost from tree: _looks_like_path still rejects uv.lock/.env.example/.gitignore, no deterministic Creates:/Modifies: scan in Parse phase, no tests or CHANGELOG; template copy has GH-164 so wave-cycle.js copies are not byte-identical.
- Severity: high
- Component: harness/workflow
- File: harness/wave_scope.py
- Rationale: Harness scope extraction and workflow scripts; mirror drift with template.

## Candidate 5: GH-164 Parse scope scan keeps template/ (other-repo) paths and either/or clause paths that the AI Parse prompt is told to exclude, so every wave listing a template mirror aborts with scope-scan-mismatch.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/wave-cycle.js
- Rationale: Harness workflow cross-check uses different inclusion rules than the AI prompt; false hard aborts.

## Candidate 6: GH-167 moved KpiCard and ComparisonTable titles to safe_line_text, which keeps ':' and '|', so a hostile title forges a metric line ('Revenue: 999999') or a table row. Falsifies DESIGN.md:214 and CHANGELOG claim; no per-renderer forgery test.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK content_types text renderers; prompt-injection row forgery to the model.

## Candidate 7: Template peer repo has uncommitted, unpushed wave-cycle.js (RT-003 shared-tree git ban hunk); pushed template main differs from harness copy, so seeded agent repos lack the ban. Local byte-identity test passes regardless.
- Severity: high
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: Template scaffold delivery gap (LRN-071).

## Candidate 8: GH-167 renders EmailList.preview via safe_line_text, so an outside sender's preview can forge a full email row including a fake '(id: ..., conversation: ...)' pair, reopening the GH-156 attacker-id risk. Docs falsely claim standalone slots cannot forge rows; no hostile-preview test.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK content_types sanitization; untrusted email content can steer model tool calls.

## Candidate 9: GH-168 AGENT_SDK_AGUI_MAX_MESSAGE_CHARS wiring into /ag-ui/run (_fold_history call) is untested; helper default equals setting default, so broken wiring stays green.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: Protocol route setting wiring with no route-level test (LRN-304).

## Candidate 10: Wave changed files not named by explicit path in any todo Creates:/Modifies: (console.js, docs/protocols.md, uv.lock, several tests, w042 deferred note), so they escape wave scope and scope-keyed gates; directory-only scope declarations are silently dropped.
- Severity: high
- Component: harness/workflow
- File: agent_sdk/console/static/console.js
- Rationale: Harness wave scope/gating process gap (LRN-207/LRN-322).

## Candidate 11: GH-167 EntityList item name/summary via safe_line_text keep ':', so a hostile value writes extra 'id: ...' claims next to the real id; test only checks exact four-space prefix lines.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK content_types id forgery to the model; breaks GH-167 AC and DESIGN.md §4.0.

## Candidate 12: GH-162 SI-2 annotation requires a no-leak test proving the single-replica WARNING omits connection-string/account/key/prefix markers; none exists.
- Severity: high
- Component: security
- File: tests/test_gh162_single_replica_warning.py
- Rationale: Missing required SDK security test for log leakage.

## Candidate 13: MCP JSON-RPC _dispatch catch-all uses logger.exception, so a ValidationError from tool result rendering logs input_value (tool output) and traceback. Deferred as medium despite critical LRN-214.
- Severity: critical
- Component: security
- File: agent_sdk/routes/mcp.py
- Rationale: Protocol route log leak of tool output (SI-2); severity inherited from critical learning.

## Candidate 14: GH-167 does not follow maintainer ruling (standalone names/summaries keep ASCII): code, tests, CHANGELOG and DESIGN.md §4.0 disagree about which slots use safe_line_text; narrowing not ratified.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK content_types sanitizer behavior and docs mismatch an unratified ruling narrowing (LRN-319/323).

## Candidate 15: _warn_single_replica_required only warns for oidc IdP or one-time consent, but the OAuth server and MCP sessions are always per-process; Azure Table multi-replica deployments with default connector OAuth/MCP get no warning. docs/deployment.md wrongly says API-key-only can run multiple replicas and misstates revoke lag.
- Severity: high
- Component: protocol/oauth
- File: agent_sdk/app.py
- Rationale: SDK OAuth/MCP deployment safety warning and docs misstate runtime behavior.

## Candidate 16: Reuses: directives unmet: gh162 note ignores C-024/C-028; admin DELETE /admin/api/oauth/identities/{user} echoes user raw without sanitize_text (C-007); GH-169 test doesn't use C-020 helpers.
- Severity: high
- Component: security
- File: workspace/todos/deferred/gh162-shared-oauth-state.md
- Rationale: SDK admin route echoes untrusted input unsanitized; component-reuse ACs not met.

## Candidate 17: GH-164 scope scan only extracts backticked tokens, but the planner's documented todo format writes bare comma-separated paths, so the scan returns [] for agent-repo waves and the guard never fires; also misses bold **Creates:** form.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/wave-cycle.js
- Rationale: Harness workflow guard is a no-op for the harness's own planner format.

## Candidate 18: GH-167 implements ruling for only EntityList and some chart titles; MarketBriefing as-of header, KpiCard/ComparisonTable titles, UserList/UserProfile/DocumentList/CalendarEvents names still use safe_cell_text with no ratification recorded.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK content_types ruling narrowing without maintainer approval (LRN-319/323).

## Candidate 19: Bare-path scope-scan fix exists only in template working tree; pushed template a7bd017 still has backtick-only scan, so downstream agent repos get a no-op guard. Byte-identity test reads local copy and passes.
- Severity: high
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: Template scaffold not delivered; mirror check compares wrong source.

## Candidate 20: KpiCard and ComparisonTable titles call _sanitize_line with separators=':'/'|', swapping ASCII the ruling says to keep ('only line-break/control-char collapse applies'); no ratification URL.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: SDK content_types deviates from maintainer ruling; layout-based defense would satisfy both.

## Candidate 21: AG-UI stream catch-all still uses logger.exception('ag-ui stream failed'); a ValidationError from payload.wire()/translate() logs tool output input_value via traceback.
- Severity: high
- Component: security
- File: agent_sdk/routes/ag_ui.py
- Rationale: Protocol route log leak (SI-2), same LRN-214 pattern fixed in mcp.py.

## Candidate 22: GH-163 revoke_user drops tokens/refresh families but leaves unredeemed auth codes and pending IdP consent tickets, so a revoked user can mint a fresh 30-day refresh family within ~5-10 minutes.
- Severity: high
- Component: protocol/oauth
- File: agent_sdk/auth/oauth_tokens.py
- Rationale: SDK OAuth revocation bypass.

## Candidate 23: GH-165 Archive step 3 checks test names in WAVE_FILE after step 1 already moved it to workspace/todos/completed/, so Test: backfill is unreliable. Same in .claude copies, template and sdk-wave.js.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/wave-cycle.js
- Rationale: Harness workflow prompt points at a moved path.

## Candidate 24: Running sdk-wave.js used old AI-only Parse; allScope omits 11 declared paths (console.js, routes/mcp.py, uv.lock, tests, docs/protocols.md, etc.), so archive/release gates can ship without or leave uncommitted those changes.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: Harness workflow scope computation gap affecting release gating.

## Candidate 25: CalendarEvent.location: Standard Profile v1.1 requires display_name and is_online; EventLocation model and compact schema (catalog.py:229) mark them optional, so payloads missing them pass and fail structural validation in renderers.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/a2ui/catalog.py
- Rationale: A2UI catalog/content_types field contract drift from Standard Profile.
