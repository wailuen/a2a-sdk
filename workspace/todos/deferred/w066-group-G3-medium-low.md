# w066 — unit:G3 — deferred medium/low findings

- Wave: w066
- Scope: unit:G3
- Date: 2026-10-25

Non-blocking — these did not block w066's archive. Address opportunistically or fold into a future wave.

Findings accumulated across every redteam round, deduped by file + description (merged duplicates list all round IDs).

## Medium

### G3-1 (RT-001 / RT-002, round-merged) — `agent_sdk/a2ui/catalog.py:126-128` — sdkCandidate
Quote: `    return info.default is not None`
- Problem: `_wire_required()` infers required-ness from the default value, not from what `wire()` writes. Models with a `model_serializer` that drops defaulted keys are still shown as required. `ColumnDef.is_id` (default False) is popped by `_omit_is_id_when_false` (content_types.py:829-832), so a domain card nesting `ColumnDef` renders `is_id: bool` as required while `wire()` gives `{'columns': [{'key': 'a', 'label': 'b'}]}`. `DocumentItem.web_url` / `last_modified` (always popped) are listed as `web_url?`. Breaks the GH-258 ruling that the prompt shows exactly the `wire()` contract.
- Fix: derive required-ness from real wire output where a model has a custom `model_serializer` (dump a default-built instance, or a class-level set such as `_wire_omitted_fields = {'is_id'}` on ColumnDef and `{'web_url','last_modified'}` on DocumentItem) and treat those fields as optional or hide them. Add a test in tests/test_gh258_catalog.py nesting ColumnDef in a domain ContentModel asserting `required_paths(parse_schema(summary)) <= emitted_paths(wire())`.
- Codify: a required-ness rule built from field defaults must account for `model_serializer` hooks that drop keys; test it against `wire()` on nested SDK sub-models, not only flat test models.

### G3-2 (RT-003) — `agent_sdk/a2ui/catalog.py:122` — sdkCandidate
Quote: `    if info.is_required():`
- Problem: a required nullable field (no default, `X | None`) is shown required (`top: str|null`), but `ContentModel.wire()` (exclude_none=True) and plain BaseModel nesting drop it when None. Verified: `top: str | None` and `Inner.v: float | None` render required, yet `wire()` returns `{'inner': {}}`. The `_wire_required` docstring contradicts itself.
- Fix: return False for a required field whose annotation allows None, unless the owner is a `_Wire` subclass that keeps required nullable fields (as `TimeSeriesDataPoint.value`); or render as `name?: X|null`. Fix the docstring; test top-level and nested-plain-BaseModel cases.
- Codify: exclude_none=True means a required nullable field is absent when None. "No default" is not "always written".

### G3-3 (RT-004) — `tests/test_gh258_catalog.py:97` — sdkCandidate
Quote: `    wired = emitted_paths(_Plain(needed="n").wire())`
- Problem: the only summary-vs-wire test uses a flat `_Plain` model; G3-1, G3-2 and the exclude=True case all pass unnoticed (4509 passed). AC item 1 has no test where the default-based rule is wrong.
- Fix: parametrize `test_wire_emits_what_summary_marks_required` over: an exclude=True default_factory field, nested ColumnDef, a required nullable set to None, a nested `_Wire` model. Assert `required_paths(parse_schema(_field_summary(M))) <= emitted_paths(M(...).wire())`.

### G3-4 (RT-002, round 2) — `agent_sdk/models/content_types.py:773` — sdkCandidate
Quote: `    x_key: str = "date"`
- Problem: the TimeSeriesChart x_key/y_key lock lives only in a field_validator; fields stay `str`. `c.x_key = 'month'` after construction is accepted and `c.wire()['x_key'] == 'month'` (silent never-renders chart; LRN-354 pattern). MCP outputSchema from `model_json_schema()` (agent/registry.py:868) advertises `{'type': 'string', 'default': 'date'}`.
- Fix: `x_key: Literal["date"] = Field(default="date", frozen=True)`, `y_key: Literal["value"] = Field(default="value", frozen=True)` (keep the fixed-message validator or rely on the literal error). Add a test that assignment after construction raises.
- Codify: a value lock on a model field must hold at assignment and in the advertised JSON schema, not only in a construction-time field_validator.

## Low

### G3-5 (RT-005) — `agent_sdk/a2ui/catalog.py:218` — sdkCandidate
Quote: `    while len(", ".join(p for p, _ in kept)) > 250:`
- Problem: the 250-char budget counts only the inner joined text, not braces or the appended `, ...`; output can reach 251-252 (up to 257 after optional drops) while docstring and `test_nested_expansion_stays_within_budget` treat 250 as the full line.
- Fix: measure `len('{' + ', '.join(texts + (['...'] if dropped else [])) + '}')` in both the drop loop and the fits check; add a test with inner length 249-250.

### G3-6 (RT-006 / RT-005, round-merged) — `agent_sdk/a2ui/catalog.py:105` (and Literal branch line 102) — sdkCandidate
Quote: `        return '"' + "|".join(str(m.value) for m in ann) + '"', required`
- Problem: enum values are always quoted. For IntEnum / int-valued Enum (and int Literals) the prompt shows `lvl: "1|2"` while `wire()` (mode=json) writes a number.
- Fix: quote only when every value is a str (or render each with `json.dumps` and join with `|`); add an IntEnum case to `test_enum_and_literal_list_values`.

### G3-7 (RT-007 / RT-004, round-merged) — `agent_sdk/models/content_types.py:789` — sdkCandidate
Quote: `            raise ValueError(f"TimeSeriesChart {info.field_name} must be fixed")`
- Problem: the fixed message does not name the allowed value; a developer cannot tell x_key must be "date" / y_key "value" without reading source or CHANGELOG.
- Fix: `f'TimeSeriesChart {info.field_name} must be "{expected}"'` (expected is a constant, no input echo); update the CHANGELOG entry and test assertion.

### G3-8 (RT-003, round 2) — `CHANGELOG.md:10` — sdkCandidate
Quote: `- GH-258: \`TimeSeriesChart\` now rejects any \`x_key\` other than \`"date"\` ... **Migration:** drop custom \`x_key\`/\`y_key\` arguments.`
- Problem: the Breaking entry does not say domain subclasses of TimeSeriesChart inherit the validator (LRN-356), and quotes only the x_key message.
- Fix: add "Subclasses of TimeSeriesChart inherit the check; a subclass with its own data-point keys must map them to date/value." Quote both messages (`TimeSeriesChart x_key must be fixed` / `TimeSeriesChart y_key must be fixed`), or the new messages if G3-7 lands.

### G3-9 (RT-006, round 2) — `agent_sdk/a2ui/catalog.py:212` — sdkCandidate
Quote: `            type_str, required = _annotation_str(ann, required, depth)`
- Problem: after GH-258 `_annotation_str` never changes `required` but still takes/returns it; the caller reassigns it. Dead weight that invites the annotation overriding `_wire_required()` again.
- Fix: make `_annotation_str(ann, depth)` return only the type string; drop `required` from recursive calls and from `_nested_fields` / `_summary_at_depth`.
