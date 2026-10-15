wave: w050
scope: phase
date: 2026-10-15

Non-blocking — these did not block w050's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every phase redteam round. Where several rounds raised the same
finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.
All findings are SDK-level (sdkCandidate: true).

## Findings

### RT-001
- severity: medium
- file: docs/content-types.md, agent_sdk/models/content_types.py, agent_sdk/agent_card.py
- description: Raised in seven rounds. The MarketBriefing wire shape is described several ways, and most are wrong. (a) docs/content-types.md:128 says `MarketBriefing.wire()` returns "the same value the A2UI, AG-UI and MCP surfaces already carry". In fact only the A2UI updateDataModel value is the bare markdown string; the AG-UI AGENT_ARTIFACT frame sends the field dict (routes/ag_ui.py:387-390, pinned by `test_market_briefing_agui_artifact_frame_matches_schema_and_keeps_metadata`), the non-A2UI A2A DataPart sends the field dict, and MCP structuredContent sends `{"markdown": ...}` (mcp.py:740-746). (b) The content_types.py module docstring (lines 28-31) says the AG-UI frame sends `{"markdown", "metadata"?}`, which is false. (c) docs/content-types.md:237 says "wire() always keeps the full value", which is false for MarketBriefing: its wire() is `to_markdown()`, which cuts the title at 1024 and as_of at 256 with '…'. (d) agent_card.py:37 `_MARKET_BRIEFING_OUTPUT_SCHEMA_WIRE_NOTE` says the A2A DataPart is a bare markdown string; it is the field dict without A2UI and a `{messages}` wrapper with A2UI.
- fix: Write one accurate per-surface table in docs/content-types.md: wire() = markdown str; A2UI updateDataModel value = markdown str; AG-UI AGENT_ARTIFACT data = field dict (metadata included); A2A non-A2UI DataPart = field dict; MCP structuredContent = `{markdown}`. Point the module docstring, docs line 128, docs line 237 (add the MarketBriefing exception) and the agent-card note at it.

### RT-002
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in six rounds. The GH-177 `DocumentItem._wire_contract_keys` (~line 1434) is a wrap `model_serializer`, so it runs on every `model_dump`, not only wire(). Verified: `DocumentItem.model_validate(doc.model_dump()).last_modified` is None, and web_url is lost too; when modified and last_modified differ, last_modified's value is lost for good. `model_dump(include={'web_url'})` returns `{'link','modified'}`, ignoring include, and `model_dump(exclude={'link'})` has link put back. Values passed through `pydantic_core.to_jsonable_python` lose the fields as well. The `dict[str, Any]` return type collapses `model_json_schema(mode='serialization')` to `{type: object, additionalProperties: true}`. The ruling says both fields stay on the model so tools can set and read them, and a downstream agent reads last_modified; the CHANGELOG says they "stay readable on the model" with no caveat.
- fix: Limit the alias fold to the wire path: do it in `DocumentItem.wire()`/`DocumentList.wire()`, or only when a serialization context flag set by wire() is present. Keep plain `model_dump()` lossless and honour include/exclude. Give the serializer a TypedDict return type so the serialization schema stays typed. Add a round-trip test (`model_validate(model_dump())` keeps last_modified and web_url) and record the scope in the CHANGELOG GH-177 entry.

### RT-003
- severity: medium
- file: agent_sdk/agent/registry.py
- description: Raised in four rounds. The GH-177 ruling says web_url and last_modified are "NOT emitted or taught". But `output_schema()` (line 721) returns `emits.model_json_schema()` in validation mode, so the MCP tools/list outputSchema and the agent card's `x-sdk.outputSchema` for DocumentList-emitting tools still list them. Verified properties: id, name, type, modified, link, size, web_url, last_modified, modified_by. Clients are taught two keys that never arrive.
- fix: Hide the two fields from the advertised schema (e.g. `Field(json_schema_extra=...)` or a DocumentItem json-schema hook that pops them), or derive output_schema from `mode='serialization'` once RT-002 gives the serializer a typed return. Add a test that the DocumentList tool outputSchema item keys equal the emitted key set (contract keys + modified_by).

### RT-004
- severity: low
- file: agent_sdk/models/content_types.py
- description: The DocumentItem serializer uses `not data.get('link')`, so an explicitly set empty contract key (link='' or modified='') is overwritten by web_url/last_modified. The docs say "A contract key that is set wins".
- fix: Test `self.link is None` / `self.modified is None` instead of truthiness, or document that an empty string counts as unset.

### RT-005
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: Raised in five rounds. `_strict_json_response` (~line 540) and `_list_entry` catch only ValueError. `dumps_strict` raises TypeError for a value that is not JSON-encodable at all, such as a datetime a hook put into task or status metadata. Verified: `record.task.metadata={'x': datetime(...)}` makes GET /v1/tasks/{id} raise TypeError, which escapes as a bare HTTP 500. The build_artifact gate (runner.py:471) and `mcp._is_writable` catch both. GH-179 (9)'s "fixed -32006, not HTTP 500" guarantee therefore covers only non-finite numbers.
- fix: Catch `(TypeError, ValueError)` in `_strict_json_response` and `_list_entry`, keeping the fixed-text -32006 and id-only logging. Add a datetime-metadata test.

### RT-006
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: Raised in four rounds. On the -32006 fallback, `_strict_json_response` passes the success-path headers into `a2a_error`. `_echo_a2ui_if_present` has already set the `X-A2A-Extensions` A2UI echo on message:send, tasks/get, tasks/list, tasks/cancel and the resume path, so a 502 error body claims A2UI was activated for a body that was never delivered. This breaks the RT-B-203 rule and `wire_errors.a2a_error`'s own docstring rule (echo only what was really activated for this response).
- fix: On the error branch, drop `X-A2A-Extensions` (keep any credential-forwarding echo only where the worker really bound it) before calling `a2a_error`. Assert in the RT-001 route tests that the header is absent on the 502.

### RT-007
- severity: low
- file: agent_sdk/routes/a2a.py
- description: Raised in four rounds. The `_strict_json_response` docstring (~lines 543-545) says "Starlette's ``dumps_strict`` refuses ...". `dumps_strict` is the SDK's own helper in agent_sdk/common/json_strict.py, and the function no longer uses Starlette's encoder. The log line "a2a response body not serializable" gives no route name, so a 502 cannot be traced to message:send, tasks/get, tasks/list or tasks/cancel.
- fix: Rewrite the docstring: it uses `agent_sdk.common.json_strict.dumps_strict`, which refuses non-finite values and non-UTF-8 strings. Add a fixed, non-user-derived route label (e.g. `route="tasks/get"`) to the log line. Never log the value.

### RT-008
- severity: low
- file: agent_sdk/routes/mcp.py, agent_sdk/agent/runner.py
- description: Raised in three rounds. The CHANGELOG claim that "the A2A, SSE and MCP writers now share this one serializer" is not fully true (LRN-364 class). The legacy /mcp/messages queue still writes its parse-error and invalid-request frames with plain `json.dumps` (mcp.py:1167, 1173: default separators, ensure_ascii=True), so one stream mixes two formats. runner.py:471 (build_artifact gate) still calls `json.dumps(..., allow_nan=False)` inline.
- fix: Route both legacy queue error frames and the build_artifact check through `dumps_strict`, or narrow the CHANGELOG wording.

### RT-009
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: `_list_entry` (line 563) dumps with `model_dump(mode='json')`, and pydantic's JSON mode turns nan/inf into null, so its "left out and logged" branch for a non-finite value cannot be reached. Verified: a record with `task.metadata={'x': inf}` gives GET /v1/tasks/{id} 502 -32006, but GET /v1/tasks returns the same task with `"x": null`. The CHANGELOG GH-179 (9) claim that tasks/list "leaves that one task out of the page" is false. `test_tasks_list_leaves_out_a_non_finite_task_never_500` passes only because it monkeypatches `Task.model_dump` to inject NaN after the dump.
- fix: Serialize list entries the same way tasks/get does (`t.wire()` / python mode, then `dumps_strict`), so one rule decides both routes, or document the null coercion and make tasks/get match. Replace the monkeypatched test with a real `record.task.metadata = {'x': float('inf')}` record and assert list and get agree.

### RT-010
- severity: low
- file: agent_sdk/routes/a2a.py
- description: When `_list_entry` leaves out a record that cannot be written, tasks_list (~line 950) still reports totalSize and pageSize counting it, and `_echo_a2ui_if_present` runs over the full task list, dropped task included. The client sees a short page with no way to tell, and may get an A2UI echo only the dropped task triggered.
- fix: Build the entries first, then compute the A2UI echo from the kept tasks. Lower totalSize by the number left out, or add a documented field (e.g. omittedCount).

### RT-011
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: Raised in two rounds. The w050 RT-001 legacy-record fallback is uneven. Non-stream reads (`_strict_json_response`, `_list_entry`) replace lone surrogates with U+FFFD and serve the task. The message:stream / tasks:subscribe snapshot in the resubscribe `gen()` (~line 831) still calls `sse_data(snapshot)` directly and, on ValueError, emits `_unserializable_tail()`: a FAILED final status-update. So a COMPLETED task stored before the fix (or by a durable store) reads COMPLETED from GET /v1/tasks/{id} but FAILED (-32006) from POST /v1/tasks/{id}:subscribe.
- fix: In `gen()`, on ValueError retry `sse_data(scrub_unencodable(snapshot))` and scrub `item.frame` too. Fall back to the FAILED tail only when the scrubbed value still cannot be written (a non-finite value). Add a test with a record holding a surrogate.

### RT-012
- severity: medium
- file: agent_sdk/routes/ag_ui.py
- description: The w050 lone-surrogate rule gives different results on A2A and AG-UI for the same model text. `runner._agent_message`/`set_task_status` swap the bad character for U+FFFD, so the A2A task completes. AG-UI's `_RunMapper.map` sends the raw `event.text` as the TEXT_MESSAGE_CONTENT delta (line 304), `_emit` refuses it, and the run ends with RUN_ERROR. Verified with `fake_model.script(reply('hello ' + LONE))` on /ag-ui/run: frames RUN_STARTED, STATE_SNAPSHOT, STEP_STARTED, TEXT_MESSAGE_START, STEP_FINISHED, RUN_ERROR, while GET /v1/tasks shows the task `completed`. ProgressEvent, NoteEvent and ToolProgressEvent text behave the same. The CHANGELOG ("the task keeps running and the stream carries the replaced text") is true only on A2A.
- fix: Apply `scrub_unencodable` once at the event source (where loop.py builds TextEvent/ProgressEvent/NoteEvent/ToolProgressEvent), or in `_RunMapper.map` for text-bearing frames. Add an AG-UI test asserting RUN_FINISHED and a U+FFFD delta.

### RT-013
- severity: low
- file: agent_sdk/common/json_strict.py
- description: `loads_strict` now calls `dumps_strict` on every decoded inbound body just to find lone surrogates. That re-serializes every A2A, AG-UI, MCP and OAuth request in full, doubling JSON work on large AG-UI histories.
- fix: Find surrogates during the parse instead (an object_pairs_hook, or a scan of the raw text for `\ud[89a-f]` escapes and raw surrogate bytes), with no second full serialization.

### RT-014
- severity: medium
- file: CHANGELOG.md
- description: The RT-001 Fixed entry says the 0.13.0 legacy MCP SSE stream "died with UnicodeEncodeError" on a lone surrogate. That is wrong. 0.13.0 wrote the legacy queue with `json.dumps(..., allow_nan=False)` (ensure_ascii=True), so the surrogate went out as an ASCII `\ud800` escape and the result was delivered. The crash only appeared mid-wave, after the queue moved to `dumps_strict` (ensure_ascii=False). The real user-facing change for legacy MCP is that tool results 0.13.0 delivered now come back as isError "tool output not serializable", and the entry does not say so.
- fix: Rewrite the entry. Streamable HTTP: HTTP 500 becomes isError/-32603. Legacy HTTP+SSE: an escaped `\ud800` in the result becomes isError; call this out as a behaviour change. Fix the same claim in the tests/test_rt001_lone_surrogate_writers.py docstring.

### RT-015
- severity: medium
- file: agent_sdk/routes/admin.py
- description: A caller the CHANGELOG does not cover. `admin.py::_safe_result` (line 544) returns `{"value": result.wire()}`, so after GH-179 (5) the admin try-tool endpoint (/admin/api/tools/{name}/try) returns a bare markdown string for MarketBriefing instead of the field dict, and the card's metadata disappears. The CHANGELOG lists the translator, MCP, AG-UI and runner callers but not this one, and no test covers it.
- fix: Choose the admin shape explicitly: keep the field dict via model_dump for MarketBriefing (as ag_ui.py does), or accept the string and add it to the GH-179 (5) Breaking bullet. Add a try-tool test on a MarketBriefing-emitting tool.

### RT-016
- severity: medium
- file: agent_sdk/models/content_types.py
- description: The guard for the removed `_rejects_non_finite` hook (line 357) only looks in `cls.__private_attributes__`. That misses the exact form the old hook used, `_rejects_non_finite: ClassVar[bool] = True`, because pydantic keeps ClassVars out of `__private_attributes__`. Verified: such a subclass defines with no error and silently switches from rejecting to coercing, contradicting the CHANGELOG Breaking claim that it "now fails at class definition with a TypeError". The test only covers the unannotated form.
- fix: Check `'_rejects_non_finite' in vars(cls) or '_rejects_non_finite' in cls.__private_attributes__ or '_rejects_non_finite' in getattr(cls, '__class_vars__', ())`. Add test cases for the ClassVar, annotated and plain forms.

### RT-017
- severity: low
- file: CHANGELOG.md
- description: The GH-178 entry (line 25) files the `_rejects_non_finite` removal as "Changed" with "no effect, no error". For a downstream class that set it to True, nullable float fields used to reject nan/inf and now silently become None. That is a behaviour change with no Migration line. (A read-only grep of the agents/ folder found no current user.) Interacts with RT-016: once the guard catches every form, the entry must match.
- fix: Move the entry under Breaking with a Migration line: add a field_validator that rejects non-finite values if strict rejection is needed.

### RT-018
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in seven rounds. The GH-175 ruling (issue 175 comment 6187888514) says both caps are "documented in docs/content-types.md and on the title fields". Only the docs page has them. No title field (KpiCard.title ~696/705, TimeSeriesChart ~761/770, ComparisonTable ~821/830, BarChart ~858/867, EntityList ~885/894, MarketBriefing ~969/978, WaterfallChart ~1025/1034, MultiCategoryChart ~1078/1087) has a docstring, Field description or comment naming TITLE_TEXT_MAX_LEN, the 1024 cap or the '…' cut (LRN-346 class).
- fix: Document the cap on each title field: the text fallback caps it at TITLE_TEXT_MAX_LEN (1024) with a trailing '…', and wire() keeps the full value (note the MarketBriefing exception, RT-001). One round warns that `Field(description=...)` changes the MCP outputSchema; use a class docstring line or attribute comment unless that change is intended. Add a test that checks for the mention, or record a maintainer-approved narrowing URL.

### RT-019
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in three rounds. The GH-175 ruling gives the 1024 cap to "titles (card titles and other title/header slots)", but several slots were missed. The MarketBriefing `KPI {title}:` line (~line 982), its `CHART (...): {title}` / `TABLE: {title}` section headers (~990-997) and the EntityList default title (`_sanitize_cell(f"{self.entity_type} list")`) go through `_sanitize_cell`/`safe_cell_text` with no cap and no '…', so a huge title is rendered in full. The MarketBriefing `as of:` header (the GH-167 standalone header slot) still uses `_sanitize_line(self.as_of)` at the 256 cap (~line 976). No maintainer clarification narrowing "header slots" is recorded.
- fix: Put the KPI and section title headers through a capped path (safe_cell_text plus the same tail cut at TITLE_TEXT_MAX_LEN, or a max_len on `_sanitize_cell`). Either pass `max_len=TITLE_TEXT_MAX_LEN` for the as-of header, or record a maintainer comment URL narrowing "header slots", and say in the CHANGELOG and docs which slots count.

### RT-020
- severity: low
- file: tests/test_gh175_title_cap_marker.py
- description: Raised in four rounds. The 1024 title cap is tested only on KpiCard. The seven other cards switched to TITLE_TEXT_MAX_LEN (ComparisonTable, BarChart, EntityList, TimeSeriesChart, MarketBriefing, WaterfallChart, MultiCategoryChart) could fall back to 256 with no test failing (LRN-327).
- fix: Parametrize the 1100-char title test over every card whose title uses TITLE_TEXT_MAX_LEN, and over the header slots fixed by RT-019.

### RT-021
- severity: medium
- file: tests/test_gh174_label_ascii.py
- description: Raised in six rounds. `test_metric_label_line_break_cannot_forge_row` (lines 36-40) proves non-forgery with a line-prefix match (`line.startswith('  forged')`), which LRN-339 and the todo's SI-2 note forbid ("search for the hostile value; do not match a line prefix"). A regression that shifted indentation, or kept 'forged: 9' joined on the row, would pass, and so would code that never swapped ':' (the line-break collapse alone keeps the text off column 2). `test_header_pipe_cannot_forge_column` only counts '|' on a line. No test puts a hostile 'id:'-style or 'k=v' value in a ComparisonTable header label, which keeps ':' and '='.
- fix: Assert the hostile substring 'forged: 9' (ASCII colon) appears nowhere in `to_plain_text()`, that the label renders with the look-alike colon, and that there is exactly one ': ' row separator per metric. Add a header-label case with 'x: 1 | y' (header row keeps one ' | ' per real column) and a hostile 'id: 99999' label case.

### RT-022
- severity: medium
- file: agent_sdk/common/redact.py
- description: Raised in two rounds. `safe_label_text(neutralise=':')` swaps every ':' (`swap[ord(':')] = _SPACED_SEPARATORS[':']`), including digit-flanked colons that `safe_cell_text` deliberately exempts (`_SPACED_SEPARATOR_DIGIT_RE`, GH-130). Verified: MetricItem labels 'Close 16:00', 'Ratio 1:2', 'Open 09:30' now render 'Close 16：00' / 'Ratio 1：2' / 'Open 09：30'; under 0.13.0 they rendered in ASCII. A digit-flanked colon cannot forge the ': ' row separator. This regression goes against the GH-174 intent (labels keep ASCII as written) and is not in the CHANGELOG. (Same issue as group G1 deferred RT-004.)
- fix: For ':', reuse the digit-flank exemption instead of a blanket translate. Add a test that 'Close 16:00' survives and 'a: 1' is still neutralised.

### RT-023
- severity: medium
- file: agent_sdk/common/redact.py
- description: Raised in two rounds. Public `safe_label_text(value, *, neutralise)` (line 216) handles only '|' and ':'; any other character is silently ignored (`safe_label_text('a,b=c', neutralise=',=')` returns 'a,b=c'). docs/content-types.md says it "swaps only the characters you name", and the CHANGELOG offers it to domain cards. A domain author who passes '=' for a `k=v` row or ',' for a list gets no protection, so a label can forge that row's grammar (fail-open, SI-2 adjacent). (Same issue as group G1 deferred RT-003; re-verify whether the final code raises KeyError or passes silently.)
- fix: Raise ValueError for any unsupported `neutralise` character (or type it as `Literal['|', ':', '|:', '']`), or support every character in `_BARE_SEPARATORS`/`_SPACED_SEPARATORS` by reusing those maps. Add a test for an unsupported character.

### RT-024
- severity: low
- file: agent_sdk/common/redact.py
- description: `safe_label_text(neutralise='|')` also swaps '│' (U+2502) and '｜' (U+FF5C), not just '|' (lines 147-152). The GH-174 ruling says only '|' in a header row, and docs/content-types.md's "swaps only the characters you name" is inaccurate (LRN-348 pattern; no title slot affected).
- fix: Document that '|' covers its two look-alikes in the docstring and docs/content-types.md and record maintainer acceptance on issue 174, or swap only ASCII '|'.

### RT-025
- severity: medium
- file: workspace/components/README.md
- description: Raised in seven rounds. Registry drift (Dimension 8). (1) The C-038 entry (line ~207) still says "Classes with `_rejects_non_finite = True` opt out of the coercion", but GH-178 removed the hook; the todo's Reuses C-038 note required the update. C-038 also still says `_assert_finite` covers only metadata and free-form dicts. (2) The `_assert_finite` docstring Scope (content_types.py:268-276, "Plus ONE cross-cutting caller") omits the new callers `ComparisonTable._rows_finite` (rows) and `CategoryValue._metadata_finite`.
- fix: In C-038, drop the opt-out sentence, note it was removed in GH-178 and that a subclass declaring it fails at class definition, and list the new `_assert_finite` callers. Update the `_assert_finite` docstring Scope list to match.

### RT-026
- severity: medium
- file: workspace/components/README.md
- description: Raised in seven rounds. This wave added reusable public helpers and registered none of them: `agent_sdk.common.json_strict.dumps_strict` (with its pair `loads_strict`; the one outbound strict serializer now shared by routes/a2a.py `_strict_json_response`, common/sse.py `sse_data`, routes/mcp.py `_is_writable` and the legacy queue, per LRN-364), `scrub_unencodable` (the store-side surrogate rule), and `agent_sdk.common.redact.safe_label_text` (the GH-174 label renderer, a third sibling to safe_cell_text and safe_line_text). C-034 does not name its safe_label_text sibling. The C-034 ↔ C-036 cross-reference (tail '…' cut vs counted middle-cut marker are deliberately separate) asked for by the Reuses notes was not added (LRN-133). The BASIC_CATALOG_COMPONENTS placement note was filed under C-020, but the todo cited C-021 (profile.py). Later waves will not find these and may add a fourth inline `json.dumps(..., allow_nan=False)` or a second label sanitizer.
- fix: Register `dumps_strict`/`loads_strict` + `scrub_unencodable` as one strict-JSON component (C-007 sibling or new C-NNN) with its contract (fixed-text ValueError, U+FFFD replacement) and the rule that every outbound JSON writer and the build_artifact gate must use it. Add safe_label_text to C-034 (or its own C-NNN) with the supported `neutralise` set, 256 cap with '…', and when to use it. Add the C-034 ↔ C-036 cross-reference to both entries. Move or copy the BASIC_CATALOG_COMPONENTS note to C-021.

### RT-027
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in five rounds. GH-176 ignores its Reuses C-021 directive ("Extend the existing GH-172 casefold loop over RESERVED_COMPONENTS + BASIC_CATALOG_COMPONENTS. Do not add a second loop."). `register_content_type` now has a separate `for primitive in BASIC_CATALOG_COMPONENTS` loop (~line 1550-1556), and the new `_case_clash_hint` (~line 1486-1495) runs a third scan over the same three lists, so the reserved-name rule lives in three places that can drift (LRN-344). BASIC_CATALOG_COMPONENTS is defined in content_types.py (~line 164), not next to the A2UI catalog data, and the 18 names stay duplicated in .claude/agents/a2ui-advisor.md and harness/agents/a2ui-advisor.md.
- fix: Build one ordered list of (kind, name) from RESERVED_COMPONENTS, BASIC_CATALOG_COMPONENTS and the registered names, and one shared `_casefold_clash(cls, component)` helper returning (kind, name) or None, used by both the raise path and the PascalCase hint. Move the tuple to agent_sdk/a2ui/catalog.py (or profile.py if no import cycle) and re-export it from content_types; record its home in the registry entry.

### RT-028
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in five rounds. The GH-176 ruling (issue 176 comment 6187889280) and the CHANGELOG Breaking entry say "The error names the card and the clash". The Basic Catalog primitive refusal (~line 1547-1556), the RESERVED casefold refusals and the PascalCase refusal print the component string and the clashing name but never the registering class. Verified: a class `MyCard` with component='Card' gives "component name 'Card' equals the Basic Catalog primitive 'Card' ignoring case..." with no `MyCard`. Only the registered-name clash includes `owner.__name__`. With several domain cards loaded at boot, the operator cannot tell which class failed.
- fix: Prefix every `register_content_type` ValueError with the class (`cls.__qualname__`, optionally `cls.__module__`), e.g. f"{cls.__name__}: component name {component!r} ...". Assert the class name in tests/test_gh176_basic_catalog_names.py.

### RT-029
- severity: medium
- file: agent_sdk/a2ui/catalog.py
- description: Raised in two rounds. GH-179 AC (7) is only partly met. `_annotation_str` has no `typing.Annotated` branch, so a list of a discriminated union renders as `[Annotated]` with every arm lost (MarketBriefing shows `sections?: [Annotated]` today), and nested `Annotated[int, Field(ge=0)]` renders as `Annotated`. Any domain card with `list[Annotated[...]]` teaches the model nothing.
- fix: When `typing.get_origin(ann) is Annotated`, recurse on `get_args(ann)[0]` before the other checks. Add a test that MarketBriefing's summary lists the KpiRowSection|ChartSection|TableSection|TextSection arms, plus a nested Annotated case.

### RT-030
- severity: low
- file: agent_sdk/a2ui/catalog.py
- description: Raised in three rounds. The Literal branch of `_annotation_str` (~lines 90-91) renders `'"' + '|'.join(str(v)) + '"'`: `Literal[1, True]` / `Literal[1, 2]` are taught as quoted strings ('"1|True"'), the wrong JSON types, and a value containing '"' or '|' breaks the format. Separately, the TimeSeriesChart compact schema adds a new type token 'num' (`value:num|null`), while every other schema and the generated summary use 'float'.
- fix: Render non-str Literal values unquoted (json.dumps per value, e.g. 1|2, true), quote each str value on its own, and escape '|'. Use 'float' in the TimeSeriesChart schema. Add test cases.

### RT-031
- severity: medium
- file: agent_sdk/console/static/a2ui.js
- description: Raised in three rounds. The GH-177 AC and the CHANGELOG Breaking entry say the console renderer "reads modified/link". `renderDocumentList` (a2ui.js:867-885) only switched its date preference to modified (falling back to last_modified); it never reads `d.link` or `d.web_url`, so a document link is never shown. The CHANGELOG overstates the change.
- fix: Render `d.link || d.web_url` as an anchor only for http/https schemes (per the todo's console-href SI note), built with `el()` text nodes, never innerHTML. Or reword the CHANGELOG and AC to "reads modified (falls back to last_modified); link is not rendered".

### RT-032
- severity: medium
- file: DESIGN.md, harness/skills/add-tool/SKILL.md, template/.claude/skills/add-tool/SKILL.md
- description: Raised in two rounds. Author-facing docs outside docs/content-types.md were not updated. DESIGN.md:231 still says `register_content_type` "refuses the four RESERVED names", with no mention of the 18 Basic Catalog primitives (GH-176 breaking boot check). DESIGN.md:214 still describes `safe_line_text` as a plain "256-char cap" with no '…' and no 1024 title cap (GH-175), has no `safe_label_text` rule for labels (GH-174), and lists the old DocumentList text layout (type/modified/id) without the new `last modified:`/`modified by:` lines (GH-177). harness/skills/add-tool/SKILL.md:92-94 and its template mirror tell authors only to avoid Standard Profile names, so a domain card named `Card`/`List`/`Text` now fails at boot with no warning in the skill.
- fix: Update DESIGN.md §4.0/§4.3 for GH-174/175/176/177. Add the Basic Catalog primitive rule to harness/skills/add-tool/SKILL.md, mirror it to template/.claude/skills/add-tool/SKILL.md, and commit and push the template per LRN-335.

### RT-033
- severity: low
- file: agent_sdk/models/content_types.py
- description: Raised in two rounds. `DocumentList._body_text` (~lines 1479-1483) has two text-format changes not in the CHANGELOG: a new '    modified by: ...' line that 0.13.0 never printed (the AC wording "as today" was wrong), and date precedence flipped from last_modified-first to modified-first.
- fix: Add a CHANGELOG [Unreleased] Changed line for the DocumentList text-format change (new 'modified by:' line; modified wins over last_modified).

### RT-034
- severity: low
- file: docs/content-types.md
- description: The new '## SDK extensions on Profile types (GH-179)' heading (line 115) sits inside the '## Domain cards (extension API)' section and demotes the following '### The `metadata` envelope' and '### Delimiter safety (GH-130)' subsections under it, breaking the page outline.
- fix: Move the SDK-extensions section after the Domain cards subsections (next to the GH-177 section at the end), or make it a ### subsection.

### RT-035
- severity: medium
- file: workspace/todos/active/w050-gh-issues.md
- description: LRN-338/359 check fails. tests/test_gh171_fallback_schema_required.py was modified but is on no Creates/Modifies line; uv.lock shows as modified; workspace/components/README.md is listed only under Reads for GH-175 although its AC edits it. tests/test_rt003_super_to_plain_text_no_recursion.py is listed in GH-174 scope but has no diff (LRN-350/361).
- fix: Add tests/test_gh171_fallback_schema_required.py and workspace/components/README.md to the relevant Creates/Modifies lines, add uv.lock to the release todo, and either drop test_rt003 from scope or record why no change was needed.

### RT-036
- severity: low
- file: uv.lock
- description: The committed uv.lock still names agent-sdk 0.11.0 while pyproject.toml is 0.13.0, so two releases shipped with a stale lockfile. Running the test suite in review (uv run) resynced it to 0.13.0, leaving a one-line uv.lock diff no todo made.
- fix: Have the release step run `uv lock` after the version bump and commit uv.lock with the release; include this diff in the w050 release commit.
