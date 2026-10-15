wave: w049
scope: group
group: G1
date: 2026-10-15

Non-blocking — these did not block w049's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in two rounds (GH-172). `register_content_type` calls `component.casefold()` (line 1406) before the `isinstance(component, str)` guard (line 1420), so the guard is unreachable dead code. A domain card with a truthy non-string component (e.g. `component = 123` with its own catalog_id) crashes boot with a bare `AttributeError: 'int' object has no attribute 'casefold'` instead of the documented ValueError naming the card. Confirmed by a live check.
- fix: Move the `isinstance(component, str)` + `_COMPONENT_NAME_RE.fullmatch` check to just after the `if not data_type or not component` presence check, before the RESERVED and case-fold loops. Raise TypeError or ValueError naming the component. Add a test row for a non-str component in tests/test_gh172_component_name_rules.py.
- codify: Type guards must come before the first method call that assumes the type; a guard placed after it is dead code.
- sdkCandidate: true

### RT-002
- severity: medium
- file: harness/skills/add-tool/SKILL.md
- description: GH-172 adds a breaking boot check (component must be PascalCase and unique ignoring case), but the authoring material that teaches downstream agents does not mention it. harness/skills/add-tool/SKILL.md:92-94 (and its byte-identical mirror template/.claude/skills/add-tool/SKILL.md) and DESIGN.md:231 still describe only exact-name uniqueness and the four RESERVED names. Only docs/content-types.md was updated. Agents learn the SDK only through skills, so an agent following the skill can still pick `my_card` or `KPICard` and fail at boot.
- fix: Add one sentence to harness/skills/add-tool/SKILL.md, template/.claude/skills/add-tool/SKILL.md and DESIGN.md §4.5 (line 231): the component must match `^[A-Z][A-Za-z0-9]*$` and must not equal a reserved or registered name ignoring case (KPICard next to KpiCard is refused at boot). Either declare these files in the G1 todo or open a follow-up.
- codify: A new boot-time validation rule must land in every teaching surface (DESIGN.md, the add-tool skill and its template mirror), not only in docs/.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/models/content_types.py
- description: `_float_field_plan` (line 287, GH-173 code) is wrapped in `@functools.cache` keyed by class. That strongly pins every _Wire/ContentModel subclass ever validated, including cards built dynamically per test or by a factory. This is exactly the leak DBG-7 fixed in the same module by switching to a WeakKeyDictionary.
- fix: Cache the plan in a `weakref.WeakKeyDictionary` keyed by class, as the DBG-7 re-entrancy table does, or compute it once in `__pydantic_init_subclass__` and store it on the class.
- codify: Per-class caches in content_types.py must be weak-keyed (DBG-7); functools.cache on a class argument pins it for the life of the process.
- sdkCandidate: true

### RT-004
- severity: medium
- file: tests/test_a2ui_wire.py
- description: Raised in two rounds (Dimension 5, file-list drift). The GH-171 todo lists tests/test_a2ui_wire.py in Creates/Modifies, but git shows it unchanged; the GH-171 tests went into the new tests/test_gh171_fallback_schema_required.py instead. This trips the LRN-322 scope audit. Also, the AC "a domain card with many fields keeps every required field in the prompt section" is only tested against the private `_field_summary()`, never against `get_system_prompt_section()`, which is the surface the model actually sees.
- fix: Add a test in tests/test_a2ui_wire.py that registers a many-field domain card (cleanup in finally), calls `get_system_prompt_section()`, pulls that card's line, and asserts via `parse_schema`/`required_paths` that every required field is present and '...' marks the drop. Or remove tests/test_a2ui_wire.py from the GH-171 Creates/Modifies line in workspace/todos/active/w049-gh-issues.md with a stated reason.
- sdkCandidate: true

### RT-005
- severity: low
- file: agent_sdk/a2ui/catalog.py
- description: Raised in two rounds. `_annotation_str` (catalog.py:63-83) renders only the first non-None union member, so `Union[int, str, None]` / `int | str | None` is taught to the model as `int|null`, dropping `str` — a narrower type than the field accepts. The function was rewritten in this change to add `|null` but still mis-teaches multi-member unions. It also still returns a `(type, required)` tuple, but `required` is passed through unchanged, so the second element does nothing.
- fix: Return only the type string and have `_field_summary` keep `required = info.is_required()`. Render every non-None member joined by '|' plus '|null' when None is present (e.g. `int|str|null`). Add a test case.
- sdkCandidate: true

### RT-006
- severity: low
- file: agent_sdk/models/content_types.py
- description: `register_content_type` docstring (lines 1374-1375) still says it "Validates the frozen-name and uniqueness rules" and does not mention the new GH-172 PascalCase and case-insensitive clash rules that now fail boot.
- fix: Extend the docstring to list the PascalCase regex and the case-insensitive reserved/registered clash rule.
- sdkCandidate: true

### RT-007
- severity: low
- file: tests/test_gh171_fallback_schema_required.py
- description: The GH-171 tests never reach the branch where required fields alone exceed the 250-character budget (the `else: break` at agent_sdk/a2ui/catalog.py:156-163). In `_Gh171Many` the required fields are short, so the AC "never drops a required field" is only proven when optional fields are enough to fit. They also test only the native `X | None` form, not `typing.Optional`/`Union`, which this change merged into one branch. A live check showed both work today, but nothing guards against a regression.
- fix: Add a card whose required fields alone exceed 250 chars (e.g. 20 long required names plus optionals). Assert every required name is in `required_paths(parse_schema(summary))`, no optional survives, and '...' is present. Add one `Optional[int]` (no default) field and assert it renders `int|null` with no '?'.
- sdkCandidate: true

### RT-008
- severity: low
- file: tests/test_gh171_fallback_schema_required.py
- description: The AC says built-in `_COMPACT_SCHEMAS` stay unchanged, but `test_builtin_compact_schemas_unchanged` pins only the KpiCard entry, so a change to any of the other 13 hand-written entries passes. The diff shows no change to the dict today, so this is weak coverage, not a defect.
- fix: Snapshot-compare the whole `_COMPACT_SCHEMAS` dict (or its hash) against a frozen copy, or drop the test and rely on existing RT-007/RT-008 coverage in tests/test_a2ui_wire.py.
- sdkCandidate: true

### RT-009
- severity: low
- file: CHANGELOG.md
- description: LRN-212 check. CHANGELOG [Unreleased] now has a Breaking changes entry (GH-172), but pyproject.toml is still 0.12.1 and both GH-171 and GH-172 are still `- [ ]` in workspace/todos/active/w049-gh-issues.md. Expected mid-wave, but the release must handle it.
- fix: At release, bump pyproject.toml to 0.13.0 (minor bump for the breaking boot check, not bump-patch) and mark GH-171/GH-172 done in the same commit as the CHANGELOG heading.
- sdkCandidate: true
