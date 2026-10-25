# w068 — Group G3 deferred findings (medium / low)

- Wave: w068
- Scope: unit:G3
- Date: 2026-10-25
- Source: redteam rounds for G3 (GH-270 and related), deduped by file + description. Repeated reports of the same defect across rounds are merged into one entry.

Non-blocking — these did not block w068's archive. Address opportunistically or fold into a future wave.

All entries are `[SDK]`, sdkCandidate: true.

## Medium

### M1. `ser_json_inf_nan="constants"` on `_Wire` changes `model_dump_json()` for every content model
- File: `agent_sdk/models/content_types.py:374-375`
- Quote: `populate_by_name=True, hide_input_in_errors=True, ser_json_inf_nan="constants"`
- Problem: a float made non-finite after validation (assignment, `model_construct`) now dumps as invalid JSON tokens `NaN`/`Infinity`; v0.24.0 wrote `null`. Verified on MetricItem, BarChart, KpiCard, TimeSeriesSummary, TimeSeriesDataPoint, and an agent card with `list[float]`. `TimeSeriesDataPoint.wire()` with a mutated nan now keeps the float (was `None`), so strict writers refuse the artifact. `routes/mcp.py:804` `_tool_text` sends `model_dump_json()` of a non-ContentModel `_Wire` result straight to the client. Docstrings at `:276-279` (`_assert_finite`), `:406` (`_finite_floats`), `:550` (`_metadata_finite`) still say null. CHANGELOG is silent; the pin test only uses finite values.
- Fix: drop the config change and handle non-finite floats inside `_wire_rule` (e.g. when `info.mode == 'json'` restore the raw float from `self.__dict__`, or raise a fixed-text ValueError), so `model_dump_json` writes null again. Or keep it, switch `mcp._tool_text` to `dumps_strict(model_dump(mode='json'))`, add a CHANGELOG Changed entry, and fix the three docstrings. Either way pin a mutated non-finite case across `wire()`, `model_dump(mode='json')`, `model_dump_json()` in `tests/test_gh270_wire_pin.py`.
- Codify: a `ser_json_*` / `model_config` change on a shared base alters every subclass's JSON output; pin non-finite and agent-subclass output, not only valid SDK samples, before calling a refactor byte-identical.

### M2. CHANGELOG "byte-identical" claim is false for agent subclasses
- File: `CHANGELOG.md:18`
- Problem: agent cards that declared `wire_omitted` / `wire_keeps_null` without their own serializer (allowed by the DESIGN.md:257 GH-262 contract) now change. Verified: `wire_omitted={'note'}`, note='hi' gave `{'note': 'hi'}` at HEAD, now `{}`. A `wire_keeps_null` field now gains `null`. Pin covers PROFILE_TYPES only.
- Fix: move to Breaking with a Migration line (a `wire_omitted` field is now removed from wire() unless its value is True). Add a pin case for a non-profile subclass with the ClassVars and no serializer.
- Codify: a rule moved into a base class also applies to external subclasses; pin one that relied on the old per-class behaviour.

### M3. A subclass `@model_serializer` silently replaces `_wire_rule`
- File: `agent_sdk/models/content_types.py:415`
- Problem: pydantic keeps only the most-derived model serializer. A `_Wire` subclass with `wire_keeps_null={'v'}` and its own wrap serializer drops `v: null`, while the catalog still marks `v` required. Domain cards written in the pre-GH-270 per-class pattern hit this with no warning.
- Fix: in `_Wire.__pydantic_init_subclass__`, raise TypeError when `cls.__pydantic_decorators__.model_serializers` has any entry other than `_wire_rule`; point to `_wire_reshape`. Document in docs/content-types.md. Add a test.
- Codify: when a cross-cutting rule moves into a base-class model_serializer, block subclass serializers.

### M4. Serialization JSON schema (MCP `outputSchema`) changed and is not pinned
- File: `agent_sdk/models/content_types.py:415`
- Problem: deleted per-class serializers were annotated `-> dict[str, Any]`, so `model_json_schema(mode='serialization')` for TimeSeriesDataPoint, ColumnDef, DocumentItem was an open object. The unannotated base serializer now exposes full properties, changing `tools/list` outputSchema for tools emitting TimeSeriesChart, ComparisonTable, DocumentList. DocumentItem now advertises `web_url`/`last_modified`, which structuredContent never carries. Not in CHANGELOG; no test.
- Fix: keep the old schemas, or record the change under GH-270 and pin `model_json_schema(mode='serialization')` for every PROFILE_TYPES member. Leave always-omitted alias fields out of DocumentItem's serialization schema.
- Codify: moving or retyping a model_serializer changes the MCP outputSchema; a wire() pin must also pin the serialization schema.

### M5. `_values_str` crashes on Enum Literals, wiping the whole card summary
- File: `agent_sdk/a2ui/catalog.py:74`
- Quote: `return "|".join(json.dumps(v) for v in values)`
- Problem: TypeError on `Literal[PlainEnum.X]` (common discriminator pattern) and on enums with non-JSON values (Decimal, object). `_field_summary` catches it and renders `{...}` for the whole card, so the prompt loses every field. Regression from v0.24.0 (rendered `Kind.DEAL` / `"1.5"`). Also a `(str, Enum)` member renders `"StrMix.A"` instead of `"a"`.
- Fix: map `enum.Enum` members to `.value` first; `json.dumps` only int/float/bool/None/str, else quoted `str(v)`; catch TypeError/ValueError per value. Tests for `Literal[PlainEnum.X]`, `Literal[StrMixEnum.X]`, Decimal-valued enum, each asserting the exact string.
- Codify: catalog summary helpers must never raise; the catch-all silently removes the card's field list.

### M6. Catalog advertises DocumentItem keys that wire() never emits
- File: `agent_sdk/a2ui/catalog.py:155` and `:177`
- Problem: non-bool `wire_omitted` fields are always popped by the base rule (only True is kept), but `_wire_required` lists them as optional, so the DocumentList line shows `web_url?: str|null, last_modified?: str|null`. The GH-177 frozen DocumentItem contract forbids them. The reverse test cannot catch declared-but-never-emitted keys.
- Fix: in `_nested_fields` / `_summary_at_depth`, skip a `wire_omitted` field unless its annotation is bool. Add a forward assertion that `web_url` is not in `_field_summary(DocumentList)` and that summary keys are emittable.
- Codify: the omission rule and the teaching string read the same ClassVar; both must agree.

### M7. Two-way nested round-trip test (GH-270 item 4) is mostly hollow
- Files: `tests/test_gh258_catalog.py:281`, `:407-410`; `tests/_compact_schema.py:99`
- Problems (merged from five reports):
  - `undeclared_paths` / `required_paths` treat a bare-name node (`[TimeSeriesDataPoint]`, `[WaterfallSegment]`, `[EmailMessage]`, `[CalendarEvent]`, `MultiCategoryPeriod`, DateRange, TimeSeriesSummary, UserPresence, Money) as free-form, so nothing below is checked. Probe: TimeSeriesChart wire with `data[0]['bogus']=1` gives `set()`. TimeSeriesDataPoint, the main keeps-null type, is never walked.
  - Reverse test skips MultiCategoryChart, FundPerformance, UserProfile (250-char truncation). UserProfile actually has undeclared paths `{presence, out_of_office}` hidden by the skip.
  - MarketBriefing is skipped as prose in both directions, so the removed exclusion came back as a skip; its summary still advertises `{title, as_of, prose, sections}` for a markdown-string wire().
  - Instances are minimal, so optional nested keys (e.g. `ColumnDef.is_id=True`) are never emitted.
- Fix: build the schema from an untruncated summary (`catalog._summary_at_depth(cls, 1)[0]` ignoring the fits flag, or a test-only full-depth walk of `model_fields`); when a node is a bare PascalCase `_Wire` name, expand via `catalog._nested_fields(model, 0)` and recurse, both directions. Use the fuller instances from `tests/test_gh270_wire_pin.py::_instances`. Replace skips with explicit assertions (MarketBriefing: check against the dict the A2UI builder sends, or render prose types as prose); assert the skip list is empty. Add a negative test that an injected nested TimeSeriesDataPoint key is reported.
- Codify: a round-trip test bounded by a truncated prompt string, or that treats an unexpanded type name as free-form, checks only the outer layer.

### M8. `x_key`/`y_key` Breaking entry has no Migration line
- File: `CHANGELOG.md:12`
- Problem: LRN-371 (high) requires every new rejection under Breaking to carry **Migration:**; this one does not.
- Fix: append `**Migration:** do not assign to x_key/y_key; the only valid values are "date"/"value", set at construction. Use model_copy only for other fields.`

### M9. Docs and comments drifted from the GH-270 code
- Files: `docs/content-types.md:38`, `DESIGN.md:212`, `:220`, `:233`, `:257`, `agent_sdk/common/schema.py:127`
- Problem: the Breaking migration tells authors to use `_wire_reshape(self, data, info) -> bool`, but no doc covers it, `wire_keeps_null`, `wire_omitted`, the True-kept rule, or reserved hook names. DESIGN.md (spec of record) still says wire_omitted "names keys a serializer pops", describes RESERVED as component-name-only, omits the reserved data_type refusal, the snake_case warning, and frozen x_key/y_key. schema.py comment still describes per-class serializers. The G3 todo listed DESIGN.md as Reads-only (plan gap).
- Fix: add a "Custom wire shaping" paragraph to docs/content-types.md (base-applied rule, True kept, `_wire_reshape` return contract, TypeError cases). Update DESIGN.md :212/:220/:233/:257 with the #270 ruling URL. Update the schema.py comment to name `_Wire._wire_rule` / `wire_keeps_null`.
- Codify: a todo that changes a registration rule must list DESIGN.md under Modifies, not just Reads.

## Low

### L1. `_wire_rule` key choice ignores `serialize_by_alias=True`
- File: `agent_sdk/models/content_types.py:430-431`
- Quote: `if not info.by_alias:`
- Problem: on pydantic 2.13, plain `model_dump()` of a subclass with `serialize_by_alias=True` reports falsy by_alias though output is aliased. Result: `{'asOf': None, 'hiddenKey': 'x', 'as_of': None}` — omitted alias leaks, keeps-null key duplicated. `routes/admin.py:568` (`/admin/api/tools/{name}/try`) shows this. wire() is safe.
- Fix: pick the key from `data` (alias if present, else name; pop both), or fall back to `type(self).model_config.get('serialize_by_alias', False)`. Extend `test_wire_rule_addresses_keys_by_alias`.

### L2. Frozen `x_key`/`y_key` bypassable via `model_copy` / `model_construct`
- File: `agent_sdk/models/content_types.py:812-853` (`x_key: Literal["date"] = Field(default="date", frozen=True)`)
- Problem: `chart.model_copy(update={'x_key': 'ts'}).wire()['x_key'] == 'ts'` (verified).
- Fix: a TimeSeriesChart `_wire_reshape` that always writes `x_key='date'`, `y_key='value'`, or validate in wire(). Add a model_copy test.

### L3. Non-str `data_type` skips reserved check and snake_case warning
- File: `agent_sdk/models/content_types.py:1660-1701` (`if isinstance(data_type, str):`)
- Problem: bytes/int/Enum data_type registers silently, bypassing the item-1 check.
- Fix: raise `TypeError("<cls>.data_type must be a str")` next to the `not data_type or not component` guard; drop the isinstance branch.

### L4. Reserved data_type test derives expectations with the same regex as the code
- File: `tests/test_content_types.py:1662`
- Fix: hard-code `trade_activity`, `company_info`, `deal_list`, `investor_profile`; add an acronym case (e.g. `ABCCard`) with a literal expected value to the monkeypatched test.

### L5. `undeclared_paths` has no negative control
- File: `tests/_compact_schema.py:99`
- Fix: unit test `undeclared_paths(parse_schema('{a: str, b: [X{c: int}]}'), {'a': 1, 'z': 2, 'b': [{'c': 1, 'd': 2}]}) == {'z', 'b[].d'}`, plus an open-map case returning nothing.

### L6. Filler assertion and scope drift in new test file
- File: `tests/test_gh270_reserved_hooks.py:66` (`assert BaseModel is not None`)
- Fix: delete the assert and the unused `BaseModel` import. Add the file to the G3 todo's Creates line (only `tests/test_gh270_wire_pin.py` was planned).

### L7. Base wrap serializer slows every `_Wire` dump
- File: `agent_sdk/models/content_types.py:415`
- Problem: every dump now goes through a Python callback, even for 40+ classes with no rule. 5000-item EntityList wire(): 0.79 ms -> 5.38 ms (~7x); 5000-point TimeSeriesChart: 2.5 ms -> 5.8 ms. Hits every A2A/AG-UI/MCP artifact build.
- Fix: cache per class whether it has keeps_null/omitted/hook and return `handler(self)` early; or move the rule to an intermediate base (e.g. `_WireRule(_Wire)`) used only by TimeSeriesDataPoint, ColumnDef, DocumentItem, and warn in `__pydantic_init_subclass__` when a class declares the ClassVars without it.
