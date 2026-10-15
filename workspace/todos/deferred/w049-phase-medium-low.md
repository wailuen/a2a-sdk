wave: w049
scope: phase
date: 2026-10-15

Non-blocking — these did not block w049's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every phase redteam round. Many rounds raised the same finding with
different wording and different round-local IDs. Those entries are merged into one here, the strongest
severity is kept, and the extra detail from each round is folded in. The IDs below are renumbered for this
note; they do not match any single round's IDs. Every entry is an SDK candidate (sdkCandidate: true).

## Findings

### RT-001
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Container float fields are planned but never checked (raised in 5 rounds). `_float_field_plan` (~line 288-306) flattens the whole annotation with get_args, so `list[float]`, `dict[str, float]`, `tuple[float, ...]` and `list[float] | None` fields count as covered, but `_Wire._finite_floats` (~line 342) checks only `isinstance(value, float)` and skips them. Verified: a domain card with `values: list[float]` given `[nan, 1.0]` gives `wire()` -> `{'values': [nan, 1.0]}` (invalid JSON), `model_dump_json()` -> null, `to_plain_text()` -> '[nan, 1.0]' — the three-way mismatch GH-173 was meant to remove. Nullability is also taken from anywhere in the tree, not just the top-level union: `mix: float | list[float | None]` turns a bare nan into None, which then fails with a misleading 'Input should be a valid number'. The CHANGELOG ('any domain card's `float` field') and docs/content-types.md ('Your own `_Wire` models get the same rule for free') overclaim. The test helper `_float_fields` / `_flatten` in tests/test_gh173_non_finite_values.py copies the same algorithm, so it shares every blind spot, and its walk injects a scalar nan into list fields, so the ValidationError comes from the list type, not the guard (false pass). Built-in models have no float containers, so the built-in AC still holds.
- fix: Plan only fields whose top-level annotation is float or a top-level Union containing float; take nullability from the top-level union args only. Either walk list/tuple/dict values (nullable element type -> None; otherwise reject with '<Model>.<field>[i] must be a finite number', never echoing the value), or narrow the CHANGELOG/docs to scalar float fields and file a follow-up. Derive test expectations from an independent source (e.g. `model_json_schema()` number properties). Add a test-local ContentModel with `list[float]`, `dict[str, float]` and `float | list[float | None]`, injecting at element level.
- codify: A type-walker that finds float anywhere in an annotation must check values at the same depth it matched; derive per-field rules from the top-level annotation, because flattening get_args gives false 'covered' and false 'nullable' results for containers.

### RT-002
- severity: medium
- file: agent_sdk/models/content_types.py (+ tests/test_content_types.py, docs/content-types.md, CHANGELOG.md)
- description: Any-typed built-in fields still split wire and text (raised in 7 rounds). `ComparisonTable.rows` (list[dict[str, Any]], ~line 783), `SeriesMeta.points` (~line 724) and `CategoryValue.metadata` (dict[str, Any] | None, ~line 991) accept nan/inf. Verified: `ComparisonTable(rows=[{'v': nan}])` gives `wire()` -> `{'v': null}` but `to_plain_text()` -> 'nan' ('  V\n  -\n  nan'); inf renders 'inf'. This is the divergence the GH-173 ruling forbids ('wire(), model_dump_json() and the text fallbacks must then agree'). `CategoryValue.metadata` also lacks the `_metadata_finite` guard `ContentModel.metadata` has. The old `_assert_finite` docstring listed ComparisonTable.rows as an exception; the rewrite (~line 264) dropped it, so the exemption is now written down nowhere. docs/content-types.md ('Built-in content models never carry nan, inf or -inf on the wire') and the CHANGELOG do not name it. `test_comparison_table_accepts_non_finite_row_value_outside_scope` (tests/test_content_types.py:822) still pins acceptance and checks neither output. Pandas-built table rows are the most common real NaN source.
- fix: Either coerce non-finite numeric cells in these three fields to None in a bounded before-validator walk (a cell typed Any can hold None, and wire() already emits null), then invert the test to assert both wire() and to_plain_text(); or keep the carve-out explicitly: restore the docstring exception note, name the fields in the CHANGELOG and docs, make the text renderer print '-' or blank for non-finite cells, and rename the test to say it pins a known divergence (with a follow-up issue reference).
- codify: When narrowing a guard's scope statement, carry previously listed exceptions forward explicitly; dropping them turns a documented gap into an undocumented one.

### RT-003
- severity: medium
- file: agent_sdk/models/content_types.py (+ tests/test_gh172_component_name_rules.py)
- description: Type guard runs after the first method call (raised in 8 rounds). In `register_content_type`, `folded = component.casefold()` (~line 1406/1440) runs before `if not isinstance(component, str) or not _COMPONENT_NAME_RE.fullmatch(component)` (~line 1420/1454), so the isinstance branch is dead. Verified: `component = 123` crashes boot with `AttributeError: 'int' object has no attribute 'casefold'` instead of the documented error naming the card. The docstring (~lines 1374-1375 / 1408) still says only 'Validates the frozen-name and uniqueness rules'. Test gaps: `test_bad_component_name_refused` matches only on the offending name, which every message contains, so it cannot tell which rule fired; the kpiCard/KPICard cases never assert the existing name 'KpiCard' appears, which the AC requires; 'kpiCard' hits the case-clash branch, so the lowercase-first regex check is never tested alone; no domain-vs-domain clash case.
- fix: Move the isinstance + `_COMPONENT_NAME_RE.fullmatch` check to just after the data_type/component presence check, before the RESERVED exact check and both casefold loops; raise TypeError for a non-str. Update the docstring with the `^[A-Z][A-Za-z0-9]*$` rule and the case-insensitive reserved/registered clash rule. Tests: add a non-str row (123), a lowercase-first non-clashing row ('tradeFeed'), a domain-vs-domain clash ('TradeFeed' then 'Tradefeed'); parametrize expected text per rule ('differs only in case' + 'KpiCard' for kpiCard/KPICard; 'PascalCase' for my_card).
- codify: Type guards must come before the first method call that assumes the type; a guard placed after it is dead code.

### RT-004
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: A non-finite value in MCP tool output becomes HTTP 500, not an isError result (raised in 3 rounds). On the legacy HTTP+SSE path (`mcp_messages`, ~line 1160/1161) the new `json.dumps(response, allow_nan=False)` raises a ValueError nobody catches (only QueueFull is caught): the POST returns 500 and the SSE stream never gets a reply for that request id, so the client hangs until timeout. The Streamable POST path (JSONResponse, ~line 857) fails the same way because Starlette renders with allow_nan=False. Verified with a domain card `values: list[float] = [nan, 1.0]` via POST /mcp tools/call -> 500. Sources: container float fields (RT-001), post-construction mutation, `model_construct()`, or a custom `wire()`. MCP rules say tool faults must come back as `isError: true`; A2A fails the same tool cleanly with -32006. The CHANGELOG Fixed entry says the MCP writer change makes such a value 'fail the task with -32006', which is false for MCP (and for `sse_data` the result is a stream abort).
- fix: In `_call_tool` / `_handle_tools_call` (~lines 700-715), dry-run `json.dumps(result, allow_nan=False)`; on ValueError log the error type only and return `{"content":[{"type":"text","text":"tool output is not valid JSON"}],"isError":true}`. At ~line 1160 catch ValueError and queue a fixed-text -32603 JSON-RPC error carrying the original request id. Correct the CHANGELOG sentence per path. Add tests that push a post-construct NaN through both MCP transports.
- codify: A wire-level allow_nan=False change must be matched on every surface by a graceful protocol error (A2A -32006, MCP isError, AG-UI RUN_ERROR); a bare 500 breaks the JSON-RPC rule that every request gets a response.

### RT-005
- severity: medium
- file: agent_sdk/routes/ag_ui.py (+ agent_sdk/agent/openai_client.py, agent_sdk/common/json_strict.py)
- description: Non-finite floats still reach AG-UI as invalid JSON inside string fields (raised in 2 rounds). `TOOL_CALL_ARGS.delta` (~line 322) and `TOOL_CALL_RESULT.content` (~line 330) use `json.dumps(..., default=str)` with allow_nan left on. Tool arguments come from the lenient `json.loads` in openai_client.py:310, which accepts model output like `NaN` or `1e999`. Verified: delta = '{"v": NaN, "w": Infinity}', content = '{"y": Infinity}'. A client that JSON.parse()s these fails. This makes the json_strict.py docstring (line 10: 'Every outbound writer in the SDK uses allow_nan=False') false, and the CHANGELOG claim that AG-UI 'fails the task with -32006 instead of streaming NaN' is wrong because TOOL_CALL_RESULT is sent first.
- fix: Serialize both fields with allow_nan=False; on ValueError sanitize non-finite floats to null (small recursive walk) or emit a fixed placeholder. Parse model tool arguments with `loads_strict` so a non-finite argument becomes a tool-argument error. Correct the json_strict docstring and CHANGELOG to list only the writers really covered. Add a test mapping ToolCallEvent and ToolResultEvent carrying nan/inf and asserting both strings parse under a strict parser.
- codify: An 'every outbound writer is strict' claim must be grep-verified: any json.dumps that builds a JSON string embedded in a frame field (args deltas, tool-result content) is also a wire writer.

### RT-006
- severity: medium
- file: agent_sdk/agent/runner.py (+ agent_sdk/models/content_types.py)
- description: The GH-173 guard runs only at model construction. Assignment, `model_copy(update=...)` and `model_construct` skip it. Verified: `b=BarItem(category='x',value=1.0); b.value=float('nan'); json.dumps(b.wire())` -> `NaN`. Status at close: the runner.py:464 dry-run now passes `allow_nan=False` (landed in a later round), so A2A fails the task via -32006; the MCP side is RT-004. Still missing: a test that mutates a card after construction and asserts the task fails cleanly.
- fix: Add that test (A2A path asserts FAILED with -32006; MCP path covered by RT-004). Optionally set `validate_assignment=True` on `_Wire`.
- codify: A construction-time validator is not a wire guarantee; the last serializability check before the wire must use allow_nan=False.

### RT-007
- severity: medium
- file: agent_sdk/routes/a2a.py (+ agent_sdk/routes/ag_ui.py)
- description: Stream-only terminal failure (raised in 4 rounds). `_unserializable_tail` (~line 762) sends a final:true 'failed' status-update to that one subscriber but never moves the stored TaskRecord to FAILED and never stops the worker. The task can keep running and finish 'completed', so tasks/get and resubscribe contradict the terminal frame the client saw; tasks/get can also return HTTP 500 because the same unserializable data is still on the record. When the snapshot itself fails, the tail is the first frame with no Task snapshot before it. The AG-UI `_emit` guard (~ag_ui.py:640) has the same gap: RUN_ERROR is sent, but the worker keeps spending model and tool budget.
- fix: When the tail fires, transition the record to FAILED with the same fixed -32006 error via `runner.set_task_status` (C-019) and cancel the worker, as the build_artifact failure path does. Same for AG-UI. Or document the path as stream-local in DESIGN.md. Extend `test_a2a_stream_unserializable_frame_ends_with_one_final_frame` to GET the task afterwards and assert state == failed.
- codify: A stream-level terminal frame must be matched by the same terminal transition in the task store, or protocol reads contradict the stream.

### RT-008
- severity: medium
- file: docs/content-types.md
- description: The new 'Non-finite numbers (GH-173)' section (lines ~96-102) contradicts the code (raised in 6 rounds). (1) It says '`BriefingKpiItem` (the `MarketBriefing` family) keeps rejecting in both cases', but content_types.py:866 dropped 'delta' from the `_reject_non_finite` validator, so `BriefingKpiItem.delta` now coerces nan to None (live probe returns {'title':'t','value':1}); the CHANGELOG Breaking entry and `test_briefing_kpi_item_coerces_nullable_delta_and_rejects_value` say so. (2) 'Built-in content models never carry nan, inf or -inf on the wire' is false for the Any-typed fields (RT-002). (3) 'Your own `_Wire` models get the same rule for free' points at a private class and is false for container fields (RT-001); it also omits that nullable `int` fields are coerced too.
- fix: Rewrite: `BriefingKpiItem.value` still rejects (GH-95); `BriefingKpiItem.delta` is nullable and now coerces to None like every other nullable field. Name the exempt free-form fields (or fix RT-002). Say 'ContentModel subclasses and their nested item models' instead of `_Wire`. Mention nullable int fields. State container coverage per RT-001.
- codify: When a ruling changes an older guard's behaviour, grep the docs for that guard's class name and update every sentence that describes it in the same change.

### RT-009
- severity: medium
- file: DESIGN.md (+ harness/skills/add-tool/SKILL.md, template/.claude/skills/add-tool/SKILL.md)
- description: The GH-172 breaking boot rule and the GH-173 float rule are taught only in docs/content-types.md (raised in 7 rounds). DESIGN.md:231 (§4.3/§4.5, and :218) still lists only data_type/component uniqueness, the four RESERVED names and the frozen catalog_id; DESIGN.md:233 describes the non-finite check for `metadata` only. harness/skills/add-tool/SKILL.md (:81, :92-94) and its byte-identical mirror template/.claude/skills/add-tool/SKILL.md say only 'PascalCase wire name' / exact-name uniqueness. Agents learn the SDK through skills (scope rule), so an agent following the skill can pick `KPICard` or `my_card` and fail at boot. Repeats the LRN-169/LRN-208/LRN-314 pattern.
- fix: Add one sentence to DESIGN.md, both SKILL.md copies (keep them byte-identical): component must match `^[A-Z][A-Za-z0-9]*$` and must not equal a reserved or registered name ignoring case (KPICard next to KpiCard is refused at boot). Add the GH-173 rule (non-nullable float rejects, nullable coerces to None) next to DESIGN.md:233, citing both ruling URLs. Declare these files in the todo.
- codify: A new boot-time validation rule must land in DESIGN.md and the add-tool skill (harness copy and template mirror), not only in docs/.

### RT-010
- severity: medium
- file: CHANGELOG.md
- description: GH-173 / GH-172 entries are incomplete or inaccurate (raised in 3 rounds). `_finite_floats` and `hide_input_in_errors=True` sit on `_Wire`, so every downstream domain ContentModel changes too: a `score: float` given nan now fails tool output, a `score: float | None` given nan silently becomes None, and validation error text no longer carries input values — no downstream notice or migration line. docs/content-types.md:101-102 names the private `_Wire`. 'three old accepts-non-finite tests were inverted' is wrong: four or five changed (metric_item, bar_item, waterfall_segment, fund_performance, plus the BriefingKpiItem delta test). Stray capital in the GH-172 entry ('; A case-sensitive client'). Neither Breaking entry cites an external spec clause for the DESIGN.md §4.0 stable-core exemption (RFC 8259 appears only in the Fixed entry). `MetricItem.from_any` now silently drops nan metrics (RT-016) without a mention. The '-32006 on every writer' claim is wrong for MCP and AG-UI (RT-004, RT-005).
- fix: Add a sentence that domain ContentModel subclasses inherit the rule and the hidden-input error text, with a one-line migration (return a finite value, or make the field `float | None`). Fix the test count and the capital. Cite RFC 8259 §6 for GH-173 and the A2UI v0.9.1 PascalCase component-name rule for GH-172. Mention the from_any change. Correct the per-path failure wording.

### RT-011
- severity: medium
- file: CHANGELOG.md (+ pyproject.toml, workspace/todos/active/w049-gh-issues.md)
- description: Release-state check (LRN-212 / LRN-232 / LRN-239; raised in 4 rounds). [Unreleased] holds two Breaking entries (GH-172 boot refusal, GH-173 reject/coerce) that change stable-core wire behaviour in agent_sdk/models/; the todo targets 0.13.0, but pyproject.toml is still 0.12.1 and GH-171/172/173 are still `- [ ]`. The standing 'bump-patch before push' habit would ship this as 0.12.2, the same failure the deleted test_content_types.py comment recorded ('shipped a self-declared breaking change as a patch release').
- fix: Do not pre-bump in the wave; run /sdk-release with 0.13.0 explicitly (minor bump, not bump-patch). Make the CHANGELOG heading match pyproject.toml exactly, and tick/archive GH-171..173 in the same release commit.
- codify: A Breaking heading in [Unreleased] overrides the default bump-patch rule; the release gate must check the bump level against the CHANGELOG headings and carry the target minor version into the release invocation explicitly.

### RT-012
- severity: medium
- file: agent_sdk/common/json_strict.py (+ workspace/components/README.md, agent_sdk/routes/mcp.py, agent_sdk/agent/runner.py, agent_sdk/common/sse.py)
- description: Component reuse (Dimension 8; raised in 2 rounds). `loads_strict` is a new shared utility used by 4 route modules but is not registered in workspace/components/README.md. Lenient `json.loads` is still used on other client-controlled JSON: agent_sdk/credentials/forwarding.py:75 (X-Agent-Credentials header on every protocol request), agent_sdk/contrib/webhooks/graph.py:106 (webhook body) and the FastAPI Body() on /admin/api/tools/{name}/try (admin.py:563), yet the CHANGELOG claims rejection 'at every protocol ingress'. The strict-writer check is implemented three times: `_is_writable` in routes/mcp.py:356, the build_artifact dry-run in runner.py:464, and `sse_data` in common/sse.py:25.
- fix: Register `loads_strict` as a C-NNN. Route forwarding.parse_header and the Graph webhook body through it, or narrow the CHANGELOG claim to the routes actually changed; add an ingress test for the forwarding header. Add `dumps_strict` / `is_strict_json` beside it and have the three writers call it.
- codify: A new 'single shared parser' must be registered as a component and grep-verified against every json.loads on client-controlled input before the CHANGELOG says 'every ingress'; its write-side twin lives next to it.

### RT-013
- severity: medium
- file: .claude/workflows/sdk-wave.js (+ workspace/todos/active/w049-gh-issues.md, tests/test_a2ui_wire.py)
- description: Scope drift (LRN-207 / LRN-322; raised in 5 rounds). The phase-redteam scope is frozen at Parse (sdk-wave.js lines 773-827) and never re-read after fix rounds amend the todo. This phase review saw 8 paths and missed json_strict.py, runner.py, sse.py, routes/{mcp,ag_ui,a2a,oauth}.py and three test files, and still included tests/test_a2ui_wire.py after the todo removed it; the undeclared-scope / dirty-tree gates compare against a stale set. The GH-171 todo listed tests/test_a2ui_wire.py as modified, but it has no diff (coverage went to tests/test_gh171_fallback_schema_required.py). tests/test_a2ui_group_d.py, tests/test_content_types.py and tests/test_protocol_fixes_w6.py are modified without a Creates:/Modifies: line. tests/test_gh173_mcp_non_finite_output.py is named in the CHANGELOG but not in any Creates line. The GH-171 AC 'many fields keeps every required field in the prompt section' is tested only against private `_field_summary()`, never against `get_system_prompt_section()`, which is what the model sees.
- fix: Re-run the deterministic Creates:/Modifies: scan (GH-164 scope-scan block) at the start of every phase-redteam round and before the protocol audit, unioning into wave.allScope. Fix the todo's Creates/Modifies lines. Add a test (in tests/test_a2ui_wire.py, or drop that path from the todo) that registers a many-field domain card, calls `get_system_prompt_section()`, and checks required fields appear without '?' via `parse_schema`/`required_paths`.
- codify: Wave scope derived from the todo file must be refreshed whenever a fix round may edit that file; a Parse-time snapshot silently narrows every later review and scope gate.

### RT-014
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Dead, duplicated and leaky code in the GH-173 validators (raised in 7 rounds). `_Wire._rejects_non_finite: ClassVar[bool] = False` (line 323) is never set to True anywhere (leftover from a design where BriefingKpiItem rejected both fields); it is a half switch that skips only the before-validator, so setting it makes nullable int fields reject while `_finite_floats` still coerces floats. The matching `GH95_REJECTING: set[str] = set()` in tests/test_gh173_non_finite_values.py is a dead filter. `_nullable_numeric_keys` (~288) and `_float_field_plan` (~305) repeat the same annotation-flatten loop word for word, with a third copy in the test file. Both are `@functools.cache` keyed by class, which holds a strong reference to every `_Wire` subclass ever validated (dynamic and test classes) for the life of the process — the leak DBG-7 fixed in this module with a WeakKeyDictionary.
- fix: Remove `_rejects_non_finite` and `GH95_REJECTING` (or make the switch cover both validators, with a test and docs). Extract one `_flatten_annotation` helper (fixed per RT-001). Compute both plans once in `__pydantic_init_subclass__` and store them as a ClassVar, or cache in a `weakref.WeakKeyDictionary`.

### RT-015
- severity: medium
- file: tests/test_gh173_non_finite_values.py
- description: Vacuous 'error names the field' assertions. `assert name in msg` in `test_every_float_field_follows_ruling` and `assert "value" in str(exc.value)` in `test_issue_repro_bar_chart_rejects` always pass for fields named `value`, because str(ValidationError) ends with 'https://errors.pydantic.dev/2.x/v/value_error'. That covers BarItem.value, CategoryValue.value, MetricItem.value and WaterfallSegment.value (4 of 5 non-nullable fields); only `cumulative` is really checked. The error comes from a model-level validator, so `errors()[0]['loc']` is `()` (verified on CategoryValue).
- fix: Assert `f"{cls.__name__}.{name}"` in `exc.value.errors()[0]['msg']`, or raise from a field-level validator so `loc == (name,)` and assert on loc. Never substring-check str(exc).
- codify: Never assert a field name is 'in str(ValidationError)': pydantic's trailing docs URL contains 'value_error', so the check passes for any field named value; assert on errors()[i]['loc'] or ['msg'].

### RT-016
- severity: low
- file: agent_sdk/models/content_types.py
- description: `MetricItem.from_any` (~line 606) catches (ValueError, TypeError), and pydantic ValidationError subclasses ValueError, so `from_any('a', float('nan'))` now silently returns None and drops the metric (verified). The docstring still says None is returned only for non-scalar or bool values.
- fix: Update the docstring to include non-finite numbers, add a test pinning None for nan/inf, and mention it in the GH-173 CHANGELOG entry (see RT-010).

### RT-017
- severity: low
- file: agent_sdk/models/content_types.py
- description: `_nullable_numeric_keys` adds only the field name and `info.alias`. A domain field `n: int | None = Field(validation_alias=AliasChoices('n','nn'))` given nn=nan is not coerced in the before-validator; pydantic then rejects with 'Input should be a finite number' (verified), breaking the GH-173 'nullable coerces' ruling for validation_alias fields.
- fix: Also add the str entries of `info.validation_alias` (str, `AliasChoices.choices`, first element of `AliasPath`), or coerce in a field-level wrap validator instead of a dict-key lookup.

### RT-018
- severity: low
- file: agent_sdk/a2ui/catalog.py (+ tests/test_gh171_fallback_schema_required.py)
- description: GH-171 fallback summary gaps (raised in 4 rounds). `_annotation_str` (lines 63-83) renders only the first non-None union member, so `int | str | None` reads 'int|null' — now looks precise but teaches a narrower type. Its `(type, required)` return is a pass-through, so the second element is dead. The prompt legend (~line 263) explains only '? = optional', not the new 'X|null' and trailing '...' markers. Tests: `test_builtin_compact_schemas_unchanged` (line 69) pins only the KpiCard entry; no test for required-only fields over 250 characters; no test for `typing.Optional[int]` with no default.
- fix: Return only the type string; join every non-None member with '|' (rendered recursively) plus '|null' when None is present; keep `required = info.is_required()` in `_field_summary`. Extend the legend: '? = optional, |null = may be null, ... = more optional fields omitted'. Snapshot the whole `_COMPACT_SCHEMAS` mapping (or assert every built-in uses its entry verbatim in `get_system_prompt_section()`), and add the over-250-chars and Optional[int] cases.

### RT-019
- severity: low
- file: tests/test_gh173_non_finite_values.py (+ tests/test_content_types.py)
- description: Test quality leftovers (raised in 5 rounds). The SI-2 end-to-end test `test_tool_error_text_has_no_non_finite_literal` uses only the GH-95 `_assert_finite` path (BriefingKpiItem), never the new `_Wire._finite_floats` message path, and reads the in-memory task store/toolResult rather than a JSON-RPC or MCP response body, which AC(SI-2)(3) asks for. A second import block (asyncio, runner imports) sits partway down the module after test code (~line 216, E402). The comment at tests/test_content_types.py:830-842 still says MetricItem.value, BarItem.value, WaterfallSegment.value and FundPerformance.irr are 'NOT scoped in' and that the `*_outside_scope` siblings are 'unchanged and still correct', false after GH-173 for every field except ComparisonTable.rows.
- fix: Run the SI-2 tool test with both BriefingKpiItem and a BarChart/BarItem builder, and add one case through MCP tools/call or A2A message:stream asserting the response body is valid JSON (`json.loads` with a raising `parse_constant`) and has no nan/inf literal. Move all imports to the top. Rewrite the test_content_types.py comment to state the GH-173 ruling, name ComparisonTable.rows as the remaining exemption (see RT-002), and point to tests/test_gh173_non_finite_values.py.
