# w046 — GitHub issues 156–159

Sourced from open issues on wailuen/a2a-sdk. Maintainer rulings 2026-10-13:
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/156#issuecomment-6128072842
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/157#issuecomment-6128073215
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/158#issuecomment-6128073645
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/159#issuecomment-6128074134
G1 items are independent and run in parallel. G2 runs after G1 (shares `agent_sdk/routes/ag_ui.py` with GH-158).
Target: next release (version chosen at /sdk-release).

---

- [x] `GH-156` Text fallback of list/profile content types omits item identifiers ‖ group:G1
  - Creates: (modifies `agent_sdk/models/content_types.py`, `tests/test_content_types.py`, `agent_sdk/common/redact.py`, `tests/test_gh156_mcp_text_ids.py`, `workspace/components/README.md`, MCP tools/call test file, `DESIGN.md` §4.3, `CHANGELOG.md`)
  - Reads: `agent_sdk/models/content_types.py` (EntityList `_body_text` ~741, EmailList ~1080, CalendarEvents ~1129, UserProfile ~1193, UserList ~1228, DocumentList ~1265, FundPerformance pb_id handling ~1046), `agent_sdk/routes/mcp.py` `_tool_text` (~515-529), `workspace/learning/LRN-241-hand-listed-text-fallback-field-drift.md`
  - Severity: high
  - Root cause: `_body_text` of six content types prints names/summaries but not the ids that follow-up tools need. MCP uses `to_plain_text()` as the text block; text-only client models cannot chain calls. A2A TextPart and admin try-tool text have the same gap.
  - AC: EntityList, EmailList (id; conversation_id where present), CalendarEvents (id), UserList (id), UserProfile (id and manager id) and DocumentList (id) include each identifier in the text, e.g. `- Databricks (59199-40)`, sanitized and length-capped in the same order as FundPerformance's `pb_id` (`sanitize_text` with max_len, then `_sanitize_cell`).
  - AC: Do NOT switch the MCP text block to serialized JSON; DESIGN.md:376 is unchanged (ruling).
  - AC: Per-model tests assert ids in `to_plain_text()` and in the MCP `tools/call` `content[0].text`. Registry-wide meta-test: for every registered SDK content type, any `id` / `*_id` field of the model or its list items reaches the text (LRN-241: derive from model fields, not a hand list); documented exemptions only.
  - AC: Exact-text test at `tests/test_content_types.py` (~643, DocumentList) updated, not skipped. DESIGN.md §4.3 states the text fallback must carry identifiers needed for follow-up calls. CHANGELOG `[Unreleased]` entry.
  - SI: SI-2 — ids pass through the existing sanitizers; no raw upstream strings.
  - GH: https://github.com/wailuen/a2a-sdk/issues/156
  - Reuses: C-007  # Build the id rendering on C-007 (agent_sdk/common/redact.py: sanitize_text / safe_error_text / safe_cell_text). Do not hand-roll a seventh copy of the FundPerformance pb_id pipeline at each of the six _body_text sites. But C-007's safe_cell_text rewrites characters that real ids contain (see sliceIssues), so add an id-preserving sibling in redact.py instead of reusing safe_cell_text as it is.

- [x] `GH-157` Agents can contribute MCP server instructions ‖ group:G1
  - Creates: (modifies `agent_sdk/app.py`, `agent_sdk/routes/mcp.py`, new `tests/test_gh157_mcp_instructions.py`, `DESIGN.md` §5.5, `docs/` page covering MCP, `harness/skills/add-artifact/SKILL.md`, `harness/skills/new-agent/SKILL.md` and their `.claude/skills/` mirrors if present, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/mcp.py` `_handle_initialize` (~411-459), `agent_sdk/credentials/card.py` `forwarding_instructions` (~42-63), `agent_sdk/app.py` Agent kwargs (~78-92) and system render (~626-634), `agent_sdk/agent/artifacts.py` (~40-67)
  - Severity: medium
  - Root cause: `initialize.instructions` is built only from the credential-forwarding note. Agent rules in `system.md` never reach MCP client models.
  - AC: New `Agent(mcp_instructions: str | None = None)` for persona= agents. With `artifacts_dir=`, an optional `mcp_instructions` artifact (`artifacts/mcp_instructions.md`) is rendered once in `build_app` via ArtifactLoader with the same variables as `system` (agent_name, agent_version, **artifact_vars; StrictUndefined). Setting both is a ValueError at build. No env setting (ruling).
  - AC: Result is stripped and stored on app.state once; build fails with a clear message if longer than 4000 characters.
  - AC: `_handle_initialize` joins the credential note first, then the agent text, separated by a blank line; the `instructions` key is still omitted when both are empty.
  - AC: Tests: artifact present / absent; kwarg; both set → error; joined with credential note; agent text only; neither → key omitted; over cap → build error; undefined template variable → build error.
  - AC: Docs say the text is shown to every MCP client model and must contain no secrets. DESIGN.md §5.5, harness skill mentions (all copies identical), CHANGELOG `[Unreleased]` entry. Template scaffold change, if any, is a separate `template/` repo commit (LRN-071) — never `git add template/` here.
  - GH: https://github.com/wailuen/a2a-sdk/issues/157
  - SI: SI-2  # Has no SI: field but modifies agent_sdk/routes/mcp.py (MCP transport) and joins output from agent_sdk/credentials/card.py forwarding_instructions. The new build errors (over 4000 chars, undefined variable, both kwarg and artifact set) must report only the length or the variable name. They must never include rendered text or artifact_vars values. The text goes to every authenticated MCP client model. initialize stays behind Depends(require_identity) at routes/mcp.py:720; add a test proving an unauthenticated initialize gets no instructions.
  - SI: SI-6  # artifact_vars can carry settings values into mcp_instructions.md, and the result is sent to every MCP client. A docs warning alone does not fail closed. Consider a build-time check that the rendered text contains no SecretStr or credential-field value from settings. At minimum, write SI: SI-6 with the docs-only decision stated.

- [x] `GH-158` AG-UI omits parentMessageId (and any optional event field) instead of sending null ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/ag_ui.py`, `tests/test_ag_ui.py` or new `tests/test_gh158_agui_no_null_fields.py`, `REVIEWS.md`, `.claude/skills/ag-ui-check/SKILL.md` (and `harness/` mirror if present), `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/ag_ui.py` (~232-239, ~269-274), `agent_sdk/common/sse.py`, `REVIEWS.md` Round 2 (~198), `agent_sdk/console/static/chat.js` (~536)
  - Severity: high
  - Root cause: TOOL_CALL_START always sets `parentMessageId = self.last_message_id`, which is None on tool-first turns and resume STARTs, so the wire carries `null`. The reference encoder uses `exclude_none=True`; the field is optional (string or absent).
  - AC: Both START builders omit `parentMessageId` when there is no parent id; a text-then-tool turn still carries the string id.
  - AC: Test that no emitted AG-UI event frame has a top-level `null` value (tool-first turn, text-then-tool turn, resume run). `CUSTOM.value` payloads are exempt (free-form).
  - AC: REVIEWS.md gets a new round recording that this ruling supersedes Round 2's "Always emit (as null)", citing the 158 ruling URL. The ag-ui-check skill line treating a missing optional `parentMessageId` as a defect is corrected. CHANGELOG `[Unreleased]` entry noting the behavior change.
  - GH: https://github.com/wailuen/a2a-sdk/issues/158
  - SI: SI-2  # Modifies agent_sdk/routes/ag_ui.py (AG-UI transport) and has no SI: field. The change only affects wire shape, so the expected impact is none. Add an explicit 'SI: none — wire-shape only, no auth/credential/error-text change' line so the unit redteam does not have to infer it.

- [x] `GH-159` Reject non-text inbound content instead of silently dropping it (A2A + AG-UI) ‖ group:G2
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`, `tests/test_protocol_wire.py`, new `tests/test_gh159_reject_non_text_parts.py`, `DESIGN.md` (~356), `docs/protocols.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/a2a.py` (`_message_text` ~363, `_parse_send` ~403-432, new-task ~480, resume ~509, stream ~784), `agent_sdk/models/a2a.py` (~70-77), `agent_sdk/routes/ag_ui.py` `_fold_history` (~79-121), `agent_sdk/agent_card.py` (~203), `.claude/reference/a2a-protocol-0_3_0.md`
  - Severity: high
  - Root cause: A2A keeps only TextPart text and feeds the model `" "` when nothing is left; FilePart/DataPart content is dropped silently while the card advertises `text/plain` input only. AG-UI `_fold_history` likewise drops non-text content parts.
  - AC: A2A: one shared helper rejects any message containing a non-TextPart with -32005 ContentTypeNotSupported (HTTP 415 on REST bindings), before any task is created, on message/send, message/stream and the interrupted-task resume path. Mixed text + unsupported parts reject the whole message. The error names the part kind only, never content (SI-2).
  - AC: A2A: a message whose joined text is empty is rejected with -32602; the `or " "` fallback is removed; an empty string can no longer resume a task.
  - AC: AG-UI: user messages with non-text content parts are rejected before a run starts through the route's existing request-validation error path, with a clear error naming the part type; no silent drop. Text-only list content still works.
  - AC: Card stays `defaultInputModes: ["text/plain"]`; docs/protocols.md states input is text only. Inbound A2UI actions are out of scope (separate future feature).
  - AC: Tests: file-only, data-only, mixed, empty text, resume, stream, AG-UI non-text part; assert no task/run is created on rejection. The existing bare-array DataPart test (-32602 from model validation) is reconciled with the new ordering, not skipped. DESIGN.md (~356) and CHANGELOG `[Unreleased]` updated.
  - GH: https://github.com/wailuen/a2a-sdk/issues/159
  - Reuses: C-007  # The AG-UI error that 'names the part type' would show the client's raw content[i].type string, which is not checked against any schema. Map it to a fixed allowlist label, or pass it through C-007 safe_error_text(max_len=...) before it reaches RUN_ERROR.message. A2A part kinds are already restricted by the pydantic discriminator, so use the literal kind name there.
  - SI: SI-2  # Has no SI: field, although it modifies A2A and AG-UI transport routes and adds new error text. The AC says 'names the part kind only'. Write that as SI: SI-2. Also state that FilePart name, mimeType, uri and bytes, DataPart data, and AG-UI part fields other than a mapped type label never appear in the error or the logs. Rejection must stay inside the require_identity-guarded handlers, after guard_origin, so an unauthenticated caller cannot use it to probe which content types are accepted.

---

**Archived 2026-10-13 (by /gh-review).** sdk-wave run wf_be168e32-90b: all four items landed; phase
redteam clean by round 6; protocol audits 0 critical / 0 high. Wave reported testsRed only because the
.venv still carried the pre-0.10.0 install (test_version) — reinstalled, suite green. All 17 sdk-candidates
re-verified: 14 fixed, 3 minor. Maintainer refined the GH-159 AG-UI scope to the current turn only
(issue 159 comment 6135432947, REVIEWS.md Round 14), applied by hand. Template skill mirrors pushed by the
wave as wailuen/a2a-agent-template c9684be and 6b7a717.
