wave: w047
scope: group
group: G1
date: 2026-10-13

Non-blocking — these did not block w047's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/common/redact.py
- description: Raised in four rounds. safe_line_text (line 184) caps at 256 chars with no marker (it calls safe_error_text, which slices value[:max_len] with no ellipsis). The slots moved to it (titles, EntityList item names and summaries) previously used safe_cell_text, which is full length (max_len=None). So any value over 256 chars is now silently cut in to_plain_text, the MCP text block, the A2A TextPart and the admin try-tool. Verified: a 600-char EntityList summary renders as a 262-char line; a 1000-char summary renders 256. The model gets no sign that text is missing — the same "silent cut loses data" defect this wave fixes in GH-168. No CHANGELOG line mentions the new truncation.
- fix: Pass max_len=None, or a much larger / per-slot cap, for summary and preview slots, and append an explicit marker ('…' or `[+N chars]`) when safe_line_text truncates. Or document the cap in CHANGELOG (GH-167 entry, as a text-format change) and DESIGN as a deliberate behavior change. Add a test that a 1000-char summary either survives or shows the marker.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in three rounds (also filed against DESIGN.md). GH-167 AC "Ids move to their own labelled line where they were joined to a name" is met for EntityList only. UserList (line 1271), UserProfile/PersonProfile (`{name} <{email}> (id: ...)`, lines 1231, 1241 incl. manager), DocumentList (line 1310), CalendarEvents (line 1176) and EmailList (lines 1119-1122) still join `(id: …)` to the name, and those names still go through safe_cell_text. UserSummary(display_name='Smith, John') renders 'Smith， John <j@x.com> (id: u1)' — the ruling's own example — and DocumentItem 'Budget (draft), v2.xlsx' renders 'Budget （draft）， v2.xlsx'. The ruling lists as-of headers as standalone slots, but MarketBriefing still renders `title (as_of)` joined. DESIGN.md:214 says "Ids always sit on their own labelled line", which is false.
- fix: Either move the ids for UserList, UserProfile (and manager), DocumentList (and MarketBriefing's as_of) onto their own `    id: …` line, render the now-standalone names with _sanitize_line, update GH-156 id tests and add a CHANGELOG text-format note. Or get a written maintainer ruling narrowing the AC to EntityList, record it in the wave file, and narrow DESIGN.md §4.0, docs/content-types.md and CHANGELOG wording to "EntityList item ids", listing the renderers that still join ids.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/models/content_types.py
- description: The EntityList name slot (line 779) now uses safe_line_text, so a hostile name forges an id pair inline. EntityItem(id='real-1', name='Acme (id: 666)') renders '  - Acme (id: 666)' then '    id: real-1'. '(id: X)' is the id syntax every other renderer uses (EmailList, CalendarEvents, UserList, UserProfile, DocumentList), and 'Name (666)' is exactly the pre-GH-167 documented EntityList id shape. DESIGN.md §4.0 (GH-167 paragraph) says a standalone slot "cannot forge a row, column, (id) or k=v pair", which is false (also false for EmailList previews). No test covers this.
- fix: Either neutralise only the '(id:' pattern and a trailing '(…)' in name slots, or put the id line before the name. Correct the DESIGN.md claim to state the remaining risk. Add a test that a name of 'X (id: 666)' cannot be read as an id next to the real id line.
- sdkCandidate: true

### RT-004
- severity: medium
- file: CHANGELOG.md
- description: Raised in two rounds. The EntityList to_plain_text() format change (`  - Name (id)` becomes `  - Name` plus `    id: <id>`, content_types.py:779-780) is filed under '### Changed'. The text fallback is a documented contract (GH-156: DESIGN §4.0, MCP tools/call text block, A2A TextPart), and the CHANGELOG itself says readers that parsed `Name (id)` must change. DESIGN §4.0 requires a Breaking entry with Migration for a consumer-visible format break. The old test was literally named test_entity_list_text_carries_id_in_documented_shape.
- fix: Move the EntityList text-format part of the GH-167 entry under '### 🔴 Breaking changes' with a `**Migration:**` line: read the `id:` line under each item instead of the `(id)` suffix.
- sdkCandidate: true

### RT-005
- severity: medium
- file: CHANGELOG.md
- description: The GH-167 entry (line 12) says `EmailList` previews now use `safe_line_text`. The code at agent_sdk/models/content_types.py:1124 still renders `m.preview` through `_sanitize_cell`, and DESIGN.md:214 and docs/content-types.md both say the preview deliberately keeps `safe_cell_text`. The public changelog contradicts the code and the design doc.
- fix: Remove `EmailList` previews from the list of slots that use safe_line_text in CHANGELOG.md:12. Add a short note that `EmailList.preview` keeps safe_cell_text because it sits under single-line ` | ` rows that carry `(id: ...)` pairs.
- sdkCandidate: true

### RT-006
- severity: medium
- file: agent_sdk/models/content_types.py
- description: The GH-167 ruling (issue 167 comment 6137225466) says titles sitting alone on a line keep ASCII. KpiCard (line 604) and ComparisonTable (line 720) titles still go through `_sanitize_cell`, so `Revenue (EU)` still renders with full-width brackets. This forgery trade-off was chosen by the wave, not approved by the maintainer; it is documented only in DESIGN.md:214 and CHANGELOG.
- fix: Either (a) make the title unable to look like a data row (e.g. indent KpiCard metric rows or prefix the title line) so the title can use safe_line_text as the ruling says, or (b) bring the deviation to the maintainer and record their approval (a GitHub comment URL) in the wave file. A wave sign-off alone is only a proposal.
- sdkCandidate: true
- status: RESOLVED (w047 fix-loop round 6 debug) via option (a). KpiCard metric rows and ComparisonTable header/rule/rows are indented two spaces; both titles use plain safe_line_text (no swap). The interim `separators=` option on safe_line_text was removed so the ruling stays literal.

### RT-007
- severity: medium
- file: tests/test_content_types.py
- description: GH-167 AC "existing separator/structure-forgery tests distinguish standalone from joined slots" is not met. The GH-130 meta-test test_gh130_all_profile_renderers_sanitize_before_joining (line 955) only checks that '_sanitize_cell(' appears somewhere in the source. Nothing checks that a _sanitize_line(...) call is the last thing on its line. A future renderer can write f'{_sanitize_line(x)} | {y}' and every test still passes.
- fix: Add an AST meta-test over _body_text bodies: every _sanitize_line call must be the final FormattedValue of its f-string or a whole list element, with no literal text after it.
- sdkCandidate: true

### RT-008
- severity: medium
- file: tests/test_a2ui_wire.py
- description: Raised in three rounds. The GH-169 plan annotation (Reuses: C-020) required the regression test to reuse the existing parity helpers _declared_wire_keys and _compact_schema_top_level_keys rather than add new string checks. The landed test_system_prompt_forbids_model_written_component_json (line 1519) uses only substring checks and never calls those helpers, so nothing proves the reworded 'Reference shapes of tool output' examples and compact schemas still match the registered ContentModel wire keys.
- fix: In the GH-169 test, loop over the examples under the new heading and every compact schema, and assert their top-level keys match _declared_wire_keys(cls) and _compact_schema_top_level_keys for each registered component.
- sdkCandidate: true

### RT-009
- severity: medium
- file: agent_sdk/a2ui/catalog.py
- description: `get_system_prompt_section` (lines 258-266) now tells the model that tools deliver these cards automatically, but still lists every registered content type, filtered only by `a2ui_allowed_components` (app.py:591, 700). It never checks which components a registered tool actually `emits=`. In an agent where no tool emits a given component, or none emits at all, the prompt claims cards the user will never see, and the model may say 'see the chart above' with nothing rendered. GH-169's own root cause is that cards come only from tools with `emits=`.
- fix: In build_app, collect the set of `emits.component` values from the ToolRegistry, intersect it with allowed_components, and pass the result to get_system_prompt_section. Return '' when no tool emits anything. Add a test where an agent with no emitting tools gets no A2UI section.
- sdkCandidate: true

### RT-010
- severity: medium
- file: agent_sdk/__init__.py
- description: Raised in three rounds (also filed against workspace/components/README.md). safe_line_text (and LINE_TEXT_MAX_LEN) is a new public helper that docs/content-types.md tells domain-card authors to use, but it is not re-exported from agent_sdk/__init__.py, while siblings safe_cell_text, safe_block_text and safe_error_text are (line 23, __all__ line 46). It is also missing from the C-007 entry in workspace/components/README.md, so future renderers will not find it and may add a fifth variant.
- fix: Re-export safe_line_text from agent_sdk/__init__.py, add it to __all__, and reference agent_sdk.safe_line_text in docs/content-types.md. Add a C-007 sub-entry for `safe_line_text(value, *, max_len=256)` (GH-167): thin wrapper over safe_error_text for values alone on a line, keeps separators; use safe_cell_text for joined slots.
- sdkCandidate: true

### RT-011
- severity: medium
- file: agent_sdk/config.py
- description: hide_input_in_errors=True only cleans str(ValidationError). exc.errors() and exc.json() still carry the full raw settings dict. Verified: with MASTER_KEY=SECRETMARKER123 and DEV_MODE=false, both `'SECRETMARKER' in repr(e.errors())` and `'SECRETMARKER' in e.json()` are True. DESIGN.md:436 ("validation errors strip input values") and the CHANGELOG GH-160 Security entry overstate the protection. An agent repo or error reporter that logs errors() or json() (LRN-214-style catch-alls, Sentry's pydantic integration) still leaks MASTER_KEY. tests/test_config.py only checks str().
- fix: Narrow the DESIGN.md and CHANGELOG wording to "the string form of the error". Either wrap settings construction (build_app / example agent) so a settings ValidationError is re-raised with only loc and msg, or document that errors()/json() must never be logged. Add a test asserting the chosen behaviour for errors().
- sdkCandidate: true

### RT-012
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: Raised in two rounds. The LRN-214 Check (`grep logger.exception` in mcp.py/admin.py must find no match) fails at line 407: the JSON-RPC dispatch catch-all still calls `logger.exception("mcp dispatch internal error method=%s", method)`, which formats any exception message (e.g. a pydantic ValidationError with `input_value=`) and logs the raw client-supplied `method` (unsanitised user input, SI-2). This code predates the wave (v0.5.12) and is outside G1's declared scope, so it is not attributed to G1.
- fix: In a separate scoped change, replace it with logger.error('mcp dispatch internal error type=%s at=%s', type(exc).__name__, frame_locations(exc)) and pass `method` through safe_error_text/sanitize_text, matching the tools/call catch-all at line ~621. Or narrow LRN-214's Check to the tools/call catch-alls it was written for. Track as its own issue.
- sdkCandidate: true

### RT-013
- severity: medium
- file: harness/workflows/wave-cycle.js
- description: Raised in three rounds (also filed against harness/wave_scope.py). The GH-164 path-acceptance rule now exists in several hand-written copies: the Parse prompt prose, harness/wave_scope.py (_looks_like_path, extract_wave_scope, _PATH_EXTENSIONS, _ROOT_LEVEL_EXTENSIONS, _KNOWN_DOTFILES), and inline EXT/ROOT/DOT/BAD/ok() Python pasted into all wave-cycle.js copies and sdk-wave.js (~line 841). No test checks they stay the same, and they already differ: the inline scan rejects `template/` paths and skips `[~]` todos, while wave_scope.py accepts `template/.gitignore` and `template/uv.lock` (asserted by tests). The next widening of either side will make Parse abort with scope-scan-mismatch or silently narrow scope. The wave_scope.py module docstring (lines 1-20) still says Parse runs no deterministic extraction, and the _looks_like_path docstring (~line 82, "slash-less token ... ROOT-LEVEL extensions (.md/.json/.toml/.yaml/.yml)") was not updated for .lock or the dotfiles.
- fix: Add a parity test in tests/test_wave_scope_extraction.py that extracts the inline script from each workflow copy, runs it on a shared fixture (tokens from test_gh164_known_lockfiles_and_dotfiles_are_scope, test_gh164_still_rejected, a `[~]` todo and a `template/` path), and compares with extract_wave_scope after the same exclusions — or asserts EXT/ROOT/DOT equal the wave_scope.py constants. Add the template/ exclusion to wave_scope.py or document why they differ. Better: have the scan call `python3 harness/wave_scope.py` where it exists. Update both docstrings.
- sdkCandidate: true

### RT-014
- severity: medium
- file: .claude/workflows/sdk-wave.js
- description: The GH-164 deterministic scan (sdk-wave.js ~773-817; harness/workflows/wave-cycle.js ~832-876) checks only `wave.allScope`. Each group's `g.creates`/`g.modifies`/`g.scope` still comes only from the AI parse, and the per-group implement, unit-redteam and undeclared-scope gates use g.scope. The AI can keep a path in allScope but drop it from its group, and that group runs with an undetected narrowed scope — the GH-164 failure mode one level down.
- fix: Have the scan script print paths per todo or per group (keyed by the `‖ group:X` label), check that each group's g.scope contains its scanned paths, and abort with `scope-scan-mismatch` naming the group. Keep all wave-cycle.js copies byte-identical and mirror the change in sdk-wave.js.
- sdkCandidate: true

### RT-015
- severity: medium
- file: tests/test_gh152_idp_authorize_flow.py
- description: GH-161 changed `idp_settings()` (line 98) to default `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=True`, but this file is not in the GH-161 Creates:/Modifies: list or anywhere in the G1 scope. The undeclared-scope and archive gates key off the declared scope, so this is unreviewed scope drift that can block or confuse archive.
- fix: Add `tests/test_gh152_idp_authorize_flow.py` to the GH-161 `Creates: (modifies ...)` list in workspace/todos/active/w047-gh-issues.md.
- sdkCandidate: true

### RT-016
- severity: low
- file: agent_sdk/a2ui/catalog.py
- description: Raised in two rounds. GH-169 leftovers: the FundPerformance note (~line 277) still tells the model to 'emit' pbId, contradicting the new "Do not write component JSON" line. The section heading is still '## A2UI Output Format'. The get_system_prompt_section docstring still says 'few-shot example' and 'output shapes it isn't permitted to produce'.
- fix: Reword the FundPerformance note to 'pbId comes only from tool results; never state or invent one' (keep the 'never invent' text the regression test asserts). Rename the heading, e.g. '## A2UI cards (delivered by tools)'. Update the docstring to say these are reference shapes of tool output.
- sdkCandidate: true

### RT-017
- severity: low
- file: harness/workflows/wave-cycle.js
- description: Raised in three rounds (also filed against .claude/workflows/sdk-wave.js). The RT-003 SHARED_TREE_GIT_BAN (line 665), appended to every agent prompt in all wave-cycle.js copies and sdk-wave.js, is a workflow behaviour change outside every G1 AC, with no CHANGELOG [Unreleased] entry and no test showing it is present in all copies. It also lands right after the `PY` heredoc terminator of the scope-scan prompt — the one prompt that asks the agent to run text exactly as written.
- fix: Add a CHANGELOG [Unreleased] Fixed line for the shared-working-tree git ban and a static test asserting callAgent appends SHARED_TREE_GIT_BAN in every workflow copy. For the scope-scan call, put the ban before the script or tell the agent the script ends at `PY`.
- sdkCandidate: true

### RT-018
- severity: low
- file: agent_sdk/models/content_types.py
- description: The EntityList fallback title `_sanitize_cell(f"{self.entity_type} list")` (line 774) is a standalone slot but still uses the joined-slot helper, so an entity_type like 'company, private' is mangled while an explicit title is not. Separately, ADR a003 D13's body (lines ~254-256) still states the Entra GUID exemption without a 'superseded by D14' marker.
- fix: Use _sanitize_line for the fallback title. Add '(superseded by D14 for the Entra exemption)' to the D13 heading.
- sdkCandidate: true

### RT-019
- severity: low
- file: DESIGN.md
- description: DESIGN.md:214 says KpiCard and ComparisonTable titles 'keep safe_cell_text (line-break and control-char collapse, 256-char cap, separators kept)'. That parenthetical describes safe_line_text; safe_cell_text has no cap and swaps the separators. The same paragraph's trade-off sentence ("cannot forge a row, column, (id) or k=v pair") is false (see RT-003).
- fix: Move the parenthetical so it describes safe_line_text. Describe safe_cell_text as full length with separators swapped. Reword the trade-off sentence to match the RT-003 fix.
- sdkCandidate: true

### RT-020
- severity: low
- file: docs/security.md
- description: Line 43 still calls `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE` / `_REQUIRED_GROUP` 'Optional', and the ADR a003 settings table still lists them as optional claim values. After GH-161, boot requires one of them or the explicit opt-out for every issuer.
- fix: Reword docs/security.md:43 and the ADR a003 table rows to say one of role, group or ALLOW_ALL_ISSUER_USERS=true is required (D14).
- sdkCandidate: true

### RT-021
- severity: low
- file: tests/test_content_types.py
- description: Raised in two rounds. test_standalone_slots_survive_unchanged (line 1339) imports KpiCard and MetricItem but never uses them.
- fix: Drop KpiCard and MetricItem from that import line.
- sdkCandidate: true

### RT-022
- severity: low
- file: .claude/workflows/sdk-wave.js
- description: The scope-scan command builds `python3 - ' + WAVE_FILE + ' <<'PY'` without shell quoting. A wave-file path with a space or shell metacharacter would break the scan or run unintended shell. The scan fails closed (scope-scan-failed), but the cause would be unclear.
- fix: Quote the argument with a single-quote shell-escape helper, or reject WAVE_FILE values outside [A-Za-z0-9._/-] before building the command. Apply to all copies.
- sdkCandidate: true
