wave: w046
phase: phase redteam
date: 2026-10-13
status: non-blocking (medium/low)

Non-blocking — these did not block w046's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every phase redteam round for w046 and deduped by file+description. Redteam IDs restart each round, so each heading carries its round label (R1..R6, in the order the rounds ran). Many findings recur across rounds with different wording. They are kept separately because their descriptions differ; the theme index below groups them. All are flagged sdkCandidate except R2 RT-003, R2 RT-005, R2 RT-007, R2 RT-008, R2 RT-009, R2 RT-012, R2 RT-013, R2 RT-014, R5 RT-010 and R5 RT-011.

## Theme index

1. DESIGN.md §4.3 (line 212) and the FundPerformance comment (content_types.py:1040-1052) still describe the old `sanitize_text` + `_sanitize_cell` id pipeline; landed code uses `safe_id_text` via `_safe_id`: R1 RT-005, R2 RT-003, R3 RT-004, R4 RT-004, R5 RT-002, R6 RT-002
2. DESIGN.md stale for GH-159: -32005 row (line 288) lacks non-TextPart trigger, §5.1 lacks text-only/-32602 empty-text rule, §5.3 (line 339) "History processing (not rejection)" contradicts the new RUN_ERROR: R1 RT-005, R2 RT-009, R3 RT-005, R4 RT-005, R5 RT-003, R6 RT-003
3. Release must be a minor bump (0.10.0 -> 0.11.0), not `bump-patch`: new public `Agent(mcp_instructions=...)` plus `### 🔴 Breaking changes` in [Unreleased]: R1 RT-006, R3 RT-014
4. GH-159 resume test uses `taskId="no-such-task"`; no real input-required task, no `:stream` resume case, no proof the interrupt stays pending, no HTTP status assert: R1 RT-007, R2 RT-008, R3 RT-007, R4 RT-009, R5 RT-004, R6 RT-004
5. `_task_count` returns None on a store without `_records`, so "no task created" asserts pass vacuously: R1 RT-007, R2 RT-013, R4 RT-014, R5 RT-010
6. MCP `tools/call` `content[0].text` id assertions cover only EntityList/DocumentList (GH-156 AC): R1 RT-007, R2 RT-012, R3 RT-003
7. new-agent SKILL.md harness vs template copies not byte-identical (LRN-208): R1 RT-008
8. `_validate` docstring still says content "is never hard-rejected" (RT-001), contradicting GH-159: R1 RT-009, R2 RT-005, R4 RT-012
9. `_KNOWN_PART_TYPES` omits AG-UI `video`, so it is labelled "unknown": R1 RT-009, R2 RT-011, R3 RT-016, R4 RT-012, R5 RT-007
10. GH-158 skill-mirror test sits in the GH-156 test file and silently skips absent mirrors (LRN-157): R1 RT-009, R2 RT-007
11. `_ID_NEUTRALISE` hand-copied from `_BARE_SEPARATORS` minus `=` (drift risk): R1 RT-009, R2 RT-010, R4 RT-010, R5 RT-008
12. `safe_id_text` silently alters ids (whitespace to `_`, `()[]<>` fullwidth, `|` to `/`, 256 cut with no marker); believable wrong ids; forgery claim in docstring overstated; undocumented/untested: R1 RT-010, R2 RT-004, R3 RT-011, R4 RT-003, R6 RT-005
13. `mcp_instructions=` silently accepted on `artifacts_dir=` agents and sent unrendered: R1 RT-011, R3 RT-012
14. AG-UI `_validate` and `_fold_history` disagree on where the current turn starts (blank assistant turn), so a binary part is silently dropped: R2 RT-002
15. sdk-wave.js wave scope extracted by a model, drops declared paths (LRN-168 false alarm, shrinks redteam scope): R2 RT-006
16. CHANGELOG files GH-156 under `### Fixed` instead of `### ⚠️ Behavior changes`, with no Migration line (LRN-153): R2 RT-014, R3 RT-015, R6 RT-013
17. AG-UI GH-159 bypasses: dict-shaped user content stringified into model input; `type:"text"` part whose `text` is a dict/list stringified: R3 RT-006, R6 RT-001
18. Registry-wide id meta-test skips unset optional `*_id` fields (LRN-241 drift): R3 RT-008
19. action_gate `parse_decision` docstring stale (DataPart/FilePart resume now rejected); `responseSchema` invites refused DataPart replies; docs/protocols.md lacks "A2A resume must be text": R3 RT-009, R5 RT-006, R6 RT-009
20. REVIEWS.md Round 2 row (line 198, "Always emit (as null)") not marked superseded by Round 12 (GH-158): R3 RT-010, R4 RT-013, R5 RT-011, R6 RT-010
21. test_gh157: broad `pytest.raises(Exception)`; unauthenticated `initialize` not pinned on POST /mcp/messages: R3 RT-013, R6 RT-011
22. AG-UI rejects non-text parts across the whole replayed history (bricks a thread; also scans beyond the 50-message fold window). NEEDS MAINTAINER RULING recorded on GitHub before any code change: R4 RT-006, R6 RT-007
23. `safe_id_text` not exported from `agent_sdk`; docs/content-types.md, add-tool skill and sdk-advisor lack the "render follow-up ids" rule for domain cards: R4 RT-007, R6 RT-006
24. add-artifact SKILL.md GH-157 block wrong for pre-SDK agents and "same variables as system" wording: R4 RT-008
25. GH-157 SI-6 secret guard: short secret values cause false build failures; plain-`str` secrets unchecked; dict-key collision lets artifact_vars hide a settings secret: R4 RT-011, R5 RT-009
26. Unclear build errors: bare jinja2 `UndefinedError` without artifact name; non-str `mcp_instructions` fails with `AttributeError`: R4 RT-015
27. LRN-152 meta-test counts only `_sanitize_cell(` presence, not per-field wrapping (pre-existing): R5 RT-005
28. AG-UI accepts empty/whitespace user text that A2A rejects with -32602: R5 RT-011, R6 RT-012
29. docs/protocols.md "Nothing is silently dropped" is too broad: R6 RT-008

## Findings

### R1 RT-005 [SDK] — medium — DESIGN.md
DESIGN.md disagrees with the landed code in four places. (1) §4.3 at line 212 says each id goes through 'sanitize_text(..., max_len=256) then _sanitize_cell', but the code uses safe_id_text, which keeps = : , @ and turns whitespace into '_'. (2) The error table at line 288 still says -32005 is only for 'unacceptable acceptedOutputModes'; it does not list non-text input parts. (3) §5.3 at line 339 ('History processing (not rejection) ... RUN_ERROR is reserved for agent-side failures') says nothing about the new GH-159 AG-UI rejection or its newest-user-message scope. (4) The FundPerformance comment at content_types.py:1040-1052 still says the pb_id order is 'sanitize_text, THEN _sanitize_cell', but the code now calls _safe_id.
- Fix: Fix §4.3 to say safe_id_text (C-007). Add 'message contains a non-TextPart (GH-159)' to the -32005 row. Add the AG-UI non-text rejection rule and its history exemption to §5.3. Update the FundPerformance comment.
- sdkCandidate: true

### R1 RT-006 [SDK] — medium — agent_sdk/app.py
GH-157 adds a public keyword argument, Agent(mcp_instructions=...), to the stable core (DESIGN.md §4.0), under '### Added'. SemVer requires a minor bump (0.11.0). The standing push habit is 'bump-patch'. A patch release (0.10.1) would hide a new stable-core API, the LRN-239 class of mistake.
- Fix: At /sdk-release, bump the minor version (0.10.0 -> 0.11.0), not the patch. Make the pyproject version and the CHANGELOG heading agree (LRN-232).
- sdkCandidate: true

### R1 RT-007 [SDK] — medium — tests/test_gh159_reject_non_text_parts.py
Test coverage does not meet the ACs. (a) test_resume_rejects_non_text_and_empty sends taskId='no-such-task', so it never reaches a real interrupted task. Nothing proves that an empty or non-text message leaves an input-required task still interrupted, and the message:stream resume branch is not tested at all. (b) _task_count() returns None when the store has no _records attribute, so 'assert _task_count(app) == before' passes vacuously on any other store. (c) The GH-156 AC asks for per-model asserts on MCP tools/call content[0].text, but tests/test_gh156_mcp_text_ids.py covers only EntityList and DocumentList; EmailList, CalendarEvents, UserList and UserProfile are not checked through MCP.
- Fix: Drive a real interrupt (for example the publish_note tool), then POST file-only and empty-text messages with that taskId on both /v1/message:send and /v1/message:stream. Assert 415/400 and that the task is still in input-required state. Add 'assert before is not None' in _task_count's callers. Add MCP tools/call tests for the other four id-bearing types.
- sdkCandidate: true

### R1 RT-008 [SDK] — medium — harness/skills/new-agent/SKILL.md
The GH-157 AC says 'harness skill mentions (all copies identical)'. harness/skills/new-agent/SKILL.md still differs from template/.claude/skills/new-agent/SKILL.md: the harness copy has uv sync/uv lock guidance, the template copy has pip install. The wave edited this file and synced only the new mention, leaving the files unequal. That fails LRN-208's whole-file diff check.
- Fix: Make template/.claude/skills/new-agent/SKILL.md byte-identical to harness/skills/new-agent/SKILL.md, commit and push it in the template repo (LRN-071), and add new-agent to the mirror-identity test.
- sdkCandidate: true

### R1 RT-009 [SDK] — low — agent_sdk/routes/ag_ui.py
Code quality issues in the GH-158/GH-159 changes. (1) The _validate docstring at line 145 still says content 'is never hard-rejected — not on ... unexpected part shapes (RT-001)', which the new rejection contradicts. (2) _KNOWN_PART_TYPES leaves out AG-UI's 'video' input content type, so a video part is reported as 'unknown'. (3) The GH-158 skill-mirror test sits in tests/test_gh156_mcp_text_ids.py instead of tests/test_gh158_agui_no_null_fields.py. (4) redact._ID_NEUTRALISE copies the first nine entries of _BARE_SEPARATORS instead of deriving them from it.
- Fix: Rewrite the docstring paragraph to scope RT-001 to replayed history. Add 'video' to _KNOWN_PART_TYPES. Move the skill-mirror test into the GH-158 test file. Build _ID_NEUTRALISE from _BARE_SEPARATORS minus '='.
- sdkCandidate: true

### R1 RT-010 [SDK] — low — agent_sdk/common/redact.py
safe_id_text changes some real ids without any signal: whitespace becomes '_', ()[]<>| become fullwidth characters, and leading/trailing spaces are stripped. The model then copies back an id the upstream API rejects, which defeats GH-156's purpose for any agent whose ids contain spaces or brackets. Its docstring also claims an id 'cannot forge ... , conversation: ...', but 'a,conversation:evil' still renders as a convincing second field.
- Fix: Document in C-007 and DESIGN.md §4.3 which id alphabets are not preserved. Optionally keep ids with spaces or brackets exact by wrapping them in a backtick span that cannot be forged, instead of rewriting them. Tighten the docstring claim.
- sdkCandidate: true

### R1 RT-011 [SDK] — low — agent_sdk/app.py
An agent built with artifacts_dir= and with no mcp_instructions.md artifact silently accepts the mcp_instructions= keyword argument. The GH-157 ruling and the docstring both say the argument is for persona= agents, and that artifact agents use the artifact.
- Fix: Either raise ValueError when mcp_instructions= is passed together with artifacts_dir=, or document that the argument is a valid fallback for artifact agents.
- sdkCandidate: true

### R2 RT-002 [SDK] — medium — agent_sdk/routes/ag_ui.py
_validate decides where the current turn starts using a different rule from _fold_history. _validate stops at any assistant message, but _fold_history skips blank assistant turns and merges the user messages around them. So [user(text+binary), assistant(''), user('go')] passes validation, and the binary part is then silently dropped (probe output: _validate returns None and the folded content is 'see file','go'). Clients that record tool-only assistant turns with empty content hit this path.
- Fix: Count an assistant message as a boundary only when it would survive _fold_history, meaning its folded text is not blank. Share one helper between both functions. Add a test for user(binary), blank assistant, user(text).
- sdkCandidate: true

### R2 RT-003 — medium — DESIGN.md
The DESIGN.md §4.3 GH-156 paragraph (line 212) says each id is rendered with sanitize_text(..., max_len=256) and then _sanitize_cell. The code renders ids with safe_id_text (via _safe_id), which deliberately skips safe_cell_text so that '=', ':', ',' and '@' stay exact. FundPerformance.pb_id was also moved off _sanitize_cell. A reviewer who aligns the code to this design text would undo the fix for ids.
- Fix: Rewrite the sentence: ids are rendered via C-007 safe_id_text (safe_error_text with max_len=256, whitespace changed to '_', and only ()[]<>| neutralised), never via _sanitize_cell.
- sdkCandidate: false

### R2 RT-004 [SDK] — medium — agent_sdk/common/redact.py
safe_id_text silently changes some ids, and nothing documents or signals it. Whitespace becomes '_' ('a b' -> 'a_b'). The characters ()[]<>| become full-width or '/' ("Users('x')" -> "Users（'x'）"). Ids are cut at 256 characters with no marker. A model that copies the rendered id into a follow-up tool call sends an id that does not exist, which is the failure GH-156 set out to fix. 'a b' and 'a_b' also render the same. The docstring also claims an id cannot forge ', conversation: ...', but 'x,conversation:evil' passes through unchanged.
- Fix: Document which characters are changed in the docstring, DESIGN §4.3 and CHANGELOG. Add a truncation marker (for example a trailing '…') so a cut id is visibly incomplete. Correct the forgery claim in the docstring. Add tests using real Graph, SharePoint ('b!...') and URN id alphabets that prove these ids survive unchanged.
- sdkCandidate: true

### R2 RT-005 — medium — agent_sdk/routes/ag_ui.py
The _validate docstring contradicts itself. The new paragraph says non-text parts in the current turn are rejected, but the older paragraph still says 'Message CONTENT is never hard-rejected — not on control characters, not on unexpected part shapes (RT-001)'. The code now rejects non-dict parts and unknown part types.
- Fix: Narrow the RT-001 paragraph. Content in replayed history is never rejected. Parts that are not text in the current turn's user messages are rejected (GH-159). Control characters are always stripped, never rejected.
- sdkCandidate: false

### R2 RT-006 [SDK] — medium — .claude/workflows/sdk-wave.js
The wave scope handed to this review is missing four paths that the todos declare. GH-156's Creates line names agent_sdk/common/redact.py, tests/test_gh156_mcp_text_ids.py and workspace/components/README.md. GH-158's names the harness/skills/ag-ui-check/SKILL.md mirror. The scope is pulled out by a model following the allCreates/allModifies schema text (lines 124-125, 673-695), not by a fixed rule. A dropped agent_sdk path makes offendingUndeclaredScope (LRN-168) give a false alarm, and it removes a file that matters for SI-2 (a C-007 sanitizer change) from the review scope.
- Fix: Pull scope out with a fixed regex over every backticked path token on the Creates:/Modifies: lines, rather than relying on the model. Then cross-check that the result is a superset of the dirty files under agent_sdk/ before redteam runs.
- Codify: Wave scope must be extracted deterministically from backticked todo paths; LLM extraction silently drops declared files and shrinks the redteam scope.
- sdkCandidate: true

### R2 RT-007 — medium — tests/test_gh156_mcp_text_ids.py
test_skills_have_no_stale_parent_message_id_trap skips any mirror file that is missing ('if p.exists()') without saying so, including the gitignored template/ copy. That is the silent-filter pattern LRN-157 forbids. The test is also a GH-158 check sitting in the GH-156 test file.
- Fix: Move the test to tests/test_gh158_agui_no_null_fields.py. Require that the .claude and harness copies exist. Use pytest.skip with a reason (or xfail) for an absent template/ copy, never a silent pass.
- sdkCandidate: false

### R2 RT-008 — medium — tests/test_gh159_reject_non_text_parts.py
The resume coverage for GH-159 is thin. test_resume_rejects_non_text_and_empty only calls /v1/message:send with taskId='no-such-task'. It never resumes a task that is really paused for input, so it does not prove that an empty string or a FilePart can no longer resume a real task, or that the interrupt stays pending. The message:stream resume path is not tested at all, although the AC lists 'resume, stream'.
- Fix: Create a task paused for input (publish_note tool). Send FILE, DATA, '' and '   ' resumes on both /v1/message:send and /v1/message:stream. Assert -32005 or -32602, assert the task stays in input-required, and assert that a later text resume still succeeds.
- sdkCandidate: false

### R2 RT-009 — low — DESIGN.md
The A2A error code table (line 288) still lists only 'unacceptable acceptedOutputModes' as the trigger for -32005 ContentTypeNotSupported. It does not mention the new GH-159 trigger: inbound FilePart or DataPart.
- Fix: Add 'inbound FilePart/DataPart (text-only input, GH-159)' and the non-JSON Content-Type trigger to the -32005 row.
- sdkCandidate: false

### R2 RT-010 [SDK] — low — agent_sdk/common/redact.py
_ID_NEUTRALISE copies _BARE_SEPARATORS by hand, minus '='. If a new separator is later added to _BARE_SEPARATORS, the id helper will not pick it up.
- Fix: Build it from the existing table: _ID_NEUTRALISE = {k: v for k, v in _BARE_SEPARATORS.items() if k != ord('=')}. Add a test that pins the relationship.
- sdkCandidate: true

### R2 RT-011 [SDK] — low — agent_sdk/routes/ag_ui.py
_KNOWN_PART_TYPES is {binary, image, audio, file, document}. Some AG-UI multimodal input schemas also define 'video', so a valid video part is reported with the unclear label 'unknown'.
- Fix: Check the type list against the AG-UI InputContent schema the SDK targets and add any missing types (such as 'video'). Keep the fixed allowlist for SI-2.
- sdkCandidate: true

### R2 RT-012 — low — tests/test_gh156_mcp_text_ids.py
The MCP tools/call content[0].text tests cover only EntityList and DocumentList. EmailList, CalendarEvents, UserList and UserProfile are checked only through to_plain_text(), while the AC asks for per-model checks on the MCP text block.
- Fix: Parametrize one Tier-1 tool per id-bearing type and assert every id in content[0].text, reusing _id_sample_instances().
- sdkCandidate: false

### R2 RT-013 — low — tests/test_gh159_reject_non_text_parts.py
_task_count returns None when the task store has no _records attribute, so 'assert _task_count(app) == before' compares None == None and passes even if a task was created. This happens with a durable store or after a rename.
- Fix: Assert that hasattr(app.state.task_store, '_records'), or count tasks through a public store API, so the 'no task created' check cannot pass without checking anything.
- sdkCandidate: false

### R2 RT-014 — low — CHANGELOG.md
GH-156 is filed under 'Fixed', but it changes the exact to_plain_text() output of six public content types. That text is the MCP text block and the A2A TextPart. The SDK's own exact-text test had to change, and downstream exact-text tests will break too. The entry has no Migration note and is not under Behavior or Breaking changes (see LRN-153).
- Fix: Move GH-156 under a behavior-change heading with a short Migration line: exact-text assertions on these cards must now include the '(id: ...)' or '(<id>)' suffix.
- sdkCandidate: false

### R3 RT-003 [SDK] — medium — tests/test_gh156_mcp_text_ids.py
GH-156 AC: 'Per-model tests assert ids in to_plain_text() and in the MCP tools/call content[0].text.' Only EntityList and DocumentList are called through MCP tools/call. EmailList (id and conversation id), CalendarEvents, UserList and UserProfile (id and manager id) have no MCP content[0].text assertion.
- Fix: Add one tier-1 tool per type, built from _id_sample_instances(). Parametrize the MCP test over all six types plus FundPerformance, and assert every value from _collect_id_values appears in content[0].text.
- sdkCandidate: true

### R3 RT-004 [SDK] — medium — DESIGN.md
DESIGN.md:212 says each id is rendered via `sanitize_text(..., max_len=256)` then `_sanitize_cell`. The landed code uses safe_id_text (agent_sdk/common/redact.py:194), which keeps = : , @ + / byte-exact, turns whitespace into _ and neutralises only ()[]<>|. The FundPerformance comment block at agent_sdk/models/content_types.py:1040-1052 still describes the old 'cap first (sanitize_text), THEN strip separators (_sanitize_cell)' pipeline above a line that now calls _safe_id.
- Fix: Rewrite the DESIGN.md §4.3 sentence to name safe_id_text (C-007) and its exact transform. Update the FundPerformance comment to describe the _safe_id call.
- sdkCandidate: true

### R3 RT-005 [SDK] — medium — DESIGN.md
The GH-159 behavior is recorded in DESIGN.md only as a parenthetical inside the GH-128 A2UI paragraph (line 358). Three other places are stale. The §5.1 error table row for -32005 (line 288) still lists only 'unacceptable acceptedOutputModes'. §5.1 does not state the text-only input rule or the -32602 rejection of empty text. §5.3 line 339, 'History processing (not rejection)', now contradicts the RUN_ERROR rejection of non-text user parts anywhere in history.
- Fix: Add 'non-TextPart in inbound message (GH-159)' to the -32005 row. Add a text-only input bullet to §5.1 covering -32005/415 and -32602 for empty text, including on resume. Amend §5.3 line 339 to carve out the GH-159 non-text-part rejection and its brick-until-removed consequence.
- sdkCandidate: true

### R3 RT-006 [SDK] — medium — agent_sdk/routes/ag_ui.py
The GH-159 check in _validate skips any user message whose content is not a list (`if not isinstance(content, list): continue`). A dict-shaped content such as {'type':'binary','data':'<base64>'} passes validation. _fold_history then runs str(content) on it and sends the stringified binary payload to the model as user text, cut to 4000 chars. That is non-text input accepted without rejection, which goes against the 'no silent drop' ruling and docs/protocols.md's 'Nothing is silently dropped'.
- Fix: In _validate, reject a user message whose content is neither str nor list. Name it with a fixed label such as 'unknown', or treat a dict as one part and run it through the same allowlist label path. Add a test for dict-shaped non-text content.
- sdkCandidate: true

### R3 RT-007 [SDK] — medium — tests/test_gh159_reject_non_text_parts.py
GH-159 AC requires a resume test and says 'an empty string can no longer resume a task'. test_resume_rejects_non_text_and_empty (line 50) only posts to :send with taskId='no-such-task'. It never interrupts a real task and so never proves that an empty-text or FilePart reply leaves the interrupt pending. There is no :stream resume case, and the resume test does not assert the HTTP status.
- Fix: Use the publish_note action-gate tool to drive a real input-required task. Send an empty-text reply and a FilePart reply to both /v1/message:send and /v1/message:stream. Assert 400/-32602 and 415/-32005, assert the task is still input-required, and assert that a later text 'yes' still resumes it.
- sdkCandidate: true

### R3 RT-008 [SDK] — medium — tests/test_content_types.py
test_registry_wide_every_id_field_reaches_text (line 1197) builds its expected ids with _collect_id_values, which skips None and empty values. If a new optional *_id field is added to an existing model and the hand-built sample leaves it unset, the test still passes even though _body_text never renders it. LRN-241 exists to prevent exactly this hand-list drift.
- Fix: Extend _id_fields_in_schema to return the full field paths. Assert that each sample sets a non-empty value for every id path, or that the path is listed in _ID_TEXT_EXEMPT with a reason, before checking that the values reach the text.
- sdkCandidate: true

### R3 RT-009 [SDK] — low — agent_sdk/contrib/action_gate/gate.py
The gate.py:126-129 docstring still says an A2A resume carrying only a DataPart or FilePart 'arrives as "" → UNCLEAR'. After GH-159 such a resume is rejected with 415 and the interrupt stays pending. The A2A input-required status metadata (agent/runner.py:1375) still advertises an object responseSchema, which invites a structured DataPart reply that A2A now refuses. docs/protocols.md does not say that A2A resume replies must be text.
- Fix: Update the parse_decision docstring: a DataPart or FilePart resume is rejected with -32005 before reaching the gate. In docs/protocols.md, state that A2A interrupt replies must be TextPart text such as 'yes' or 'no', and that responseSchema applies to AG-UI resume payloads only.
- sdkCandidate: true

### R3 RT-010 [SDK] — low — REVIEWS.md
The Round 2 table row at REVIEWS.md:198 ('`parentMessageId` absent on first tool call | Always emit (as null)') has no pointer to Round 12. A reader or advisor who greps Round 2 sees the superseded rule as current.
- Fix: Append '— SUPERSEDED by Round 12 (GH-158): omit when absent' to the line 198 row.
- sdkCandidate: true

### R3 RT-011 [SDK] — low — agent_sdk/common/redact.py
safe_id_text (line 194) maps '|' to '/', and '/' is itself a valid base64 id character. It also swaps ()[]<> for fullwidth forms, turns whitespace into '_', and cuts at 256 characters with no marker. An id that contains these characters becomes a plausible-looking but wrong id that a model will copy back into a tool call. This lossiness is not documented in the CHANGELOG or DESIGN.md, and no test covers it.
- Fix: Document the lossy cases in the safe_id_text docstring, DESIGN.md §4.3 and CHANGELOG. Consider a visible marker on truncation, such as a trailing '…', so a truncated id is clearly incomplete. Add a test that pins the behavior.
- sdkCandidate: true

### R3 RT-012 [SDK] — low — agent_sdk/app.py
Agent(mcp_instructions=...) on an artifacts_dir= agent with no mcp_instructions.md artifact is accepted silently and sent without Jinja rendering (line 654). The docstring says the kwarg is 'For persona= agents' and that artifacts_dir agents use the artifact. A '{{ agent_name }}' in the kwarg reaches MCP clients literally.
- Fix: Either raise ValueError at build when artifacts_dir is set and mcp_instructions= is passed, or document that the kwarg is sent unrendered for artifact agents. Add a test either way.
- sdkCandidate: true

### R3 RT-013 [SDK] — low — tests/test_gh157_mcp_instructions.py
test_undefined_variable_is_error (line 112) uses `pytest.raises(Exception, match='nope')`, so it does not pin the exception type and does not check that the error leaks no rendered text. The SI-2 unauthenticated-initialize test covers only POST /mcp, not the legacy POST /mcp/messages path.
- Fix: Assert jinja2.UndefinedError, or a ValueError wrapper, and check that the error text contains no artifact_vars values. Add an unauthenticated initialize case for /mcp/messages that asserts 401 and that the instruction text is absent.
- sdkCandidate: true

### R3 RT-014 [SDK] — low — CHANGELOG.md
[Unreleased] has a '### 🔴 Breaking changes' section (GH-158 wire key removal, GH-159 input rejection). The requested release must be a minor bump (0.11.0). The habitual `python3 -m agent_sdk bump-patch` would ship breaking changes as 0.10.1.
- Fix: Have /sdk-release cut 0.11.0 (bump the minor version), not bump-patch, for this [Unreleased] block.
- sdkCandidate: true

### R3 RT-015 [SDK] — low — CHANGELOG.md
The GH-156 entry sits under '### Fixed' (line 16), but it changes to_plain_text() output for seven types. That output is a required Standard Profile interface that MCP and A2A text clients may parse, and the entry also changes how FundPerformance.pb_id renders. Project convention files such changes under '### ⚠️ Behavior changes' with a migration note.
- Fix: Move the GH-156 entry to '### ⚠️ Behavior changes' and add a one-line Migration note about the new '(id: ...)' suffixes and the pb_id rendering change.
- sdkCandidate: true

### R3 RT-016 [SDK] — low — agent_sdk/routes/ag_ui.py
_KNOWN_PART_TYPES = {binary, image, audio, file, document} leaves out 'video', so a video part is reported as 'unsupported user content part type: unknown', which is less useful to the client.
- Fix: Add 'video' to _KNOWN_PART_TYPES and add a label test for it.
- sdkCandidate: true

### R4 RT-003 [SDK] — medium — agent_sdk/common/redact.py
`safe_id_text` changes some ids without saying so, and the model then copies the changed id into the next call. Spaces become `_`, `|` becomes `/`, brackets become fullwidth characters, and ids longer than 256 characters are cut with no marker. Examples: `auth0|abc123` becomes `auth0/abc123`, and `Shared Documents/Q4 Report.docx` becomes `Shared_Documents/Q4_Report.docx`. The model gets an id that looks valid but is wrong, so the follow-up call fails with no hint why. GH-156 exists to prevent exactly that. Graph and PitchBook ids are not affected.
- Fix: When `safe_id_text` would change a value (output differs from the control-stripped input, or the value was cut), render it in a form that can be reversed and cannot forge structure, such as `json.dumps(value)` (a quoted, escaped string). Or add an explicit marker such as `(id truncated)` or `(id: <unrepresentable>)`. Document the rule in DESIGN.md §4.3 and add tests for an id with spaces or `|`.
- Codify: An id rendered for a model to copy back must be exact or clearly marked as altered; a silent change is worse than leaving the id out.
- sdkCandidate: true

### R4 RT-004 [SDK] — medium — DESIGN.md
DESIGN.md §4.3 (GH-156 paragraph, about line 212) says each id is rendered via `sanitize_text(..., max_len=256)` then `_sanitize_cell`. The landed code uses `_safe_id` -> `safe_id_text` (`safe_error_text` + whitespace->`_` + `_ID_NEUTRALISE`), which keeps `= : , @` exactly. `_sanitize_cell` would turn those into fullwidth characters. FundPerformance.pb_id also moved off `_sanitize_cell`. The spec describes a pipeline the code no longer uses.
- Fix: Change the sentence to: ids are rendered via `safe_id_text(value, max_len=256)` (C-007 sibling in `agent_sdk/common/redact.py`): control characters stripped, whitespace turned into `_`, only `()[]<>|` neutralised, and `= + / : , . _ - ! ~ @` kept exactly. Also note that FundPerformance.pb_id now uses the same helper.
- sdkCandidate: true

### R4 RT-005 [SDK] — medium — DESIGN.md
GH-159 is recorded in DESIGN.md only as an aside inside the GH-128 A2UI DataPart paragraph (line 358). §5.3 AG-UI still has the heading `History processing (not rejection)` and says nothing about the new `RUN_ERROR` for non-text user parts in any history message, which contradicts the code. §5.1 'Inbound Message validation' (line 268) lists only the messageId rule, not the -32005/415 non-TextPart rule or the -32602 empty-text rule.
- Fix: Add the GH-159 rules to §5.1 'Inbound Message validation': non-TextPart -> -32005/HTTP 415 before task creation on send, stream and resume; empty joined text -> -32602; the `" "` fallback is removed. In §5.3, add an explicit exception to the 'not rejection' rule: non-text user content parts in any user message -> RUN_ERROR before task creation; skipped on resume; the error label comes from an allowlist.
- sdkCandidate: true

### R4 RT-006 [SDK] — medium — agent_sdk/routes/ag_ui.py
`_validate` rejects non-text parts in every user message of the replayed history, not only in the new turn. AG-UI clients resend the full history on every run. Once a client sends one image or binary part, every later run on that thread ends in `RUN_ERROR` until the client edits its own history. That is the permanent session-bricking that RT-001 (in the same docstring) says content validation must never cause. REVIEWS.md Round 13 records this consequence, but the maintainer ruling on GH-159 (comment 6128074134) says only 'rejected before a run starts (no silent drop)'. It does not ratify bricking threads.
- Fix: Do not change the code without a ruling: Round 13 says the earlier narrowing was reverted as unapproved. Escalate to the maintainer with a recorded GitHub comment (memory: feedback-wave-signoff-needs-user-ratification). Ask whether the rule should apply only to the latest user message, with earlier already-rejected messages skipped and the skip logged. Until then, keep the documented behavior.
- sdkCandidate: true

### R4 RT-007 [SDK] — medium — agent_sdk/__init__.py
The new public C-007 helper `safe_id_text` is not exported from `agent_sdk`, while its siblings `safe_cell_text`, `safe_block_text` and `safe_error_text` are (`agent_sdk/__init__.py:23`). The guidance for downstream agents also lacks the new rule. docs/content-types.md and harness/skills/add-tool/SKILL.md, which teach authors to write `_body_text()`, do not say the text fallback must carry follow-up ids, so agents' own domain cards will keep the GH-156 bug. Per the SDK scope rule, skills and SDK APIs are the only way to reach downstream agents.
- Fix: Add `safe_id_text` to the `from .common.redact import ...` line and to `__all__` in `agent_sdk/__init__.py`, and add a CHANGELOG `### Added` line for it. Add a short rule to docs/content-types.md and harness/skills/add-tool/SKILL.md (and its template mirror, per LRN-071): `_body_text()` must render every id a follow-up tool needs, via `safe_id_text`.
- sdkCandidate: true

### R4 RT-008 [SDK] — medium — harness/skills/add-artifact/SKILL.md
The new 'Optional: MCP instructions (GH-157)' block comes right after the 'Pre-SDK agents (standalone ArtifactLoader)' subsection and tells readers to add `src/artifacts/mcp_instructions.md`. The SDK picks up that file only when the agent passes `artifacts_dir=`. A pre-SDK or self-rendering agent that follows this step gets nothing, with no warning. The block also says 'same variables as system', but for those agents `system` gets per-call variables (`today`, `now_utc`) that `build_app` does not provide. Using them in mcp_instructions.md fails the build with a StrictUndefined error.
- Fix: Rewrite the block: the `mcp_instructions.md` artifact works only with `Agent(artifacts_dir=...)` and is rendered once at build with `agent_name`, `agent_version` and `artifact_vars` (no per-call variables such as `today`). Every other agent must pass `Agent(mcp_instructions=...)`. Make the same change in template/.claude/skills/add-artifact/SKILL.md and commit it in the template repo (LRN-071), and fix the 'same variables as `system`' wording in docs/protocols.md.
- sdkCandidate: true

### R4 RT-009 [SDK] — medium — tests/test_gh159_reject_non_text_parts.py
`test_resume_rejects_non_text_and_empty` sends to `taskId="no-such-task"`, so it proves only that parsing comes before the task lookup. Nothing tests a real `input-required` task: that an empty or FilePart resume message is rejected, the interrupt stays pending, and a later valid text resume still works. The AC 'an empty string can no longer resume a task' is therefore never tested against a live interrupt.
- Fix: Script an interrupting tool (e.g. `publish_note` via `fake_model.script(tool_call(...))`) to get a task into input-required. Send the empty-text and FilePart resumes and assert -32602/-32005. Then assert the task is still input-required (GET /v1/tasks/{id}) and that a non-empty text resume moves it forward.
- sdkCandidate: true

### R4 RT-010 [SDK] — low — agent_sdk/common/redact.py
`_ID_NEUTRALISE` is a hand copy of `_BARE_SEPARATORS` minus `=`. If a separator is later added to `_BARE_SEPARATORS`, the id path will silently miss it (the same duplication drift as LRN-236).
- Fix: Derive it: `_ID_NEUTRALISE = {k: v for k, v in _BARE_SEPARATORS.items() if k != ord("=")}`.
- sdkCandidate: true

### R4 RT-011 [SDK] — low — agent_sdk/app.py
The SI-6 secret guard matches any SecretStr value as a raw substring. A short or common secret value (e.g. a 1-4 character dev value) fails the build whenever mcp_instructions happens to contain that text. Meanwhile secret settings typed as plain `str`, and credential-store values, are not checked at all (documented in DESIGN.md).
- Fix: Skip values shorter than about 8 characters, or match on word boundaries. Also state in the Agent docstring that only SecretStr-typed settings and artifact_vars are checked.
- sdkCandidate: true

### R4 RT-012 [SDK] — low — agent_sdk/routes/ag_ui.py
`_KNOWN_PART_TYPES` leaves out `video`, a current AG-UI InputContent type, so a video part is reported as 'unknown'. The `_validate` docstring also still says 'Message CONTENT is never hard-rejected' on a 127-character line, right after the new GH-159 exception paragraph that contradicts it.
- Fix: Add `"video"` to `_KNOWN_PART_TYPES`. Rewrap the docstring and reword the RT-001 sentence to 'apart from the GH-159 non-text rule, content is never hard-rejected'.
- sdkCandidate: true

### R4 RT-013 [SDK] — low — REVIEWS.md
The Round 2 table row at line 198 still says 'Always emit (as null)' for `parentMessageId`, with no inline note. A reader of Round 2 alone does not see that Round 12 (GH-158) reversed it.
- Fix: Append '(superseded by Round 12 / GH-158: omit when absent)' to the Round 2 row.
- sdkCandidate: true

### R4 RT-014 [SDK] — low — tests/test_gh159_reject_non_text_parts.py
`_task_count` returns None when the task store has no `_records` attribute, so `assert _task_count(app) == before` becomes `None == None`. The 'no task created on rejection' assertion would silently pass on any non-memory store.
- Fix: Assert `hasattr(app.state.task_store, "_records")` (or use a public count or list API) so the check cannot pass when the count is unavailable.
- sdkCandidate: true

### R4 RT-015 [SDK] — low — agent_sdk/app.py
An undefined variable in `mcp_instructions.md` surfaces as a bare jinja2 `UndefinedError` ("'nope' is undefined") that does not name the artifact, unlike the clear build messages for the cap and for setting both. A type that is not a string for `Agent(mcp_instructions=...)` fails with an unclear `AttributeError` from `.strip()`.
- Fix: Wrap the `loader.render("mcp_instructions", ...)` call: catch `jinja2.UndefinedError` and raise `ValueError(f"mcp_instructions artifact: {exc}")` (the message holds the variable name only). In `Agent.__init__`, check that `mcp_instructions` is `str | None`.
- sdkCandidate: true

### R5 RT-002 [SDK] — medium — DESIGN.md
DESIGN.md:212 (§4.3, GH-156) says each id goes through `sanitize_text(..., max_len=256)` and then `_sanitize_cell`. The landed code uses the new `safe_id_text` helper instead (content_types.py `_safe_id`). That helper keeps `= : , @` unchanged, turns whitespace into `_`, and replaces only `()[]<>|`. The FundPerformance comment at content_types.py:1040-1052 still describes the old 'Cap first (sanitize_text), THEN strip separators (_sanitize_cell)' steps, but the line under it now calls `_safe_id`.
- Fix: Change DESIGN.md §4.3 to say 'via `safe_id_text` (C-007, max_len=256)' and describe what it changes in an id. Rewrite the FundPerformance comment to match the `_safe_id` call.
- sdkCandidate: true

### R5 RT-003 [SDK] — medium — DESIGN.md
Two GH-159 behavior changes are missing from DESIGN.md where those behaviors are described. (1) The A2A error table at DESIGN.md:288 still lists -32005 only for 'unacceptable `acceptedOutputModes`'. It now also fires for any FilePart or DataPart in the input (HTTP 415), and the new -32602 rejection of empty text is not mentioned. (2) §5.3 at DESIGN.md:339 still says 'History processing (not rejection)' and 'RUN_ERROR is reserved for agent-side failures'. AG-UI now returns RUN_ERROR for non-text parts in any user message, history included.
- Fix: Add the non-TextPart input trigger to the -32005 row and the empty-text trigger to the -32602 description. In §5.3, add the GH-159 exception: non-text user content parts get RUN_ERROR, in any user message, and resume runs are skipped.
- sdkCandidate: true

### R5 RT-004 [SDK] — medium — tests/test_gh159_reject_non_text_parts.py
The AC asks for a resume test, but `test_resume_rejects_non_text_and_empty` (line 50) only posts to `/v1/message:send` with `taskId="no-such-task"`. No real task waiting for input is ever resumed. There is no `:stream` resume case, no HTTP status assertion, and no check that the interrupt is still pending (not consumed by `deliver_resume`) after the rejection. A future refactor that moved the check after the resume branch would still pass this test.
- Fix: Create a real interrupted task (script a gated tool so the task reaches input-required). Send FilePart-only and empty-text resumes on both `/v1/message:send` and `/v1/message:stream`. Assert 415/-32005 and 400/-32602, then assert the task is still input-required and that a later text resume works.
- sdkCandidate: true

### R5 RT-005 [SDK] — medium — tests/test_content_types.py
The LRN-152 check fails. This predates the wave. `test_gh130_all_profile_renderers_sanitize_before_joining` (line 955) only checks that `_sanitize_cell(` appears somewhere in a renderer's source. It does not compare the number of untrusted fields against the number of sanitizer calls. This wave added new untrusted fields (ids) to six renderers through `_safe_id(`, and that meta-test counts none of them. `test_every_id_site_is_sanitized_and_capped`, which checks each type with hostile ids, covers the ids. The LRN's check still fails as written, so this is reported at medium rather than its high severity: the gap predates the wave, and the new interpolations have their own per-field test.
- Fix: Extend the meta-test to count interpolated `self.`/item fields in each `_body_text` and assert that each one is wrapped in `_sanitize_cell`, `_sanitize_block` or `_safe_id`. Or retire the LRN-152 check clause in favor of the per-field hostile-value test pattern.
- sdkCandidate: true

### R5 RT-006 [SDK] — low — agent_sdk/contrib/action_gate/gate.py
The `parse_decision` docstring (gate.py:128) still says an A2A resume that carries only a DataPart or FilePart 'arrives as "" → UNCLEAR'. After GH-159 that resume is rejected with -32005 before it reaches the gate. A2A input-required metadata still includes `responseSchema` (runner.py:1375), which invites structured DataPart replies that are now refused. docs/protocols.md does not say that A2A resume replies must be TextPart.
- Fix: Update the docstring to say non-text resumes are rejected at the route with -32005. Add one line to docs/protocols.md: interrupted-task resumes on A2A must be text; `responseSchema` describes the meaning of the text reply.
- sdkCandidate: true

### R5 RT-007 [SDK] — low — agent_sdk/routes/ag_ui.py
`_KNOWN_PART_TYPES` (ag_ui.py:127) leaves out `video`, which AG-UI's multimodal input content includes. A video part is rejected correctly, but the error labels it 'unknown' instead of naming the part type, as the AC requires.
- Fix: Add "video" to `_KNOWN_PART_TYPES` and add it to the parametrized label test.
- sdkCandidate: true

### R5 RT-008 [SDK] — low — agent_sdk/common/redact.py
`_ID_NEUTRALISE` (redact.py:181) is a hand-copied subset of `_BARE_SEPARATORS`: the same 9 entries minus `=`. If a new bare separator is added to `_BARE_SEPARATORS` later, `safe_id_text` will not pick it up, so ids could forge that separator in the text fallback.
- Fix: Derive it: `_ID_NEUTRALISE = {k: v for k, v in _BARE_SEPARATORS.items() if k != ord("=")}`. Add a test asserting the two maps differ only by `=`.
- sdkCandidate: true

### R5 RT-009 [SDK] — low — agent_sdk/app.py
The GH-157 SI-6 guard builds `secret_values` as a dict keyed by field name, merging settings fields and `artifact_vars`. If an `artifact_vars` key has the same name as a settings SecretStr field, the artifact value replaces the settings secret, and the settings secret is never checked against the rendered `mcp_instructions`.
- Fix: Collect `(source, name, value)` tuples or a list instead of a dict, so every SecretStr is checked. In the error, say which source the name came from (settings or artifact_vars), without the value.
- sdkCandidate: true

### R5 RT-010 — low — tests/test_gh159_reject_non_text_parts.py
`_task_count` (line 17) returns None when the store has no `_records` attribute. Every 'no task created' assertion then compares None == None and passes without checking anything. This would happen with any non-InMemory store fixture.
- Fix: Assert `hasattr(app.state.task_store, "_records")` in the helper, or count tasks through a public store API, so the check cannot pass without checking anything.
- sdkCandidate: false

### R5 RT-011 — low — REVIEWS.md
The Round 2 row at REVIEWS.md:198 ('`parentMessageId` absent on first tool call | Always emit (as null)') is not marked as superseded. Only the new Round 12 says it overrides Round 2. Someone reading Round 2 alone gets the reversed ruling. The AG-UI route also still accepts an empty or whitespace-only user message that A2A now rejects with -32602. That gap is not recorded anywhere either.
- Fix: Add '(superseded by Round 12, GH-158)' to the Round 2 row. Record the AG-UI/A2A empty-text difference as a known gap in docs/protocols.md, or fix it in a follow-up.
- sdkCandidate: false

### R6 RT-001 [SDK] — medium — agent_sdk/routes/ag_ui.py
GH-159 bypass: a `type: "text"` part whose `text` is a dict or list passes `_user_content_problem` (it only checks `type`), and `_fold_history` line 106 then runs `str(p.get("text") or "")`. So `{"type":"text","text":{"bytes":"QUJD","mimeType":"image/png"}}` reaches the model as `"{'bytes': 'QUJD', 'mimeType': 'image/png'}"`. I confirmed this by calling `_validate` (returns None) and `_fold_history` directly. It breaks the claims in the `_fold_history` docstring, docs/protocols.md:33-35 and the CHANGELOG that a structured value is never stringified into model input and that non-text input is rejected.
- Fix: In `_user_content_problem`, reject a text part whose `text` is a dict or list, with a fixed message such as "text part must carry a string". In `_fold_history`, map non-scalar `text` to "" instead of calling str(). Scalars (None/int/bool) can keep the coercion that test_ag_ui_group_b pins. Add the dict-text and list-text cases to tests/test_gh159_reject_non_text_parts.py.
- Codify: An allowlist on a part's `type` is not enough. The payload field of an allowed part must be type-checked too, or a malformed allowed part carries the content the allowlist was meant to block.
- sdkCandidate: true

### R6 RT-002 [SDK] — medium — DESIGN.md
The new §4.3 paragraph (line 212) says each id is rendered via `sanitize_text(..., max_len=256)` then `_sanitize_cell`. The landed code uses `safe_id_text`, which deliberately skips `_sanitize_cell`. The CHANGELOG says pb_id no longer goes through `_sanitize_cell`. So the spec contradicts both the code and the CHANGELOG. The FundPerformance comment at agent_sdk/models/content_types.py:1040-1052 still describes the old 'cap first (sanitize_text), THEN strip separators (_sanitize_cell)' pipeline right above a `_safe_id()` call.
- Fix: Rewrite the DESIGN.md §4.3 sentence to: rendered via `safe_id_text` (C-007): control characters stripped, capped at 256, whitespace turned into `_`, only `()[]<>|` neutralised, `= + / : , . _ - ! ~ @` kept byte-exact. Replace the stale FundPerformance comment with a one-line pointer to `_safe_id`/`safe_id_text`.
- Codify: When a wave changes a sanitising pipeline, the new spec paragraph and the inline comment at the call site must describe the code that landed, not the pipeline the todo AC first proposed.
- sdkCandidate: true

### R6 RT-003 [SDK] — medium — DESIGN.md
GH-159 updated DESIGN.md only near line 356. Two older normative lines now contradict the code. Line 288's -32005 row lists only 'unacceptable acceptedOutputModes' and omits the new non-TextPart input rejection. Line 339 §5.3 says 'History processing (not rejection)' and 'RUN_ERROR is reserved for agent-side failures, not large-but-valid client history'. But `_validate` now ends the run with RUN_ERROR when any user message in the replayed history has a non-text part.
- Fix: Add 'inbound FilePart/DataPart (text-only input, GH-159)' to the -32005 row and add the -32602 empty-text case to the error table. Amend §5.3 line 339 to state the GH-159 exception: non-text user content parts in any history message end the run with RUN_ERROR, and the thread stays blocked until the client removes that message.
- Codify: A wave that adds a rejection path must grep DESIGN.md for the existing error-code table row and any 'never rejected' wording on the same surface, and update them in the same change.
- sdkCandidate: true

### R6 RT-004 [SDK] — medium — tests/test_gh159_reject_non_text_parts.py
The GH-159 AC requires tests for the resume and stream paths and says an empty string can no longer resume a task. `test_resume_rejects_non_text_and_empty` only sends `taskId="no-such-task"` to `/v1/message:send`. No test creates a real input-required task and then shows four things: a FilePart or empty-text resume returns 415 or 400; the interrupt stays pending and can still be resumed afterwards; `/v1/message:stream` resume is rejected before `_open_stream` subscribes; and the HTTP status is asserted on the resume path.
- Fix: Add a test that drives the example `publish_note` tool to input-required, posts a FilePart resume and an empty-text resume on both `:send` and `:stream`, and asserts 415/-32005 and 400/-32602. Then assert the task is still `input-required`, and that a following text resume succeeds.
- Codify: A rejection test on a resume path must use a real interrupted task and prove the interrupt survives the rejected attempt; a made-up task id only proves the order of the checks.
- sdkCandidate: true

### R6 RT-005 [SDK] — medium — agent_sdk/common/redact.py
`safe_id_text` (line 194) changes ids without saying so. It turns whitespace into `_`, swaps `()[]<>` for fullwidth characters, turns `|` into `/`, and cuts at 256 characters with no marker. Examples: an id 'ACME Corp' renders as 'ACME_Corp' and 'AAPL (US)' renders as 'AAPL_（US）'. These look like real ids, so a text-only MCP model copies them into the next tool call, which then fails or hits the wrong record. That defeats the purpose of GH-156. The CHANGELOG says only 'sanitized and capped'.
- Fix: When `safe_id_text(value) != value`, render the id so the model can tell it was changed: either JSON-quote it with escapes (byte-exact and still unable to forge a delimiter) or append a fixed marker such as ' [id altered; use structuredContent]'. List the exact transformations in the CHANGELOG and in the C-007 registry entry, and add a test for an id containing a space or a parenthesis.
- Codify: Sanitising an identifier that a model will copy back must either keep it exact or mark it as changed; a silently changed id that still looks real is worse than leaving it out.
- sdkCandidate: true

### R6 RT-006 [SDK] — medium — docs/content-types.md
DESIGN.md §4.3 now says the text fallback must carry every identifier a follow-up call needs. But the guidance domain-card authors actually read does not say so. docs/content-types.md (the `_body_text()` example at ~line 66), harness/skills/add-tool/SKILL.md and harness/agents/project/sdk-advisor.md do not mention including ids or `safe_id_text`. Downstream agents' domain cards (for example a PitchBook deal list) will keep leaving ids out of MCP text, which is the same defect GH-156 fixed only for SDK types.
- Fix: Add a rule and example to docs/content-types.md: render every `id`/`*_id` a follow-up tool needs, through `agent_sdk.common.redact.safe_id_text`. Mirror one line into harness/skills/add-tool/SKILL.md (and its template peer per LRN-071/LRN-208) and into the sdk-advisor checklist.
- Codify: A text-fallback contract added to DESIGN.md for SDK types must also reach the agent-facing docs and harness skills, or domain cards keep the old defect.
- sdkCandidate: true

### R6 RT-007 [SDK] — low — agent_sdk/routes/ag_ui.py
`_validate` (line 195) scans every user message in `messages`. `_fold_history` uses only the last `MAX_HISTORY_MESSAGES` (50). A non-text part in a message that has already left the 50-message window, and would never reach the model, still ends every later run with RUN_ERROR. Long threads stay blocked by content that has no effect.
- Fix: Scan the same window the fold uses, `(messages or [])[-MAX_HISTORY_MESSAGES:]`, or document why the full history is scanned. Add a test with a non-text part at position 0 of 60 messages.
- sdkCandidate: true

### R6 RT-008 [SDK] — low — docs/protocols.md
Line 35 says 'Nothing is silently dropped' for AG-UI input. `_fold_history` still silently drops non-text parts in assistant messages, assistant content that is neither a string nor a list (folds to ""), and every message whose role is not user or assistant (system, developer, tool). So the statement is too broad.
- Fix: Narrow the sentence to user messages: 'Non-text parts in user messages are rejected, not dropped; assistant turns with non-text or non-string content and non-user/assistant roles are ignored.'
- sdkCandidate: true

### R6 RT-009 [SDK] — low — agent_sdk/contrib/action_gate/gate.py
The `parse_decision` docstring (line 128) still says an A2A resume carrying only a DataPart or FilePart 'arrives as "" → UNCLEAR'. Since GH-159, routes/a2a.py `_parse_send` rejects that resume with -32005/415 before `deliver_resume`, and an empty-text resume is rejected with -32602. The documented path can no longer happen.
- Fix: Update the docstring: non-text or empty A2A resumes are rejected at the route (GH-159) and never reach the gate; the A2A resume value is always non-empty text.
- sdkCandidate: true

### R6 RT-010 [SDK] — low — REVIEWS.md
Round 12 says it supersedes Round 2's 'Always emit (as null)' for `parentMessageId`. But the Round 2 table row at line 198 is unchanged and gives no pointer, so a reader or auditor who checks Round 2 still sees the old ruling as current.
- Fix: Append '(SUPERSEDED by Round 12 / GH-158: omit when absent)' to the line-198 decision cell.
- sdkCandidate: true

### R6 RT-011 [SDK] — low — tests/test_gh157_mcp_instructions.py
The SI-2 test `test_unauthenticated_initialize_gets_no_instructions` covers only POST /mcp. The legacy POST /mcp/messages path also dispatches `initialize` and is not pinned. `test_undefined_variable_is_error` uses `pytest.raises(Exception, ...)`, which would also pass on an unrelated exception whose text contains 'nope'.
- Fix: Parametrize the unauthenticated test over `/mcp` and `/mcp/messages?session_id=x`, and assert 401 with no instruction text. Narrow the undefined-variable test to `jinja2.UndefinedError` (or the wrapper the build raises).
- sdkCandidate: true

### R6 RT-012 [SDK] — low — agent_sdk/routes/ag_ui.py
The GH-159 ruling gives AG-UI 'the same rule' as A2A. A2A rejects empty or whitespace-only text with -32602. AG-UI accepts a user message with empty content, or a list of empty text parts, and starts a model run on an empty prompt.
- Fix: In `_validate`, when the newest user message folds to empty or whitespace-only text, return 'user message must contain non-empty text'. Or record in docs/protocols.md that AG-UI deliberately allows empty input.
- sdkCandidate: true

### R6 RT-013 [SDK] — low — CHANGELOG.md
The GH-156 entry changes the `to_plain_text()` output of six Standard Profile types and FundPerformance.pb_id rendering. That output is the MCP `tools/call` text and the A2A TextPart, and agents that parse exact text are affected; the entry itself says callers 'will see the extra (id: ...) suffix'. It is filed under `### Fixed` instead of `### ⚠️ Behavior changes`, with no Migration line.
- Fix: Move the GH-156 entry under `### ⚠️ Behavior changes`, with a Migration line: exact-text assertions on these cards must accept the `(id: ...)` suffix, and pb_id characters `= : , @` are no longer converted to fullwidth.
- sdkCandidate: true
