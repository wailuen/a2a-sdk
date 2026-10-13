# SDK issue candidates — w046 (2026-10-13)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GH-156 _safe_id routes ids through _sanitize_cell (safe_cell_text), which rewrites '=', ':', ',' to fullwidth forms, so Graph base64 ids and URN ids in EmailList/CalendarEvents MCP text fallback are corrupted and cannot be copied back into tool calls.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/models/content_types.py
- Rationale: SDK content_types model rendering used by MCP text fallback; fix needs an id-preserving C-007 helper in agent_sdk/common/redact.py.

## Candidate 2: GH-158 fix only changed the table row; the conformance-traps list (line 83) in both .claude and harness copies still flags missing parent_message_id on tool calls as a defect, which will flag the SDK's new wire shape.
- Severity: high
- Component: harness/skill
- File: .claude/skills/ag-ui-check/SKILL.md
- Rationale: Harness skill content shipped with the SDK.

## Candidate 3: Template mirrors of ag-ui-check, add-artifact and new-agent skills were not updated for GH-157/GH-158; template repo has no pending commit, so scaffolded agents keep the stale rule and never learn about mcp_instructions.
- Severity: high
- Component: harness/template
- File: template/.claude/skills/ag-ui-check/SKILL.md
- Rationale: Template scaffold is SDK-owned; AC requires all copies identical.

## Candidate 4: GH-156 sanitization tests cover only EntityList; other renderers (EmailList, CalendarEvents, UserList, UserProfile, DocumentList, FundPerformance) only check id presence, and the renderer-wide guard only greps for _sanitize_cell, so a raw {x.id} regression would pass (LRN-152).
- Severity: high
- Component: protocol/mcp
- File: tests/test_content_types.py
- Rationale: SDK test coverage for content_types renderers that feed MCP/A2A text.

## Candidate 5: _validate rejected non-text parts in any user message of replayed history, so one rejected binary turn bricks every later turn and blocks resume; also scans beyond the 50-message fold window.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: SDK AG-UI protocol route behavior.

## Candidate 6: Client-supplied content[i].type is echoed into RUN_ERROR.message after only isidentifier(); unbounded length (200 KB probe) and no C-007 safe_error_text or allowlist.
- Severity: high
- Component: security
- File: agent_sdk/routes/ag_ui.py
- Rationale: SDK route echoes untrusted input into wire error text (SI-2).

## Candidate 7: _validate skips GH-159 rejection when body['resume'] is merely truthy, but the route treats resume only as a non-empty list; resume=true/'x'/{} bypasses rejection and binary parts are silently dropped with RUN_FINISHED.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: SDK AG-UI route validation bypass.

## Candidate 8: AG-UI rejection checks only the newest user message; non-text parts in other current-turn user messages are silently dropped, narrowing the GH-159 'no silent drop' ruling without record; CHANGELOG overstates the fix.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: SDK AG-UI route conformance to maintainer ruling.

## Candidate 9: GH-157 mcp_instructions lacks the SI-6 build-time secret check (or a recorded docs-only decision) and the SI-2 test that unauthenticated initialize gets no instructions.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/app.py
- Rationale: SDK app build path for MCP initialize instructions; security annotations unmet.

## Candidate 10: GH-158 (parentMessageId key removal) and GH-159 (new 415/-32602 rejections) wire changes are filed under Fixed with inline 'Behavior change' instead of Breaking changes with Migration callouts and spec citations, forfeiting the DESIGN.md §4.0 conformance exemption.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: SDK release changelog governance.

## Candidate 11: New C-007 helper safe_id_text/_ID_NEUTRALISE and the FundPerformance.pb_id rendering change are not declared in any todo Creates/Modifies or the CHANGELOG, so the wave review scope excluded redact.py and related files (LRN-202).
- Severity: high
- Component: security
- File: agent_sdk/common/redact.py
- Rationale: SDK security helper and scope tracking.

## Candidate 12: AG-UI GH-159 narrowing (reject only after last assistant message) is recorded in REVIEWS.md Round 13 as pending ratification with no maintainer reference; its 'cannot brick a thread' claim is false since a kept rejected message fails every later run. Must not release unapproved.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: SDK protocol route diverges from maintainer ruling; release blocker.

## Candidate 13: harness/skills/new-agent/SKILL.md differs from template/.claude/skills/new-agent/SKILL.md (uv vs pip, several hunks), failing the GH-157 'all copies identical' AC and LRN-208.
- Severity: high
- Component: harness/template
- File: harness/skills/new-agent/SKILL.md
- Rationale: Harness skill / template mirror drift.

## Candidate 14: test_skills_have_no_stale_parent_message_id_trap uses 'if p.exists()', so an absent template mirror passes silently (LRN-157); misplaced in GH-156 file and never checks copies are identical.
- Severity: high
- Component: harness/skill
- File: tests/test_gh156_mcp_text_ids.py
- Rationale: SDK test guarding harness skill copies.

## Candidate 15: Registry-wide GH-156 meta-test only collects ids the hand-built sample populates; a new optional id field left None passes unchecked (LRN-241).
- Severity: high
- Component: protocol/mcp
- File: tests/test_content_types.py
- Rationale: SDK content_types test coverage.

## Candidate 16: GH-156 AC requires MCP tools/call content[0].text checks per model, but only EntityList and DocumentList are tested; EmailList, CalendarEvents, UserList, UserProfile lack MCP-level tests.
- Severity: high
- Component: protocol/mcp
- File: tests/test_gh156_mcp_text_ids.py
- Rationale: SDK MCP route test coverage gap against AC.

## Candidate 17: Dict-shaped user content ({type:'binary',data:...}) skips _validate's list check and _fold_history str()s the whole dict, including base64 data, into model input, bypassing GH-159 rejection.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: SDK AG-UI route validation bypass; unmet AC.
