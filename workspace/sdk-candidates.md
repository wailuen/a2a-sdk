# SDK issue candidates — w050 (2026-10-15)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GH-174 has no CHANGELOG [Unreleased] entry. The ruling URL, the text-format-change flag and the list of label sites still using safe_cell_text are all missing.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: Release notes for an SDK change. Not agent code.

## Candidate 2: safe_label_text cuts the text through safe_error_text before stripping control characters, and adds no '…' marker. Leading whitespace can use up the label budget. It should build on safe_line_text.
- Severity: high
- Component: security
- File: agent_sdk/common/redact.py
- Rationale: This is the shared SDK text sanitizer. A second truncation rule breaks the rule that every cut is visible.

## Candidate 3: [Unreleased] has no entries for GH-175, GH-176 (a breaking boot check that needs a Migration line) or GH-177. The code for all three is already in the tree.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: Release-gate documentation for SDK code. Releasing now would ship a breaking change with no notes.

## Candidate 4: safe_label_text adds a private _LABEL_LOOKALIKES table instead of reusing the C-007 maps _BARE_SEPARATORS/_SPACED_SEPARATORS. Labels and data cells can drift onto different look-alike characters.
- Severity: high
- Component: security
- File: agent_sdk/common/redact.py
- Rationale: Duplicate SDK sanitizer table that goes against the Reuses C-007 rule.

## Candidate 5: No test covers the GH-175 SI-2 rule that the cut happens only after the control-character collapse. No test puts hostile control characters or line breaks at the cut point.
- Severity: high
- Component: security
- File: tests/test_gh175_title_cap_marker.py
- Rationale: Missing test for an SDK sanitizer's security rule. If the cut moves back before the collapse, no test fails.

## Candidate 6: In register_content_type, the PascalCase regex check still runs after the RESERVED, Basic Catalog and registry case-fold loops. The CHANGELOG claim that the check runs first is false. test_gh172 still pins the old order.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Rationale: Component-name validation in the SDK's A2UI content-type registry.

## Candidate 7: Three wire breaks are not under Breaking changes and have no Migration line. GH-177 drops the web_url and last_modified keys. GH-179(5) makes MarketBriefing.wire() return a str, which breaks the dict check at runner.py:318 for subclasses. GH-179(3) adds new ValidationErrors.
- Severity: high
- Component: protocol/a2ui
- File: CHANGELOG.md
- Rationale: Undocumented breaks in the SDK wire contract for content types.

## Candidate 8: DocumentList._body_text prefers last_modified, but the wire serializer prefers modified. When both are set, the text part and the data part of one reply show different dates.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Rationale: The SDK's dual-part artifact contradicts itself across A2A and MCP.

## Candidate 9: The plain-text fallback never shows modified_by, and the test named for it never asserts it.
- Severity: high
- Component: protocol/a2ui
- File: tests/test_gh177_document_contract_keys.py
- Rationale: The SDK text fallback drops a documented wire field (LRN-241).

## Candidate 10: With MarketBriefing.wire() returning a str, the AG-UI AGENT_ARTIFACT frame's data no longer matches the advertised object valueSchema and drops the metadata envelope. A2A and AG-UI now send different shapes for the same artifact.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/models/content_types.py
- Rationale: Breaks the SDK's AG-UI wire contract and the GH-63 metadata disclosure.

## Candidate 11: runner.py, ag_ui.py and agent_card.py changed behaviour for GH-179 item 5, but they are not on the todo's Modifies line (LRN-359/361).
- Severity: high
- Component: harness/workflow
- File: agent_sdk/agent/runner.py
- Rationale: Todo scope-tracking gap in the wave workflow.

## Candidate 12: The new MarketBriefing branch fails mypy because a dict[str, str] variable is given a metadata value. This blocks the /sdk-test release gate.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: Type error in an SDK protocol route that blocks the release.

## Candidate 13: The AG-UI AGENT_ARTIFACT data for MarketBriefing changed to {markdown, metadata?} with no maintainer ruling. It diverges from the A2A DataPart and is not documented in DESIGN.md.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: Unapproved breaking change to the SDK's public AG-UI wire.

## Candidate 14: Removing the _Wire._rejects_non_finite opt-out is listed under Fixed, not Breaking. Subclasses that still set the flag now silently turn NaN into None.
- Severity: high
- Component: protocol/a2ui
- File: CHANGELOG.md
- Rationale: Behaviour change in an SDK base-class validator.

## Candidate 15: [Unreleased] does not name the changed files a2a.py, ag_ui.py, a2ui.js or content_types.py. It has no Added section for safe_label_text, TITLE_TEXT_MAX_LEN, LINE_TEXT_CUT_MARKER or BASIC_CATALOG_COMPONENTS (LRN-322).
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: Release notes incomplete for SDK files and new public symbols.

## Candidate 16: The strict-serialize -32006 path is untested for tasks/list, tasks/cancel, the resume branch and the sync_reply bare-Message branch.
- Severity: high
- Component: protocol/a2a
- File: tests/test_gh179_conformance_drift.py
- Rationale: Missing per-route coverage of the SDK's A2A error path.

## Candidate 17: The private _strict_json_response relies on Starlette's json.dumps(allow_nan=False) default instead of a shared dumps_strict in json_strict.py. sse.py and mcp.py still serialize inline.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: The SDK route guard depends on a framework default and ignores the Reuses C-007 rule.

## Candidate 18: The _rejects_non_finite removal guard checks only __private_attributes__. The documented ClassVar[bool] form is accepted silently, so the promised TypeError never fires.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Rationale: The SDK base-class guard misses the canonical declaration form.

## Candidate 19: json_strict.py (new public dumps_strict), sse.py and routes/mcp.py changed, but they are on no todo Modifies line and have no CHANGELOG entry. dumps_strict has no Added bullet.
- Severity: high
- Component: sdk/build
- File: agent_sdk/common/json_strict.py
- Rationale: New public SDK API with no scope entry and no release note.

## Candidate 20: The GH-178 Breaking bullet (removed flag plus a TypeError at class definition) cites no maintainer ruling. Issue 178 has no comments, and the fail-loud guard goes beyond the AC.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: A breaking SDK change with no recorded approval (LRN-357).

## Candidate 21: The Reuses C-021 and C-036 directives are unmet. BASIC_CATALOG_COMPONENTS lives in content_types.py and is a third copy. The C-021, C-034 and C-036 registry rows are not updated with placement notes or cross-references.
- Severity: high
- Component: harness/workflow
- File: workspace/components/README.md
- Rationale: Drift in the component registry that the harness wave process maintains.

## Candidate 22: The legacy MCP SSE queue now uses dumps_strict with ensure_ascii=False. A lone-surrogate tool result passes _is_writable, then raises UnicodeEncodeError at encode time and kills the session stream. The CHANGELOG claim 'bytes unchanged' is false.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: An SDK MCP transport crash that client input or upstream data can trigger.

## Candidate 23: The build_artifact gate uses json.dumps with no UTF-8 check, not dumps_strict. A lone-surrogate artifact commits as COMPLETED, then every tasks/get and tasks/list read returns 502.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py
- Rationale: The SDK task-commit gate lets an artifact through that later poisons every read of the task.

## Candidate 24: loads_strict accepts escapes that decode to a lone surrogate. On A2A this gives 502 and blocks task listing. On AG-UI the RUN_STARTED write raises an unhandled ValueError with no terminal frame.
- Severity: high
- Component: security
- File: agent_sdk/common/json_strict.py
- Rationale: Client-caused denial of service through the SDK's ingress parser.

## Candidate 25: Model text, progress, note and tool-progress messages reach set_task_status with no encodability check. One lone surrogate makes tasks/get and the whole tasks/list return 502. The CHANGELOG claim that such text 'can no longer be stored in a task' is false.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py
- Rationale: The SDK store-commit point does not enforce the rule.

## Candidate 26: Now that modified wins in the text fallback and the wire remap, a last_modified value that differs from modified appears on no surface. That breaks the GH-177 AC that the text must stay as today.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Rationale: The SDK content-type remap silently loses data that downstream agents set.

## Candidate 27: renderDocumentList never reads d.link, but the CHANGELOG Breaking entry says the console reads modified/link.
- Severity: high
- Component: sdk/console
- File: agent_sdk/console/static/a2ui.js
- Rationale: An SDK console renderer gap, and release notes that do not match the code.

## Candidate 28: Scope drift: changed test files and uv.lock are on no todo line. A listed file has no diff. The OAuth /register behaviour change caused by loads_strict is not in the CHANGELOG.
- Severity: high
- Component: harness/workflow
- File: workspace/todos/active/w050-gh-issues.md
- Rationale: The wave todo tracking process missed changes (LRN-361).

## Candidate 29: workspace/components/README.md was edited, but no todo lists it under Creates/Modifies. GH-175 lists it only under Reads.
- Severity: high
- Component: harness/workflow
- File: workspace/todos/active/w050-gh-issues.md
- Rationale: Todo scope-tracking gap in the wave workflow (LRN-359).

## Candidate 30: DocumentItem._wire_contract_keys is a model-wide model_serializer. It removes last_modified/web_url from every model_dump, including the LLM tool-result fold, round trips and the JSON schema. The ruling limited the drop to the wire.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Rationale: An SDK serializer change that leaks past the wire into the agent loop and the model API.
