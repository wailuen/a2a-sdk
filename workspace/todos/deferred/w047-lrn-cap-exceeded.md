wave: w047
scope: lrn-cap-exceeded
date: 2026-10-13
MAX_LRN_PER_WAVE: 20
status: non-blocking (fixed, not codified)

These findings were already fixed but not codified as LRN files due to the 20-per-wave cap. Review and codify opportunistically, or fold into a future wave.

Count: 5 findings over the cap.

## RT-001 (high) — sdkCandidate

- File: `agent_sdk/routes/ag_ui.py`
- Description: The AG-UI stream catch-all still calls logger.exception("ag-ui stream failed") (line ~741). This is the same LRN-214 pattern this wave fixed in mcp.py::_dispatch (RT-001). Inside that try, mapper.map() calls payload.wire() and translate() (lines ~386 and ~398). A domain ContentModel or custom translator that raises pydantic ValidationError puts input_value='<tool output>' into the log through the traceback and message (SI-2).
- Fix: Replace logger.exception with logger.error("ag-ui stream failed type=%s at=%s", type(exc).__name__, frame_locations(exc)), as mcp.py does. Add a test like tests/test_rt001_mcp_dispatch_no_value_log.py that monkeypatches a content model's wire() to raise a ValidationError holding a marker, then asserts the marker is absent from caplog.
- Codify: LRN-214's Check greps only mcp.py/admin.py. Every catch-all around content rendering (wire/translate/to_plain_text), including routes/ag_ui.py and the A2A stream, must log type and frame locations only.

## RT-001 (high) — sdkCandidate

- File: `agent_sdk/auth/oauth_tokens.py`
- Description: [SDK] GH-163 revoke_user() (line 514) drops refresh families and access tokens, but leaves the user's unredeemed auth codes in self._codes (user field set, CODE_TTL) and pending IdP consent tickets in IdpFlowStore._tickets (_CONSENT_TTL 300s, auth/oidc.py:40,414). A user who finished the IdP callback just before the admin revoked them can still click Allow, or redeem an already-issued code at /oauth/token, and gets a brand-new refresh family that lasts the full SESSION_HOURS (default 30 days). For about 5-10 minutes after the revoke, revocation can be fully undone, even though the user can no longer sign in at Entra.
- Fix: In revoke_user, also pop every self._codes entry whose rec.user == user. Add an IdpFlowStore method that drops consent tickets for a user, and call it from the admin DELETE route. Better, and covering other replicas too: persist a per-user 'revoked_at' marker in the credential store, and refuse code redemption and refresh rotation for any code or family minted before it. Add a test: mint a code for t1:alice, revoke_user('t1:alice'), then consume_code + mint_token_pair (or POST /oauth/token) must give invalid_grant.
- Codify: Revoking a principal must cut off every credential that can still mint a credential (pending codes and consent tickets), not only the tokens that already exist.

## RT-002 (high) — sdkCandidate

- File: `harness/workflows/wave-cycle.js`
- Description: [SDK] GH-165 Archive step 3 (line 2730; same in .claude/workflows/wave-cycle.js, template mirror, and .claude/workflows/sdk-wave.js:2399) fills Test: only if 'the test name must be cited in ' + WAVE_FILE. But step 1 of the same prompt (lines 2718-2722) has already moved WAVE_FILE (workspace/todos/active/...) to workspace/todos/completed/. The agent is told to check a file that no longer exists, so the backfill either leaves every Test: as [pending] or depends on the agent guessing. The GH-165 AC is not reliably met.
- Fix: In step 3, cite the post-move path: 'workspace/todos/completed/' + WAVE_BASENAME. Or read the test names before step 1 moves the file. Apply the fix to all three wave-cycle.js copies (commit and push the template) and to sdk-wave.js. Extend the static test in tests/test_wave_scope_extraction.py to assert step 3 names the completed/ path.
- Codify: A multi-step agent prompt must not point a later step at a path an earlier step moves; name the path the file has after the move.

## RT-003 (high) — sdkCandidate

- File: `.claude/workflows/sdk-wave.js`
- Description: [SDK] The sdk-wave.js instance running this wave still uses the old AI-only Parse (GH-164 was fixed mid-wave), and the review scope it passed here leaves out 11 declared paths. The fixed deterministic scan of the same wave file finds them: agent_sdk/console/static/console.js, agent_sdk/routes/mcp.py, tests/test_rt001_mcp_dispatch_no_value_log.py, tests/test_gh152_idp_authorize_flow.py, tests/test_ag_ui_group_b.py, tests/test_gh148_reuse_kind_substitution.py, tests/test_gh159_reject_non_text_parts.py, docs/protocols.md, uv.lock, workspace/todos/deferred/w042-phase-medium-low.md and template/.claude/skills/setup/SKILL.md. The archive commit and undeclared-scope gates key off that narrowed allScope, so the release can ship without the GH-163 console panel, the RT-001 mcp.py logging fix and the uv.lock resync, or leave them uncommitted.
- Fix: Before archive and release, compute scope with harness/wave_scope.extract_wave_scope(w047 file), plus tests/test_rt001_agui_stream_no_value_log.py (see RT-004). Check that every dirty or untracked path in git status is in that set and gets committed. Do not trust the running instance's allScope for this wave.
- Codify: A wave that fixes its own workflow script still runs on the old script; recompute its scope with the fixed logic before archive and release.

## proto-A2UI-profile-field-contract--nested-required-keys--calendarevent-location---compact-schema----on-optional-fields-only- (high)

- File: protocol-surface (`agent_sdk/models/content_types.py`, `agent_sdk/a2ui/catalog.py`)
- Description: Standard Profile v1.1 says CalendarEvent.location is {display_name, is_online, join_url?}. Only join_url is optional. content_types.py:1136-1139 (EventLocation) makes display_name and is_online both `| None = None`. catalog.py:229 teaches them as `location?:{display_name?,is_online?,join_url?}`. So the prompt marks two required keys as optional, and the model accepts a location without them. Confirmed at runtime: EventLocation(join_url='u') serialises to {'join_url': 'u'} because wire() uses exclude_none. That payload fails the structural required-key check, and a renderer reading location.is_online gets undefined.
- Fix: Make EventLocation.display_name: str and is_online: bool required. Keep join_url optional. Change the compact schema to `location?:{display_name:str,is_online:bool,join_url?:str}`. Add a test that the schema string and the model agree on which location keys are required.
- Codify: Compact-schema '?' marks must be derived from, or tested against, the frozen contract table. Add a test per Profile type that compares required keys in _COMPACT_SCHEMAS with the model's required fields.
