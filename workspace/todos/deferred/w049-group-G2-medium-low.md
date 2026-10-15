wave: w049
scope: group
group: G2
date: 2026-10-15

Non-blocking — these did not block w049's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G2. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/agent/runner.py
- description: The GH-173 guard only runs when a model is built, and nothing checks again at the wire. The serializability dry-run at runner.py:464 calls `json.dumps(artifact.wire(), ensure_ascii=False)` with the default `allow_nan=True`, and routes/mcp.py:1160 does the same. So a non-finite float that skips construction validation still goes out as invalid JSON `NaN`. Verified bypasses: `b=BarItem(category='x',value=1.0); b.value=float('nan'); b.wire()` -> `{'value': nan}`; `FundPerformance(irr=0.1).model_copy(update={'irr': float('nan')}).wire()` -> `{'irr': nan}`; a domain `_Wire`/ContentModel field typed `list[float]` or `dict[str, float]` -> `[nan]` / `{'a': inf}`. See also RT-005 (same root cause on the model side).
- fix: Pass `allow_nan=False` to the json.dumps dry-run in runner.py:464 (and routes/mcp.py:1160). A non-finite value that got past validation then fails the task with -32006 (the existing LRN-125 path) instead of shipping `NaN`. Add a test that mutates a BarItem after construction and asserts the task reaches FAILED. Optionally set `validate_assignment=True` on `_Wire`.
- codify: A construction-time validator is not a wire guarantee: model assignment, model_copy(update=), model_construct and container fields all skip it, so the last serializability check before the wire must use json.dumps(..., allow_nan=False).
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in two rounds. `_float_field_plan` (line 288) flattens the whole annotation tree. Two results: (a) container fields such as `list[float]`, `list[float | None] | None` and `dict[str, float]` are listed as covered, but `_finite_floats` then skips them through `isinstance(value, float)`, so their non-finite items reach `wire()`. A domain card with `values: list[float]` (a sparkline series) given `[nan, 1.0]` still returns `{'values': [nan, 1.0]}`, which `json.dumps` writes as invalid JSON, and its text fallback shows 'nan' — the GH-173 bug again. (b) 'nullable' is true if None appears anywhere in the tree, not only in the top-level union. Verified: `v: float | list[float | None]` with v=nan becomes None, which is not a valid value for that type. docs/content-types.md:101-102 says 'Your own `_Wire` models get the same rule for free'. That is false for container fields, and it points users at a private underscore class. The built-in models have no such field today, so the existing test walk passes.
- fix: Plan only fields whose top-level annotation is `float` or a Union of float with None/int/str. Take nullability from the top-level union args only. Either recurse into list/tuple/dict values with the same rule (coerce or reject element by element, following the element type's nullability) or reject non-finite items there. Change the docs to say 'ContentModel subclasses and their nested item models', and state plainly whether list/dict float containers are covered. Add a test with a domain `ContentModel` that has `list[float]`, `dict[str, float]` and `float | list[float | None]` fields.
- codify: When deriving per-field rules from a type annotation, inspect only the top-level union; flattening nested args with get_args gives false 'covered' and false 'nullable' results for container types.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/models/content_types.py (+ docs/content-types.md, CHANGELOG.md)
- description: Raised in two rounds. Free-form `dict[str, Any]` fields outside the GH-95 family still accept non-finite values, and the two halves of the dual-part artifact (structured data part and plain-text part) still disagree. `ComparisonTable(rows=[{'a': nan}])` gives `wire()` -> `{'a': null}` but `to_plain_text()` -> 'nan' (and `_body_text` renders `str(inf)` -> 'inf'). That is the same wire-vs-text disagreement GH-95 named as its reason to exist. `SeriesMeta.points` and `CategoryValue.metadata` behave the same way; `CategoryValue.metadata` is a `metadata` field yet lacks the `_metadata_finite` guard that `ContentModel.metadata` has. docs/content-types.md:96-97 says 'Built-in content models never carry nan, inf or -inf on the wire', and CHANGELOG line 13 says 'non-finite floats no longer reach wire() on built-in content models'; neither mentions these exemptions. The old `_assert_finite` docstring listed `ComparisonTable.rows` as a deliberate exception; the rewritten docstring (line 264) dropped it, so the exemption is now written down nowhere. tests/test_content_types.py:823 still asserts rows accept inf.
- fix: Either apply the rule to these free-form fields (add `_assert_finite`, or set non-finite numeric cells to None so text shows an empty cell) on `ComparisonTable.rows`, `SeriesMeta.points` and `CategoryValue.metadata` — the GH-95 criterion: a free-form dict that reaches both `wire()` and the text fallback — or keep them as an explicit exception: restore the exception note in the `_assert_finite` docstring and name these fields in both the CHANGELOG entry and docs/content-types.md.
- codify: When narrowing a guard's scope statement in a docstring or CHANGELOG, carry the previously listed exceptions forward explicitly; silently dropping them turns a documented gap into an undocumented one.
- sdkCandidate: true

### RT-004
- severity: medium
- file: CHANGELOG.md
- description: Raised in two rounds. The GH-173 entry (line 13) only describes 'every float field on every built-in model'. But `_finite_floats` and `hide_input_in_errors` sit on `_Wire`, so every downstream domain card that subclasses `ContentModel` also changes: a field `score: float` given nan now fails the tool output, and a field `score: float | None` given nan now silently becomes None. Downstream agents get no notice of this change in their own cards. The docs (line 102) refer to the private `_Wire` class rather than `ContentModel`, which is what downstream cards actually subclass. The entry also says three 'accepts non-finite outside scope' tests in tests/test_content_types.py were inverted, but four changed (metric_item, bar_item, waterfall_segment and fund_performance, the last now coercing). Separately, tests/test_gh173_non_finite_values.py:216 puts module-level imports (asyncio, agent_sdk.*) halfway down the file after test definitions (linter E402, import-not-at-top).
- fix: Extend the CHANGELOG behaviour-change note: domain `ContentModel` subclasses registered with `register_content_type` inherit the rule (non-nullable float fields reject non-finite values, nullable ones coerce to None), plus a one-line migration (return a finite value or make the field `float | None`). In the docs, say `ContentModel` subclasses rather than `_Wire`. Change 'three' to 'four'. Move the late imports to the top of tests/test_gh173_non_finite_values.py.
- sdkCandidate: true

### RT-005
- severity: low
- file: agent_sdk/models/content_types.py
- description: The guard only runs at validation time. `_Wire` does not set `validate_assignment`, so code that builds a valid model and then assigns a value bypasses it, and so do `model_copy(update=...)` and `model_construct`. Probe: `b = BarItem(category='x', value=1.0); b.value = nan; b.wire()` puts nan back, and `json.dumps(..., allow_nan=False)` fails. Tools that build a card and then patch it can still emit invalid JSON from `wire()`. Model-side counterpart of RT-001.
- fix: Either set `validate_assignment=True` on `_Wire`, after checking the cost and the effect on existing mutate-after-build code, or make `wire()` itself map non-finite floats to None as a final pass so the serialized output is always valid JSON, whatever path built the model.
- sdkCandidate: true

### RT-006
- severity: low
- file: tests/test_content_types.py
- description: The comment at lines 838-842 still says 'The sibling `*_outside_scope` tests ... are unchanged and still correct: MetricItem.value, BarItem.value, WaterfallSegment.value, ComparisonTable.rows and FundPerformance.irr are NOT scoped in'. After GH-173 that is false for every field except `ComparisonTable.rows`. `test_comparison_table_accepts_non_finite_row_value_outside_scope` (line 823) still locks in the wire-null / text-'nan' divergence and does not check either output.
- fix: Rewrite the comment to match the GH-173 ruling. Either assert the intended behaviour of the rows test for both `wire()` and `to_plain_text()`, or replace it to match whatever RT-003 decides.
- sdkCandidate: true

### RT-007
- severity: low
- file: agent_sdk/models/content_types.py
- description: `MetricItem.from_any` (around line 607) catches `(ValueError, TypeError)`, and pydantic's `ValidationError` is a subclass of `ValueError`. So `from_any('a', float('nan'))` now silently returns None and drops the metric from the card; before, it returned the item. The docstring still says it returns None only for 'non-scalar or bool' values, and the CHANGELOG does not mention this silent drop.
- fix: Update the `from_any` docstring to include non-finite numbers, add a test pinning the None return for nan/inf, and mention it in the GH-173 CHANGELOG entry.
- sdkCandidate: true

### RT-008
- severity: low
- file: tests/test_gh173_non_finite_values.py
- description: The end-to-end SI-2 test (`test_tool_error_text_has_no_non_finite_literal`, line 230) uses only the GH-95 `_assert_finite` path (a tool returning BriefingKpiItem). It never hits the new `_Wire._finite_floats` model-validator path ('BarItem.value must be a finite number'). It also reads the in-memory task store, not an actual JSON-RPC or MCP response body. AC(SI-2)(3) asks for 'the JSON-RPC / tool-error text on the wire'.
- fix: Parametrize the tool over BriefingKpiItem and a BarChart/BarItem builder. Add one case that drives the A2A JSON-RPC route (or MCP tools/call) and asserts the response body has no nan/inf literal.
- sdkCandidate: true

### RT-009
- severity: low
- file: tests/test_gh173_non_finite_values.py
- description: The test helper `_float_fields` repeats the production algorithm in `_float_field_plan` exactly: flatten get_args, then check `float in flat` and `NoneType in flat`. So the walk test shares every blind spot of the code it checks (container fields, nested-None nullability; see RT-002) and cannot catch a planning bug. The 'not a hand list' AC is met in letter only.
- fix: Derive the expected cases from an independent source, e.g. `model_json_schema()` 'number' properties with top-level null in anyOf. Add explicit shape tests: `list[float]`, `dict[str, float]`, and `float | list[float | None]` on a test-local `_Wire`.
- sdkCandidate: true

### RT-010
- severity: low
- file: agent_sdk/models/content_types.py
- description: `_float_field_plan` uses `@functools.cache` keyed on the class. This holds a strong reference to every model class ever validated, including domain or test classes created at runtime, and never releases it. The module already imports weakref for this kind of class-keyed state (DBG-7). Same finding as w049-group-G1 RT-003; fix once.
- fix: Store the plan on the class itself (computed in `__pydantic_init_subclass__` or lazily as a private ClassVar), or use a `weakref.WeakKeyDictionary` cache.
- sdkCandidate: true
