wave: w050
scope: phase
date: 2026-10-15
round_count: 8
status: budget-exhausted

Fix remaining findings, then re-run /wave w050

The phase redteam loop used all 8 rounds and these findings were still open. They block w050's archive.

## Findings

### RT-001
- severity: high
- file: agent_sdk/models/content_types.py
- description: [SDK] GH-177's `DocumentItem._wire_contract_keys` (line 1434) is a model-wide `@model_serializer(mode='wrap')`. It removes `web_url`/`last_modified` from every `model_dump()`, not only from the wire. `agent/loop.py::fold_result_content` (line 286) folds tool results into the LLM transcript with `model_dump(mode='json', by_alias=True, exclude_none=True)`. So the agent's own model no longer sees `last_modified` when `modified` is set. Verified: `fold_result_content(DocumentList(documents=[DocumentItem(id='1', name='n', modified='2025-12-31', last_modified='2026-02-03T10:00Z')]))` returns only `modified`. The a2a-ilevel agent, which the ruling names, sets modified=periodEnd and last_modified=uploadDate (src/tools/documents.py:143-149), so its model can no longer answer 'when was it uploaded'. The ruling (issue 177 comment 6187888894) limited the drop to 'the wire and the compact schema' and said to keep the fields because ilevel reads `last_modified`. Other effects: `DocumentItem.model_validate(doc.model_dump())` loses the value, and `model_json_schema(mode='serialization')` collapses to `{type: object, additionalProperties: true}`.
- fix: Apply the remap only on wire paths. Gate the serializer on a serialization context, e.g. `if not (info.context or {}).get('wire'): return data` using `SerializationInfo`. Pass `context={'wire': True}` from `_Wire.wire()` and from `build_artifact`'s non-A2UI DataPart `model_dump`. Leave `model_dump()` (the LLM fold, round trips) with all fields. Add a test that `fold_result_content` keeps `last_modified` while `wire()` and the A2A DataPart do not.
- codify: A wire-only key remap must not be a model-wide @model_serializer, because model_dump also feeds the LLM tool-result fold and round trips. Gate it on a wire serialization context.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/routes/ag_ui.py
- description: [SDK] The w050 lone-surrogate rule gives different results on A2A and AG-UI for the same model text. `runner._agent_message`/`set_task_status` swap the bad character for U+FFFD, so the A2A task completes. AG-UI's `_RunMapper.map` sends the raw `event.text` as the TEXT_MESSAGE_CONTENT delta (line 304), `_emit` refuses it, and the run ends with RUN_ERROR. Verified with `fake_model.script(reply('hello ' + LONE))` on /ag-ui/run: the frames are RUN_STARTED, STATE_SNAPSHOT, STEP_STARTED, TEXT_MESSAGE_START, STEP_FINISHED, RUN_ERROR, while GET /v1/tasks shows that task as `completed`. ProgressEvent, NoteEvent and ToolProgressEvent text behave the same way. The CHANGELOG says this covers model text, 'the task keeps running and the stream carries the replaced text'. That is true only on A2A.
- fix: Apply `scrub_unencodable` once at the event source (where loop.py builds TextEvent/ProgressEvent/NoteEvent/ToolProgressEvent), or in `_RunMapper.map` for the text-bearing frames, so both transports carry U+FFFD. Add an AG-UI test asserting RUN_FINISHED and a U+FFFD delta.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: [SDK] `_list_entry` (line 563) dumps with `model_dump(mode='json')`, and pydantic's JSON mode turns nan/inf into null. So the 'left out and logged' branch for a non-finite value cannot be reached. Verified: a record with `task.metadata={'x': inf}` gives GET /v1/tasks/{id} 502 -32006, but GET /v1/tasks returns the same task with `"x": null`. The CHANGELOG GH-179 (9) claim that tasks/list 'leaves that one task out of the page' is false. `test_tasks_list_leaves_out_a_non_finite_task_never_500` only passes because it monkeypatches `Task.model_dump` to inject NaN after the dump. The real behaviour is untested and differs from tasks/get.
- fix: Serialize list entries the same way tasks/get does (`t.wire()` / python mode, then `dumps_strict`), so one rule decides both routes. Or document the null coercion and make tasks/get match. Replace the monkeypatched test with a real `record.task.metadata = {'x': float('inf')}` record, and assert list and get agree.
- sdkCandidate: true

### RT-004
- severity: medium
- file: agent_sdk/common/redact.py
- description: [SDK] The public `safe_label_text(value, *, neutralise)` (line 216) handles only '|' and ':'. Any other character in `neutralise` is silently ignored: `safe_label_text('a,b=c', neutralise=',=')` returns 'a,b=c' unchanged. docs/content-types.md says it 'swaps only the characters you name', and the CHANGELOG offers it as stable to domain cards. A domain author who passes '=' for a `k=v` row or ',' for a list gets no protection, and a label can then forge that row's grammar (fail-open, SI-2 adjacent).
- fix: Raise ValueError for any `neutralise` character outside the supported set. Or support every character in `_BARE_SEPARATORS`/`_SPACED_SEPARATORS` by reusing those maps. Add a test for an unsupported character.
- sdkCandidate: true

### RT-005
- severity: medium
- file: agent_sdk/models/content_types.py
- description: [SDK] The GH-176 ruling (issue 176 comment 6187889280) says 'The error names the card and the clash', and the CHANGELOG Breaking entry repeats it. The primitive refusal (line 1556), the RESERVED case-fold refusal and the PascalCase refusal print only the component string and the clashing name, never the registering class. Verified: a class `MyCard` with component='Card' gives "component name 'Card' equals the Basic Catalog primitive 'Card' ignoring case..." and no `MyCard`. With several domain cards loaded at boot, the operator cannot tell which class failed.
- fix: Add `cls.__qualname__` (and `cls.__module__`) to every `register_content_type` ValueError. Assert the class name in tests/test_gh176_basic_catalog_names.py.
- sdkCandidate: true

### RT-006
- severity: medium
- file: docs/content-types.md
- description: [SDK] The MarketBriefing transport docs written in this wave contradict the code. (a) docs/content-types.md:128 says `MarketBriefing.wire()` returns 'the same value the A2UI, AG-UI and MCP surfaces already carry'. In fact AG-UI AGENT_ARTIFACT sends the field dict (`ag_ui.py` MarketBriefing branch) and MCP sends `{"markdown": ...}`. (b) The content_types.py module docstring (lines 28-31) says the AG-UI frame sends `{"markdown", "metadata"?}`, which is wrong. (c) docs/content-types.md:237 says 'wire() always keeps the full value', but `MarketBriefing.wire()` now returns `to_markdown()`, which cuts the title at 1024 and as_of at 256 with '…'.
- fix: Rewrite all three to match the code. A2UI updateDataModel = markdown string; AG-UI AGENT_ARTIFACT and the non-A2UI A2A DataPart = field dict; MCP structuredContent = {markdown}. State that MarketBriefing.wire() is cut at the GH-175 caps.
- sdkCandidate: true

### RT-007
- severity: medium
- file: agent_sdk/common/redact.py
- description: [SDK] The GH-175 ruling (issue 175 comment 6187888514) is only partly done. (a) It requires the caps to be 'documented ... on the title fields'. None of the 8 title fields switched to `TITLE_TEXT_MAX_LEN` (KpiCard.title line 696, TimeSeriesChart 761, ComparisonTable 821, BarChart 858, EntityList 885, MarketBriefing 969, WaterfallChart 1025, MultiCategoryChart 1078) mentions the cap. (b) It covers 'other title/header slots', but MarketBriefing's `KPI {title}:` line and its `CHART (...): {title}` / `TABLE: {title}` section headers (content_types.py ~979-994) still go through `_sanitize_cell` with no cap and no '…'. (c) Only KpiCard has a 1024-cap test; the other 7 title sites could fall back to 256 unnoticed.
- fix: Add `Field(description=...)` or a docstring naming TITLE_TEXT_MAX_LEN to each title field. Put the section and KPI title headers through a capped path (e.g. `safe_cell_text` plus the same tail cut at TITLE_TEXT_MAX_LEN). Parametrise the 1100-char title test over every card that uses the title cap.
- sdkCandidate: true

### RT-008
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: [SDK] On the -32006 fallback, `_strict_json_response` (line 540) passes the success-path headers into `a2a_error`. `_echo_a2ui_if_present` has already set `X-A2A-Extensions` (the A2UI echo) on message:send, tasks/get, tasks/list and tasks/cancel, so a 502 error body still claims A2UI was activated for a body that was never sent. This breaks the RT-B-203 rule: echo only when the delivered task carries an A2UI part.
- fix: On the error branch, drop the `X-A2A-Extensions` header (or pass only non-extension headers) before calling `a2a_error`. Add a test that the -32006 answer carries no A2UI echo.
- sdkCandidate: true

### RT-009
- severity: medium
- file: workspace/components/README.md
- description: [SDK] This wave added three reusable public helpers and registered none of them: `agent_sdk.common.json_strict.dumps_strict` (the one outbound strict serializer now shared by A2A, SSE and MCP, LRN-364), `scrub_unencodable` (the store-side surrogate rule), and `agent_sdk.common.redact.safe_label_text` (the GH-174 label renderer offered to domain cards). A grep of the registry finds no entry for any of them, so later waves will not find them and may write second copies (Dimension 8).
- fix: Add C-NNN entries (or extensions of C-007/C-034) for dumps_strict + scrub_unencodable (paired with loads_strict) and safe_label_text, with their contracts (fixed-text ValueError, U+FFFD replacement, supported `neutralise` set, 256 cap with '…').
- sdkCandidate: true

### RT-010
- severity: medium
- file: DESIGN.md
- description: [SDK] Author-facing docs outside docs/content-types.md were not updated for this wave's rule changes. DESIGN.md:231 still says `register_content_type` 'refuses the four RESERVED names', with no mention of the 18 Basic Catalog primitives (GH-176 breaking boot check). DESIGN.md:214 still describes `safe_line_text` as a plain '256-char cap' with no '…' or 1024 title cap (GH-175), has no `safe_label_text` rule for labels (GH-174), and lists the DocumentList text layout without the new `last modified:`/`modified by:` lines (GH-177). harness/skills/add-tool/SKILL.md:92-94 and its template mirror tell downstream authors only to avoid Standard Profile names, so a domain card named `Card`/`List`/`Text` will now fail at boot with no warning in the skill.
- fix: Update DESIGN.md §4.0/§4.3 for GH-174/175/176/177. Add the Basic Catalog primitive rule to harness/skills/add-tool/SKILL.md, mirror it to template/.claude/skills/add-tool/SKILL.md, and commit and push the template per LRN-335.
- sdkCandidate: true

### RT-011
- severity: low
- file: agent_sdk/routes/a2a.py
- description: [SDK] The U+FFFD read fallback reaches only the non-stream routes. The stream snapshot in the message:stream / tasks:subscribe generator (`yield sse_data(snapshot)`, ~line 833) has no scrub. A record holding a lone surrogate (stored before this fix, or by a durable store) is served 200 with U+FFFD by GET /v1/tasks/{id}, while subscribing to the same task gives a synthetic `failed` final status-update from `_unserializable_tail`, so the client is told a completed task failed.
- fix: Before falling back to `_unserializable_tail`, retry the snapshot and frames through `scrub_unencodable`, matching `_strict_json_response`.
- sdkCandidate: true

### RT-012
- severity: low
- file: agent_sdk/routes/a2a.py
- description: [SDK] `_strict_json_response` catches only ValueError. A value that is not JSON-encodable at all, such as a datetime a hook put into task or status metadata, makes `dumps_strict` raise TypeError, which escapes as HTTP 500. Verified: `record.task.metadata={'x': datetime(...)}` makes GET /v1/tasks/{id} raise TypeError. GH-179 (9)'s 'fixed -32006, not HTTP 500' guarantee therefore covers only non-finite numbers.
- fix: Catch `(TypeError, ValueError)` in `_strict_json_response` (and in `_list_entry`), keeping the fixed-text -32006 and id-only logging. Add a datetime-metadata test.
- sdkCandidate: true
