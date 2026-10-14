wave: w048
scope: group
group: G1
date: 2026-10-14

Non-blocking — these did not block w048's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- severity: medium
- file: tests/test_gh170_profile_required_keys.py
- description: Raised in two rounds. The required-key table claims MultiCategoryChart requires literal keys `periods[].categories.name`, `periods[].categories.name.value`, `summary.by_category.name` and `summary.by_category.name.value`. In the Profile, `name` is a placeholder for a map key: `categories {[name]: {value, count?}}`. `_required_paths` parses the placeholder as a literal required key, and the test only passes because `_minimal_instances()` uses a category literally called "name". A real instance (for example `{"Equity": ...}`) would fail the "always emits required keys" check. The gate passes because the test data was built to fit it.
- fix: Treat map placeholders as wildcards. In tests/_compact_schema.py, have `parse_schema`/`required_paths` mark the dynamic-key objects under `categories` and `by_category` as `*`, and have `emitted_paths` collapse dict-valued map keys to `*` for those paths. Change the table to `periods[].categories.*.value` and `summary.by_category.*.value`, and build the minimal instance with a realistic category name such as "Equity".
- codify: A test that checks keys against a contract must use realistic map keys. Building the instance so a placeholder key matches literally makes the test pass by design.
- sdkCandidate: true

### RT-002
- severity: medium
- file: tests/test_gh170_profile_required_keys.py
- description: Raised in two rounds. `test_table_covers_every_frozen_object_profile_type` (line 257) only checks `set(_PROFILE_REQUIRED) <= set(_COMPACT_SCHEMAS)`. It does not check that every object-shaped Standard Profile entry in `_COMPACT_SCHEMAS` appears in the table. A new Profile type added to `_COMPACT_SCHEMAS` without a table row gets no required-key check and the suite still passes. That falls short of the AC: "for every Standard Profile type in _COMPACT_SCHEMAS".
- fix: Assert `set(_PROFILE_REQUIRED) == {k for k, v in _COMPACT_SCHEMAS.items() if v.startswith('{')}` (equivalently `set(_COMPACT_SCHEMAS) - {"MarketBriefing"} == set(_PROFILE_REQUIRED)`), so only the MarketBriefing prose entry is excluded, by name. `_COMPACT_SCHEMAS` is never changed at runtime (catalog.py:270 only reads it), so the equality is stable.
- codify: A coverage table must be checked with equality against its source set. A subset check lets new entries skip the gate.
- sdkCandidate: true

### RT-003
- severity: medium
- file: tests/test_gh170_profile_required_keys.py
- description: Raised in two rounds. The todo's `Reuses: C-021` note was not followed. It asked for one of two things: build the Profile required-key table as the first slice of agent_sdk/a2ui/profile.py, or keep it in a shared test module and record in the CHANGELOG/registry that it seeds C-021. Instead `_PROFILE_REQUIRED` (lines 137-196) is hard-coded inside the GH-170 test file. That makes a third hand-kept copy of the Standard Profile v1.1 field contracts, after .claude/agents/a2ui-advisor.md and harness/agents/a2ui-advisor.md (plus template mirrors). Neither CHANGELOG.md nor workspace/components/README.md mentions it; the C-021 row (line 153) still says profile.py does not exist and names no seed.
- fix: Move `_PROFILE_REQUIRED` into a shared test module, for example tests/_profile_contract.py next to tests/_compact_schema.py, that the future agent_sdk/a2ui/profile.py will replace. Add a sentence to the C-021 entry in workspace/components/README.md naming that table as the seed for StandardProfileV1Contract, to be derived from it once profile.py exists. Add a matching note to the CHANGELOG entry.
- codify: When a Reuses note names a planned component, the landed code must either start that component or record where its seed lives. A silent third copy of a contract is drift.
- sdkCandidate: true

### RT-004
- severity: medium
- file: workspace/components/README.md
- description: The C-020 registry entry (line 151) still says the guard lives in private helpers `_declared_wire_keys` and `_compact_schema_top_level_keys` in tests/test_a2ui_wire.py. This wave deleted `_compact_schema_top_level_keys` and moved the parser to the new tests/_compact_schema.py (`parse_schema`, `required_paths`, `emitted_paths`, `top_level_keys`). The registry now points at a symbol that no longer exists.
- fix: Update the C-020 entry to name tests/_compact_schema.py and its four functions as the current shared parser. Note that it now handles nested objects and both quoted and unquoted key styles.
- codify: When a refactor moves or deletes a helper that a component registry entry names, update the registry in the same change.
- sdkCandidate: true

### RT-005
- severity: low
- file: tests/test_gh170_profile_required_keys.py
- description: The "always emits" check runs only on fully populated instances. TimeSeriesDataPoint uses value=1.0, so a regression of the required-but-nullable `value: null` re-insertion (LRN-110) would not be caught here.
- fix: Add a second TimeSeriesChart instance with value=None and assert `data[].value` is still emitted.
- sdkCandidate: true

### RT-006
- severity: low
- file: agent_sdk/models/content_types.py
- description: The `mode='before'` validator on EventLocation only runs when the model is built. `_Wire` does not set `validate_assignment`. So `loc.display_name = None` after construction is stored as-is, and `wire()` (exclude_none) drops the key again. Checked: `EventLocation(display_name='x')` followed by `.display_name = None` gives `.wire() == {'is_online': False}`, which brings the GH-170 Profile violation back for agents that fill fields after construction.
- fix: Add `model_config = ConfigDict(populate_by_name=True, validate_assignment=True)` to EventLocation so the None-to-default validator also runs on assignment. Add a test that assigns None after construction.
- sdkCandidate: true

### RT-007
- severity: low
- file: agent_sdk/models/content_types.py
- description: `_none_means_default(cls, v: Any, info: Any)` types the validation info as `Any` instead of pydantic's `ValidationInfo`, so mypy cannot check `info.field_name`. The CHANGELOG also says the change is "not breaking", but the Python attribute types narrow from `str | None` / `bool | None` to `str` / `bool`. Caller code that tests `loc.is_online is None` to mean "unknown" now silently sees False.
- fix: Import `ValidationInfo` from pydantic and annotate `info: ValidationInfo`. In the CHANGELOG entry, add one sentence saying the Python attributes are no longer None-able, so `is None` checks on `display_name` and `is_online` must become falsy checks.
- sdkCandidate: true

### RT-008
- severity: low
- file: tests/test_gh170_profile_required_keys.py
- description: Several test-hygiene problems. (a) tests/_compact_schema.py was created but is not in the todo's Creates list, and tests/test_content_types.py is listed but was never changed. (b) The imports are out of order: `BarItem` sits at the end of the import list, and both test_gh170 and test_a2ui_wire.py import `tests._compact_schema` before `agent_sdk`. (c) `EmailMessage(..., **{"from": _NE}, ...)` causes 4 mypy arg-type errors on this file, though `populate_by_name=True` would accept `from_=_NE`.
- fix: Add tests/_compact_schema.py to the todo's Creates line and drop the unchanged tests/test_content_types.py, or add a CalendarEvents location case there. Sort the imports. Replace `**{"from": _NE}` with `from_=_NE`.
- sdkCandidate: true
