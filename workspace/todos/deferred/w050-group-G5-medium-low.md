wave: w050
scope: group
group: G5
date: 2026-10-15

Non-blocking — these did not block w050's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G5. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

Note on the MarketBriefing AG-UI shape: earlier rounds described the AG-UI `AGENT_ARTIFACT` data as
`{"markdown", "metadata"?}`. The code as archived (routes/ag_ui.py:387-390) sends
`payload.model_dump(mode="json", by_alias=True, exclude_none=True)`, i.e. the full field dict, matching the
non-A2UI A2A DataPart. RT-005/RT-006/RT-007 below are written against the archived code.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: Raised in four rounds. Item 9's strict-serialize helper landed as the private `_strict_json_response` in routes/a2a.py (around line 540). The todo's C-007 reuse note (LRN-364) asked for a shared `dumps_strict` next to `loads_strict` in agent_sdk/common/json_strict.py, used by sse.py:25 and routes/mcp.py:361/1200 too. Those sites still call `json.dumps(..., allow_nan=False)` inline, so the SDK now has four separate strict-write paths (runner.py:471 inline, sse.py:25, mcp.py `_is_writable` / 361 / 1200, and a2a.py). The a2a.py helper also only works because Starlette's `JSONResponse.render` happens to call `json.dumps(allow_nan=False)` in its constructor — an implicit dependency on framework internals. The helper is not registered in workspace/components/README.md.
- fix: Add `dumps_strict(obj) -> str` (and optionally `is_strict_json_writable` / a `strict_json_response` wrapper) to agent_sdk/common/json_strict.py and export it. It should call `json.dumps(..., allow_nan=False, ensure_ascii=False, separators=(",", ":"))` and turn ValueError/TypeError into one fixed error. Have `_strict_json_response` call it and return `Response(body, media_type="application/json")`. Move runner.build_artifact's check, sse.py `sse_data` and mcp.py's writers to the same helper. Register it under C-007 (or a new C-NNN) in workspace/components/README.md.
- codify: A strict-JSON writer must state `allow_nan=False` itself in one shared helper; leaning on a framework's default serializer settings is an invisible contract that a framework upgrade can break.
- sdkCandidate: true

### RT-002
- severity: medium
- file: tests/test_gh179_conformance_drift.py
- description: Raised in four rounds. Item 9 routes six non-stream return sites through `_strict_json_response`: message:send resume (a2a.py:586), the bare-Message sync_reply path (a2a.py:603), the main message:send path, tasks/list (a2a.py:929), tasks/get and tasks/cancel (a2a.py:1058). Only two have a route test (main message:send via monkeypatched `_task_wire`, and tasks/get). tasks/list, tasks/cancel, the resume path and the sync_reply path have none. The todo's SI-2 note said "Every non-stream route needs the helper and a test", and LRN-364 (high) says to add a route test for every surface. A later edit that reverts any of these four sites to a bare `JSONResponse` would leave the suite green.
- fix: Add parametrised route tests that put a NaN into record.task.metadata (or monkeypatch `_task_wire` / `Message.wire`) for GET /v1/tasks, POST /v1/tasks/{id}:cancel, the resume branch of message:send and the sync_reply branch. Each must assert HTTP 502, the exact body `{"error":{"code":-32006,"message":"invalid agent response"}}`, and no nan/inf in the response text. Optionally add a grep test that a2a.py has no bare `return JSONResponse(` outside the helper.
- codify: When one strict-serialize guard is applied to N return sites, write N route tests; a guard with no test is not verified.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: Raised in two rounds. On the -32006 path, `_strict_json_response` (lines 540-551) forwards the success-path headers into `a2a_error`. In tasks/get, tasks/cancel and the message:send paths, `_echo_a2ui_if_present` has already set the `X-A2A-Extensions` A2UI echo for a body that is never delivered, so a 502 error claims the A2UI extension was activated. This breaks the RT-B-203 rule and the `a2a_error` contract (wire_errors.py:41-50: pass headers only once you know what was really activated for THIS response), and contradicts the tasks_cancel comment that error responses carry no echo (cf. test_tasks_get_not_found_never_echoes_credential_forwarding).
- fix: In the except branch, call `a2a_error(A2A_INVALID_AGENT_RESPONSE, "invalid agent response")` with no headers, or with a copy of the headers minus `X-A2A-Extensions`. Add a test where a task with an A2UI part plus a NaN gets 502 with no `X-A2A-Extensions` header.
- sdkCandidate: true

### RT-004
- severity: medium
- file: workspace/components/README.md
- description: Raised in four rounds. The C-038 FINITE_FLOAT_GUARD entry (line 207) still says "Classes with `_rejects_non_finite = True` opt out of the coercion", but G5 removed that hook from `_Wire` and setting it now raises TypeError. The todo's C-038 reuse note said to update the entry if the hook was removed. The entry also still says `_assert_finite` covers only metadata and free-form dicts "and does not yet delegate here", and does not list the new callers ComparisonTable.rows and CategoryValue.metadata. A downstream author who reads the registry will try an opt-out that now breaks their class.
- fix: Rewrite the C-038 entry. Replace the opt-out sentence with: the `_rejects_non_finite` opt-out was removed in GH-178/GH-179 and setting it raises TypeError at class definition. List the current `_assert_finite` callers: ContentModel.metadata, ChartSection.data, TableSection.data, BriefingKpiItem.value, ComparisonTable.rows and CategoryValue.metadata. Note that the class-keyed plans/memos are now weak-keyed (GH-179 item 8).
- sdkCandidate: true

### RT-005
- severity: medium
- file: docs/content-types.md
- description: Raised in four rounds. Lines 128-129 say "`MarketBriefing.wire()` returns the `to_markdown()` string, the same value the A2UI, AG-UI and MCP surfaces already carry". That is false. Only the A2UI `updateDataModel` value is the bare markdown string. The AG-UI `AGENT_ARTIFACT` data is the field dict (routes/ag_ui.py:387-390), MCP structuredContent is `{"markdown": ...}` (mcp.py:740-746), and the non-A2UI A2A DataPart is the field dict (runner.build_artifact model_dump branch). A downstream renderer that trusts the sentence will parse AG-UI or MCP output wrongly. Related: the ag_ui.py comment near line 390 (in an earlier draft) said metadata is kept "as the MCP surface does", but MCP structuredContent omits metadata — check the current comment for the same claim.
- fix: Rewrite the sentence to list each surface: A2UI updateDataModel value = bare markdown string; AG-UI AGENT_ARTIFACT data = field dict (model_dump, metadata included); MCP structuredContent = `{"markdown": <str>}` (GH-105); A2A DataPart without A2UI = field dict. State that `wire()` does not carry `metadata` for this type. Fix any code comment that claims parity with MCP.
- codify: Docs that say "the same value every surface carries" must be checked surface by surface; MarketBriefing has three different wire shapes.
- sdkCandidate: true

### RT-006
- severity: medium
- file: agent_sdk/models/content_types.py
- description: The module-docstring carve-out (lines 28-31) says the AG-UI `AGENT_ARTIFACT` frame for MarketBriefing sends `{"markdown", "metadata"?}`. The archived code in routes/ag_ui.py:387-390 sends `payload.model_dump(mode="json", by_alias=True, exclude_none=True)`, the full field dict, as do the CHANGELOG and `test_market_briefing_agui_artifact_frame_matches_schema_and_keeps_metadata`. The docstring describes a wire shape that does not exist.
- fix: Change the parenthetical: the AG-UI `AGENT_ARTIFACT` frame and the non-A2UI A2A DataPart both carry the field dict (`model_dump`, metadata included); the A2UI translator carries the bare markdown; the text fallback carries the `to_plain_text()` suffix.
- codify: A docstring that states a wire shape must be checked against the transport code that builds it, not against an earlier draft of the design.
- sdkCandidate: true

### RT-007
- severity: medium
- file: agent_sdk/routes/agent_card.py
- description: MarketBriefing has no single non-A2UI shape across transports: MCP structuredContent is `{"markdown"}` while the AG-UI AGENT_ARTIFACT and the A2A non-A2UI DataPart carry the field dict. Neither matches what the agent-card `_MARKET_BRIEFING_OUTPUT_SCHEMA_WIRE_NOTE` says (a bare markdown string). (One round saw an interim draft where AG-UI sent `{"markdown","metadata"?}`, which split AG-UI from A2A too; the archived code restored the field dict on AG-UI.)
- fix: Update `_MARKET_BRIEFING_OUTPUT_SCHEMA_WIRE_NOTE` so it describes the real per-transport shapes. Add a test that compares the AG-UI and A2A non-A2UI payloads for the same MarketBriefing so they cannot drift apart again. Decide in a future wave whether the non-A2UI shape should converge on `{"markdown", "metadata"?}` everywhere.
- sdkCandidate: true

### RT-008
- severity: medium
- file: agent_sdk/models/content_types.py
- description: The guard for the removed `_rejects_non_finite` flag (line 355) only checks `cls.__private_attributes__`. A subclass that declares the flag the old way, `_rejects_non_finite: ClassVar[bool] = True` — the exact form the SDK itself used — does not raise; a probe confirms it builds with no error. So the CHANGELOG claim that such a subclass "now fails at class definition with a TypeError" is false for this form, and the old opt-out is silently dropped: a nullable int field holding nan used to be rejected and is now turned into None.
- fix: Also check `"_rejects_non_finite" in cls.__class_vars__`, and check `vars(c)` for every class `c` in `cls.__mro__` up to `_Wire`. Raise the same TypeError in every case. Add a test next to `test_subclass_setting_rejects_non_finite_flag_fails_loud` that uses the `ClassVar[bool]` annotation (and a plain attribute and an inherited one).
- codify: When a removed opt-out flag gets a fail-loud guard, test every way the flag could have been declared (ClassVar, plain attribute, inherited), especially the form the SDK itself used.
- sdkCandidate: true

### RT-009
- severity: low
- file: agent_sdk/models/content_types.py
- description: Raised in three rounds. The `_assert_finite` docstring (lines ~258-279) still lists its scope as the GH-95 MarketBriefing validators "Plus ONE cross-cutting caller" (ContentModel._metadata_finite). G5 added ComparisonTable._rows_finite and CategoryValue._metadata_finite, so the stated scope is wrong.
- fix: Update the scope paragraph to name the GH-179 callers (ComparisonTable.rows, CategoryValue.metadata) and the rule for adding one: a free-form value that reaches both wire() and the text fallback.
- sdkCandidate: true

### RT-010
- severity: low
- file: agent_sdk/routes/a2a.py
- description: Raised in two rounds. `_strict_json_response` catches only ValueError and guards only the JSONResponse encode step. `Task.wire()` dumps in Python mode, so a value that cannot be JSON-encoded at all (for example a datetime a hook put into task or status metadata) raises TypeError inside JSONResponse and still gives a bare HTTP 500. A PydanticSerializationError from `record.task.wire()` / `bare_msg.wire()` is raised inside `_task_wire` before the helper and also returns 500. The docstring calls this "the one place a non-stream A2A body is serialized"; the check the todo said to match (runner.py:470-475) catches `(TypeError, ValueError)` around the wire build too.
- fix: Catch `(TypeError, ValueError)` as runner.py does, and move the `_task_wire(...)` / `.wire()` call inside the helper (pass a thunk) or wrap it in the same except. Add a test that uses a non-JSON object.
- sdkCandidate: true

### RT-011
- severity: low
- file: agent_sdk/routes/a2a.py
- description: Raised in two rounds. The -32006 fallback runs after side effects. In message:send (line 616) the task is already created and its worker started, so the client gets a 502 with no task id and cannot poll or cancel the task, which keeps running. In tasks/cancel (line 1058) the CANCELED state is already committed and published, but the client is told the call failed; a retry then gets -32002 TaskNotCancelable.
- fix: For cancel, check the body can be serialized before committing, or return a minimal Task (id, contextId, status only) on failure. For message:send, cancel the started worker or fail the task before returning -32006. At minimum, document the behaviour in the helper's docstring, in tasks_cancel, and in the CHANGELOG.
- sdkCandidate: true

### RT-012
- severity: low
- file: agent_sdk/a2ui/catalog.py
- description: Raised in three rounds. `_annotation_str` (lines 90-91) wraps every Literal value in double quotes using str(v). `Literal[1, 2]` or `Literal[True]` is shown to the model as the string type `"1|2"`, telling it to send strings where ints/bools are expected. A Literal value that itself contains `|` or `"` cannot be told apart from the separator. The new test only covers string literals.
- fix: Quote only str members (escape them, e.g. via json.dumps), and render other members with json.dumps(v) (`1|2`, `true`). Add a test with an int Literal.
- sdkCandidate: true

### RT-013
- severity: low
- file: agent_sdk/a2ui/catalog.py
- description: Compact-schema drift. (a) The TimeSeriesChart compact schema (line 211) adds a new type token `num` (`value:num|null`), but every other compact schema and the generated field summary use `float` (BarChart `value:float`, DocumentList `size?:float`), so the prompt uses two names for one type. (b) The EntityList compact schema (line 214) still teaches the SDK-extension keys `title?`/`showing?`; issue 179 item 1 asked to drop them from the schema, and GH-177 set the rule "compact schema teaches contract keys only" (DocumentList's `modified_by` is untaught).
- fix: Use `float|null` in the TimeSeriesChart compact schema. Remove `title?`/`showing?` from the EntityList compact schema.
- sdkCandidate: true

### RT-014
- severity: low
- file: agent_sdk/agent/runner.py
- description: `_validate_a2ui_wire` (runner.py:319) now rejects a domain MarketBriefing subclass whose `wire()` returns a dict. That used to be accepted, and the translator never uses `wire()` for MarketBriefing (it uses `to_markdown()`), so such a card now fails artifact build for a value that never reaches the wire. The CHANGELOG mentions only the new str acceptance, not the new dict rejection.
- fix: For MarketBriefing, validate `payload.to_markdown()` (what the translator emits) as a non-empty str instead of `wire()`, or note the dict rejection in the CHANGELOG Breaking bullet.
- sdkCandidate: true

### RT-015
- severity: low
- file: docs/content-types.md
- description: The new "## SDK extensions on Profile types (GH-179)" heading (line 115) is a level-2 heading placed inside "## Domain cards (extension API)". The existing "### The `metadata` envelope", "### Delimiter safety (GH-130)" and "### Why one helper..." subsections now sit under "SDK extensions on Profile types" in the outline and table of contents.
- fix: Move the SDK-extensions section after the Domain cards subsections (for example next to "## DocumentItem wire keys (GH-177)" at the end), or demote it to "###".
- sdkCandidate: true

### RT-016
- severity: low
- file: tests/test_gh179_conformance_drift.py
- description: `test_sdk_extension_docs_page_lists_every_key` reads the cwd-relative `Path("docs/content-types.md")` and only checks that words like `showing` appear anywhere in the page, which any other text satisfies.
- fix: Resolve the doc path from `Path(__file__).parents[1]` and assert on the SDK-extensions table rows themselves.
- sdkCandidate: true

### RT-017
- severity: low
- file: CHANGELOG.md
- description: The GH-179 (3) and (5) Breaking entries cite issue 179 comment 6187889614 as their ruling. That ruling covers only item 1 (keep the SDK extension keys), so the breaking changes in items 3 and 5 point to an approval that does not cover them.
- fix: Cite the issue body or the todo AC for items 3 and 5 instead of the item-1 ruling, or get an explicit user ruling for those breaking changes (recorded as a GitHub issue comment URL).
- sdkCandidate: true
