# w049 — GitHub issues 171–173

Sourced from open issues on wailuen/a2a-sdk. Groups run in order (G1 then G2);
GH-172 and GH-173 both edit `agent_sdk/models/content_types.py`, so they are in
different groups.
Target: 0.13.0 (GH-172 is a breaking boot check).

Maintainer rulings recorded before this wave ran.
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/172#issuecomment-6182565843
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/173#issuecomment-6182565586

---

- [ ] `GH-171` Generated compact schema marks required-but-nullable fields as optional ('?') ‖ group:G1
  - Creates: (modifies `agent_sdk/a2ui/catalog.py`, new `tests/test_gh171_fallback_schema_required.py` (includes the `get_system_prompt_section()` required-field test), `docs/content-types.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/models/content_types.py`, `tests/_compact_schema.py`
  - Severity: medium
  - Root cause: `_annotation_str` / `_field_summary` in `agent_sdk/a2ui/catalog.py` (around lines 77-90) set `required=False` whenever a union contains `None`, overriding `info.is_required()`. A domain card registered via `register_content_type` with `a: str | None` (no default) is taught to the model as `a: str?`. Separately, `_field_summary` cuts the fallback string at 247 chars and appends `...`, which can cut mid-field and drop trailing required fields.
  - AC: `?` is derived from `info.is_required()` only. A required-but-nullable field renders without `?` and shows nullability in its type (e.g. `str|null`). An optional field with a default keeps `?`.
  - AC: The fallback summary never cuts mid-field: either no cap, or truncation drops whole optional fields first and never drops a required field; if anything is dropped, a marker says so.
  - AC: Tests: a domain card with `a: str | None` (no default), `b: str | None = None` and `c: int` renders `a` without `?`, `b` with `?`, `c` without `?`; a domain card with many fields keeps every required field in the prompt section. Built-in hand-written `_COMPACT_SCHEMAS` are unchanged. Reuse the shared parser in `tests/_compact_schema.py` (C-020); do not write a second parser.
  - AC: CHANGELOG `[Unreleased]` entry under Fixed.
  - GH: https://github.com/wailuen/a2a-sdk/issues/171
  - Reuses: C-020  # tests/_compact_schema.py (parse_schema / required_paths / top_level_keys). Convention mismatch: required_paths treats a field as optional only when the KEY ends in '?' (hand-written _COMPACT_SCHEMAS style, e.g. '"title?":str'), while _field_summary (agent_sdk/a2ui/catalog.py:163) puts '?' on the TYPE ('b: str?'). Run as-is, the shared parser reports every fallback field as required, so the test cannot tell a/b/c apart and pushes toward a second parser (forbidden). Fix: have the fallback emit 'b?: str' (key marker, matching the hand-written convention) so C-020 parses it unchanged. Do not change the hand-written _COMPACT_SCHEMAS.
  - AC: The fallback summary puts the optional marker on the key (`b?: str`), not the type, so `tests/_compact_schema.py` (C-020) `required_paths` parses it unchanged and distinguishes `a`/`b`/`c`.

- [ ] `GH-172` register_content_type accepts non-PascalCase and case-variant component names ‖ group:G1
  - Creates: (modifies `agent_sdk/models/content_types.py`, `tests/test_content_types.py`, new `tests/test_gh172_component_name_rules.py`, `docs/content-types.md`, `CHANGELOG.md`)
  - Reads: `tests/test_content_types.py`, `agent_sdk/a2ui/catalog.py`
  - Severity: medium
  - Root cause: `register_content_type` (`agent_sdk/models/content_types.py`, around lines 1342-1379) blocks only exact-case matches of `RESERVED_COMPONENTS` and exact duplicates. `KPICard` registers next to the frozen `KpiCard`, `tradeactivity` next to the reserved `TradeActivity`, and `my_card` (snake_case) registers and is advertised. A2UI requires PascalCase wire names; a case-sensitive Path-B extractor silently drops case-variants (a2ui-advisor trap 18).
  - Ruling (issue 172 comment 6182565843): refuse to boot, not warn.
  - AC: `register_content_type` raises (boot failure) when the component name does not match `^[A-Z][A-Za-z0-9]*$`, or when it equals a reserved or already-registered name case-insensitively. The message names the offending component and, for a clash, the existing name. Exact re-registration rules that exist today are unchanged.
  - AC: Tests for `KPICard`, `tradeactivity`, `my_card`, `kpiCard`, and that a valid new PascalCase name (e.g. `TradeFeed`) still registers. Existing tests that register non-PascalCase test cards are updated to valid names.
  - AC: CHANGELOG `[Unreleased]` entry under Breaking changes with a **Migration** line (rename the card to unique PascalCase).
  - GH: https://github.com/wailuen/a2a-sdk/issues/172

- [ ] `GH-173` NaN/Infinity chart values leak through wire() as invalid JSON ‖ group:G2
  - Creates: (new `agent_sdk/common/json_strict.py` (`loads_strict`, strict ingress parser); modifies `agent_sdk/models/content_types.py`, `agent_sdk/agent/runner.py`, `agent_sdk/common/sse.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/a2a.py` (ingress `loads_strict` + stream final:true tail guard), `agent_sdk/routes/oauth.py` (`/oauth/register` ingress `loads_strict`), `tests/test_a2ui_group_d.py`, `tests/test_content_types.py`, `tests/test_protocol_fixes_w6.py`, new `tests/test_gh173_non_finite_values.py`, `docs/content-types.md`, `CHANGELOG.md`)
  - Reads: `tests/test_content_types.py`
  - Severity: medium
  - Root cause: `_assert_finite` (`agent_sdk/models/content_types.py` around line 248) runs only on `metadata` and the `MarketBriefing` family. `BarItem.value`, `MetricItem.value`, `WaterfallSegment.value`/`cumulative`, `CategoryValue.value`, `FundPerformance` numerics, `TimeSeriesDataPoint.value` and other float fields accept nan/inf. `BarChart(bars=[BarItem(category='x', value=float('nan'))]).wire()` returns `nan`, which `json.dumps` emits as invalid JSON (`NaN`), while `model_dump_json` emits `null`.
  - Ruling (issue 173 comment 6182565586): nullable numeric fields coerce nan/inf/-inf to `None`; non-nullable numeric fields reject with a clear error naming the field, never echoing the value.
  - AC: Every float-typed field on every built-in content model (including nested item models) follows the ruling. Nullable examples: `TimeSeriesDataPoint.value`, `MetricItem.change_pct`, `MultiCategoryPeriod.period_total`, `FundPerformance.irr`/`tvpi`. Non-nullable examples: `BarItem.value`, `WaterfallSegment.value`/`cumulative`, `CategoryValue.value`, numeric `MetricItem.value`.
  - AC: A test walks every built-in content model's float fields (not a hand list) and asserts: nullable → nan/inf/-inf become `None` and `json.dumps(model.wire(), allow_nan=False)` succeeds; non-nullable → `ValidationError` whose message names the field and does not contain `nan`/`inf` as the input value. `wire()`, `model_dump_json()` and `to_plain_text()` agree (no literal `nan`/`inf` in text).
  - AC: The existing MarketBriefing-family behaviour (GH-95) is unchanged unless it conflicts with the ruling; if it does, say so in the CHANGELOG.
  - AC: CHANGELOG `[Unreleased]` entry under Fixed, noting that a non-nullable non-finite value now fails tool output (it previously produced invalid JSON).
  - GH: https://github.com/wailuen/a2a-sdk/issues/173
  - SI: SI-2  # New validation error paths on tool output. _assert_finite (agent_sdk/models/content_types.py:275) raises f"non-finite float not allowed: {value!r}", echoing the input; ruling says never echo. pydantic's str(ValidationError) also appends 'input_value=nan' by default, so the no-nan/inf AC fails unless model_config sets hide_input_in_errors=True (or the error is raised without the input).
  - AC (SI-2): (1) change the `_assert_finite` message to name the field only, never the value; (2) set `hide_input_in_errors=True` on the `_Wire`/`ContentModel` `model_config`; (3) test `str(exc)` and the JSON-RPC / tool-error text on the wire for absence of `nan`/`inf`. The message change alters GH-95 MarketBriefing error text — add a CHANGELOG note saying so.

---

Archived 2026-10-15 by hand: the wave used all 8 phase redteam rounds; the last round had no critical/high findings. The protocol audit flagged only mediums/lows. All 14 sdk-candidates verified fixed in the tree (probes + tests in tests/test_gh173_*.py). GH-173 grew a strict JSON reader at every ingress (RFC 8259: NaN/Infinity are not JSON). Shipped in v0.13.0.
