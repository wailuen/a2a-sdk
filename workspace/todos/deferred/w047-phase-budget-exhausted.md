wave: w047
scope: phase
date: 2026-10-13
round_count: 8
status: budget-exhausted

## Findings

### RT-001
- status: RESOLVED (manual, 2026-10-13): revoke_user burns the user's auth codes; IdpFlowStore.drop_user drops consent tickets from the admin route; tests in tests/test_gh163_revoke_user.py.
- severity: high
- file: agent_sdk/auth/oauth_tokens.py
- description: [SDK] GH-163 revoke_user() (line 514) drops refresh families and access tokens, but leaves the user's unredeemed auth codes in self._codes (user field set, CODE_TTL) and pending IdP consent tickets in IdpFlowStore._tickets (_CONSENT_TTL 300s, auth/oidc.py:40,414). A user who finished the IdP callback just before the admin revoked them can still click Allow, or redeem an already-issued code at /oauth/token, and gets a brand-new refresh family that lasts the full SESSION_HOURS (default 30 days). For about 5-10 minutes after the revoke, revocation can be fully undone, even though the user can no longer sign in at Entra.
- fix: In revoke_user, also pop every self._codes entry whose rec.user == user. Add an IdpFlowStore method that drops consent tickets for a user, and call it from the admin DELETE route. Better, and covering other replicas too: persist a per-user 'revoked_at' marker in the credential store, and refuse code redemption and refresh rotation for any code or family minted before it. Add a test: mint a code for t1:alice, revoke_user('t1:alice'), then consume_code + mint_token_pair (or POST /oauth/token) must give invalid_grant.
- codify: Revoking a principal must cut off every credential that can still mint a credential (pending codes and consent tickets), not only the tokens that already exist.
- sdkCandidate: true

### RT-002
- status: RESOLVED (manual, 2026-10-13): Archive step 3 now cites workspace/todos/completed/<basename> in all four workflow copies; template 3df3ca6 pushed.
- severity: high
- file: harness/workflows/wave-cycle.js
- description: [SDK] GH-165 Archive step 3 (line 2730; same in .claude/workflows/wave-cycle.js, template mirror, and .claude/workflows/sdk-wave.js:2399) fills Test: only if 'the test name must be cited in ' + WAVE_FILE. But step 1 of the same prompt (lines 2718-2722) has already moved WAVE_FILE (workspace/todos/active/...) to workspace/todos/completed/. The agent is told to check a file that no longer exists, so the backfill either leaves every Test: as [pending] or depends on the agent guessing. The GH-165 AC is not reliably met.
- fix: In step 3, cite the post-move path: 'workspace/todos/completed/' + WAVE_BASENAME. Or read the test names before step 1 moves the file. Apply the fix to all three wave-cycle.js copies (commit and push the template) and to sdk-wave.js. Extend the static test in tests/test_wave_scope_extraction.py to assert step 3 names the completed/ path.
- codify: A multi-step agent prompt must not point a later step at a path an earlier step moves; name the path the file has after the move.
- sdkCandidate: true

### RT-003
- status: RESOLVED (manual, 2026-10-13): release committed every dirty and untracked path (git add -A), not the narrowed allScope.
- severity: high
- file: .claude/workflows/sdk-wave.js
- description: [SDK] The sdk-wave.js instance running this wave still uses the old AI-only Parse (GH-164 was fixed mid-wave), and the review scope it passed here leaves out 11 declared paths. The fixed deterministic scan of the same wave file finds them: agent_sdk/console/static/console.js, agent_sdk/routes/mcp.py, tests/test_rt001_mcp_dispatch_no_value_log.py, tests/test_gh152_idp_authorize_flow.py, tests/test_ag_ui_group_b.py, tests/test_gh148_reuse_kind_substitution.py, tests/test_gh159_reject_non_text_parts.py, docs/protocols.md, uv.lock, workspace/todos/deferred/w042-phase-medium-low.md and template/.claude/skills/setup/SKILL.md. The archive commit and undeclared-scope gates key off that narrowed allScope, so the release can ship without the GH-163 console panel, the RT-001 mcp.py logging fix and the uv.lock resync, or leave them uncommitted.
- fix: Before archive and release, compute scope with harness/wave_scope.extract_wave_scope(w047 file), plus tests/test_rt001_agui_stream_no_value_log.py (see RT-004). Check that every dirty or untracked path in git status is in that set and gets committed. Do not trust the running instance's allScope for this wave.
- codify: A wave that fixes its own workflow script still runs on the old script; recompute its scope with the fixed logic before archive and release.
- sdkCandidate: true

### RT-004
- status: RESOLVED (manual, 2026-10-13): committed with the v0.12.0 work commit.
- severity: medium
- file: tests/test_rt001_agui_stream_no_value_log.py
- description: This untracked regression test, for the ag_ui.py stream catch-all change (LRN-214, which names it in its Check clause), is not declared on any Creates:/Modifies: line in workspace/todos/active/w047-gh-issues.md. Scope-keyed commit and archive gates will not pick it up, so the LRN-214 regression guard may not land.
- fix: Add tests/test_rt001_agui_stream_no_value_log.py to the GH-168 (or GH-169 RT-001) Modifies: line, and make sure it is committed with the wave.
- sdkCandidate: false

### RT-005
- severity: medium
- file: agent_sdk/routes/ag_ui.py
- description: [SDK] GH-168 raised the per-message replay cap 8x (4000 to 32000) with no total-history budget (_fold_history line 95; raw_messages[-50:] at line 116). Folded model input grows from about 200K chars to about 1M chars, bounded only by the 1 MB body cap. That is above many model context windows. AG-UI clients resend full history, so a long thread then fails every turn with RUN_ERROR. DESIGN.md §5.3 says large-but-valid history must never cause that. The CHANGELOG files it under Fixed with no size or Migration note.
- fix: Add a total folded-history budget (for example AGENT_SDK_AGUI_MAX_HISTORY_CHARS, or a cap derived from max_chars) that drops the oldest whole messages while keeping the leading-user invariant, logging lengths only. Add a test with 50 messages at the cap. Document the worst case and how to restore 4000 in DESIGN.md §5.3 and docs/deployment.md.
- sdkCandidate: true

### RT-006
- severity: medium
- file: workspace/todos/deferred/w042-group-A2-medium-low.md
- description: The GH-166 AC asks for the 'w042 RT-009 deferred entries' to be cross-referenced as resolved. Only w042-phase-medium-low.md RT-027 got a RESOLVED line. The actual RT-009 entries for the uvicorn access-log code/state leak are still open: w042-group-A2-medium-low.md:28 and :411, and w042-group-A2-budget-exhausted.md:62. They will come back as open backlog.
- fix: Add 'status: RESOLVED (GH-166) ...' to those three entries, and add both files to the GH-166 Modifies: line.
- sdkCandidate: false

### RT-007
- status: RESOLVED (manual, 2026-10-13): maintainer accepted the deviation, https://github.com/wailuen/a2a-sdk/issues/162#issuecomment-6142451447; account-name test added.
- severity: medium
- file: agent_sdk/app.py
- description: [SDK] GH-162 AC: 'no warning when sign-in is off ... Tests for each case'. _warn_single_replica_required (around line 559) instead warns on every shared store, arguing that the OAuth server is always mounted. That may be the right engineering call, but it changes a ruled AC (issue 162 ruling: 'when a shared store is configured with OAuth/IdP on'). There is no recorded ruling update, and the todo AC text still says the opposite. The AZURE_STORAGE_ACCOUNT_NAME branch has no test.
- fix: Record the deviation as a maintainer-ratified comment on GH-162 (per the self-signoff rule) and update the todo AC. Add a test for the account-name branch. Optionally reword the warning so API-key-only A2A deployments see the conditional advice.
- sdkCandidate: true

### RT-008
- severity: medium
- file: workspace/components/README.md
- description: [SDK] The new public helper agent_sdk/common/redact.py::safe_line_text (and LINE_TEXT_MAX_LEN), which docs/content-types.md tells domain-card authors to use, is not in the component registry under C-007 next to safe_id_text and safe_cell_text. Unregistered reusable utility (Dimension 8).
- fix: Add a C-007 sub-entry for safe_line_text(value, *, max_len=256): a standalone-slot wrapper over safe_error_text, separators kept, with no truncation marker.
- sdkCandidate: true

### RT-009
- status: RESOLVED (manual, 2026-10-13): CHANGELOG wording fixed and GH-162 entries merged.
- severity: low
- file: CHANGELOG.md
- description: [SDK] The GH-163 entry (line 10) says the revocation 'is logged with the count only', but routes/admin.py logs user=<sanitized user> as well. GH-162 appears twice in [Unreleased] (Security line 22 and Fixed line 27) with overlapping text.
- fix: Change to 'logged with the sanitized user id and the family count, never token material'. Merge the two GH-162 entries into one.
- sdkCandidate: true

### RT-010
- severity: low
- file: docs/protocols.md
- description: [SDK] The new GH-168 sentence says '>50 messages or messages over AGENT_SDK_AGUI_MAX_MESSAGE_CHARS ... keep head and tail with an omission marker'. The 50-message cap drops the oldest messages; it does not keep head and tail. Also, MAX_MESSAGE_CHARS = 32000 (agent_sdk/routes/ag_ui.py:72) is now dead and duplicates the settings default, against the AC that says the setting 'replaces the fixed constant'.
- fix: Reword: 'only the most recent 50 messages are kept; a message over AGENT_SDK_AGUI_MAX_MESSAGE_CHARS keeps its start and end with a [... N chars omitted ...] marker'. Remove the dead constant, or make it the single source for the Field default.
- sdkCandidate: true

### RT-011
- severity: low
- file: harness/workflows/wave-cycle.js
- description: [SDK] SHARED_TREE_GIT_BAN (line 665) is appended to every prompt in callAgent (line 698), including the parse:scope-scan prompt. That prompt ends in a shell heredoc ('PY') and tells the agent to 'Run this script exactly as written'. So rule text containing backticked `git stash`/`git reset` comes right after the heredoc terminator. An agent that pastes the prompt tail into bash would run those as command substitutions. Same in sdk-wave.js and the mirrors.
- fix: Put the ban before the prompt body (prepend), or fence the scan script in a clearly delimited code block and say that only the fenced block is to be run.
- sdkCandidate: true

## Instruction

Fix remaining findings, then re-run /wave w047.
