# w067 — group G3 — deferred medium/low findings

- Wave: w067
- Scope: unit:G3
- Date: 2026-10-25

Non-blocking — these did not block w067's archive. Address opportunistically or fold into a future wave.

Findings were merged across redteam rounds (deduped by file + description). All are SDK candidates.

## Medium

### D1. `wire_keeps_null` / `wire_omitted` declared on `_Wire` but not enforced by `wire()`
- File: agent_sdk/models/content_types.py:370 (`wire_keeps_null: ClassVar[frozenset[str]] = frozenset()`); `wire()` at :401
- Issue: `_Wire.wire()` is a plain `model_dump(exclude_none=True)`. Only the bespoke serializers on ColumnDef, DocumentItem, TimeSeriesDataPoint honour the settings. A ContentModel with `wire_keeps_null={'kept'}`, `kept: float|None` gets summary `{kept: float|null}` (required) but `wire()` drops `kept`. A `wire_omitted={'hide'}` field shows `hide?` but is still written. Pops/inserts use Python field names, so aliased fields are missed under by_alias. Fixture `_Nullable` (tests/test_gh258_catalog.py:211) locks in the drift and never calls `wire()`.
- Fix: one wrap model_serializer on `_Wire` (applies to nested models) that re-inserts `None` for `wire_keeps_null` names (under serialization alias) and pops `wire_omitted` names; drop the per-class loops, keeping only class-specific conditions. Minimum alternative: `__pydantic_init_subclass__` rejects `wire_keeps_null` on a class with no custom serializer. Test: `_Nullable(kept=None, dropped=None, plain='p').wire()` has `kept: None`.
- Codify: a declarative wire rule on a base model must be enforced by the base serializer, or downstream declarations desync prompt and wire.

### D2. TimeSeriesChart `x_key`/`y_key` assignment after construction not guarded
- File: agent_sdk/models/content_types.py:784 (`x_key: Literal["date"] = "date"`)
- Issue: GH-262 item 4. `chart.x_key = 'month'` succeeds at runtime and `wire()` emits it; no `validate_assignment`, field not frozen. Only a type checker catches it; no test covers assignment.
- Fix: `Field(default="date", frozen=True)` (same for y_key), or `validate_assignment=True`, or a serializer that always writes `date`/`value`. Add a test that assignment raises (or is normalised). If the type-checker-only guard is accepted, say so in CHANGELOG.
- Codify: a Literal annotation does not guard attribute assignment.

### D3. Round-trip test is one-directional and does not reach nested shapes
- File: tests/test_gh258_catalog.py:276-279 (`missing = required - emitted_paths(inst.wire())`); TimeSeriesChart instance at :267
- Issue: only checks required ⊆ emitted. 7 of 13 types (TimeSeriesChart, WaterfallChart, MultiCategoryChart, EmailList, CalendarEvents, UserProfile, FundPerformance) fall back to depth 0, so no nested paths; the AC case "TimeSeriesChart with a value=None point" checks nothing about `data[].value`. Reverse direction unchecked: EntityList/DocumentList `total_count` (after-validator, content_types.py:930, :1517) is always written but shown `total_count?`.
- Fix: compare each nested `_Wire` sub-object's `_nested_fields(sub, 0)` (or depth-1 unbudgeted summary) with its `wire()`. Assert both directions; declare validator-filled fields always-written (e.g. a `wire_always` ClassVar read by `_wire_required`) or list them as documented exceptions.
- Codify: a summary-vs-wire parity test must compare both directions.

### D4. Annotated discriminated union renders as `[Annotated]` (MarketBriefing)
- File: agent_sdk/a2ui/catalog.py:109 (`cls_name = getattr(ann, "__name__", None)`)
- Issue: GH-262 item 1 not fixed. `_field_summary(MarketBriefing)` gives `sections: [Annotated]` (BriefingSection, content_types.py:1002). MarketBriefing is subtracted from the coverage test (tests/test_gh258_catalog.py:286).
- Fix: at top of `_annotation_str`, `if typing.get_origin(ann) is typing.Annotated: recurse on get_args(ann)[0]` (render union members). Remove the exclusion or add a MarketBriefing instance; assert no `Annotated` in its summary.
- Codify: a coverage test that subtracts the type named in the bug report is not coverage; exclusions need a stated reason.

### D5. IntEnum values still render quoted
- File: agent_sdk/a2ui/catalog.py:107 (Enum branch)
- Issue: GH-262 low only half fixed. IntEnum field renders `"1|2"` while `wire()` writes a number. `test_int_enum_and_literal_values_unquoted_numbers` covers only Literal.
- Fix: see D6 (per-value json.dumps). Add an IntEnum case asserting `1|2` present, `"1|2"` absent.
- Codify: when a fix covers two parallel paths (Enum and Literal), test both.

## Low

### D6. Literal value rendering uses Python `str()`
- File: agent_sdk/a2ui/catalog.py:104
- Issue: `Literal[True, False]` renders `True|False`, `Literal[None]` renders `None`; mixed `Literal['a', 1]` loses quotes on the string.
- Fix: render each value with `json.dumps(v)` (enum: `json.dumps(m.value)`) and join with `|`. Extend tests for IntEnum, mixed, bool Literals.

### D7. Unused `required` pass-through on `_annotation_str` kept with an incorrect reason
- File: agent_sdk/a2ui/catalog.py:68; CHANGELOG.md:24
- Issue: ruling said "fix the lows as listed". CHANGELOG says it stays because tests patch the signature, but `_boom(ann, required)` in tests/test_catalog_narrow_except_logs_fallback.py already mismatches the 3-arg call and passes on TypeError.
- Fix: `_annotation_str(ann, depth=0) -> str`; update call sites and both `_boom` stubs to `*args, **kwargs`; remove the CHANGELOG excuse (or cite a real ruling).

### D8. Stale required rule in `_field_summary` docstring and DESIGN.md:257
- File: agent_sdk/a2ui/catalog.py:176; DESIGN.md:257
- Issue: both still say "no default, or a non-None default", contradicting the GH-262 rule stated later in the same DESIGN paragraph.
- Fix: reword to: required when wire() always writes it — not in `wire_omitted`, and either in `wire_keeps_null` or non-nullable with no default or a non-None default.

### D9. Tautological x_key assertion; misnamed test
- File: tests/test_gh258_catalog.py:295 (`assert "date" not in str(exc.value) or "value" in str(exc.value)`); :342
- Issue: always true; x_key rejection message never asserted. `test_gh262_wire_omitted_drives_serializers_and_catalog` never touches the catalog.
- Fix: replace with `_chart(x_key='other')` asserting `"x_key must be fixed to 'date'"`; keep the y_key assertion. Add a `_field_summary`/required_paths assertion to the :342 test (e.g. `unit`/`size` optional) or rename it.

### D10. Ad hoc regex rewrites instead of extending shared C-020 `parse_schema`
- File: tests/test_gh258_catalog.py:254 (`def _parse(summary: str)`)
- Issue: `tests/_compact_schema.parse_schema` fails on 6 of 13 raw summaries (BarChart, ComparisonTable, DocumentList, EntityList, KpiCard, UserList: `Model{...}`, `X|Model|null`). Regex workarounds are fragile and bypass the registered helper.
- Fix: teach `parse_schema` to skip a type-name token before `{` and treat `{key: V}` as a map; call `required_paths(parse_schema(_field_summary(cls)))` directly as test_gh171 does.

### D11. `wire_omitted` means two different things
- File: agent_sdk/models/content_types.py:845 (`if not getattr(self, name):`); DocumentItem :1506
- Issue: ColumnDef pops a listed key only when falsy; DocumentItem always pops. Subclass behaviour depends on parent.
- Fix: pick one meaning (always), with ColumnDef `is_id`-when-False as its own named condition; or split into `wire_omitted` and `wire_omitted_when_falsy`. Ties into D1.
