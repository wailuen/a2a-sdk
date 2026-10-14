# SDK issue candidates — w048 (2026-10-14)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: EventLocation.display_name/is_online were narrowed from `str | None`/`bool | None` to `str = ""`/`bool = False` with no None-coercion, so an explicit None now raises ValidationError. Callers that map upstream nulls (e.g. EventLocation(display_name=src.get('displayName'))) worked on 0.12.0 and break on this patch release, while the CHANGELOG calls it 'Additive, not breaking'. The required mode='before' validator and test did not land. Fix: add @field_validator("display_name", "is_online", mode="before") that maps None to the field default; add a test that EventLocation(display_name=None, is_online=None).wire() == {"display_name": "", "is_online": False} and that model_validate({"display_name": None}) succeeds; note the explicit-null behavior in docs/content-types.md and the CHANGELOG.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Rationale: content_types models are SDK internals that feed the A2UI catalog and wire output. This is a backward-compatibility break in a public SDK model that every agent using EventLocation hits, not agent-specific code.

## Candidate 2: The new test file defines its own compact-schema tokenizer and parser (_TOKEN, _parse_schema, _required_paths, _emitted_paths, lines 52-130). The todo's `Reuses: C-020` directive said to extend and import the existing helpers in tests/test_a2ui_wire.py (_declared_wire_keys, _compact_schema_top_level_keys). tests/test_a2ui_wire.py and tests/test_content_types.py are listed under Modifies, but the original finding said git diff showed both unchanged. The repo now has two compact-schema parsers that can drift apart. Fix: put the nested-aware parser in a shared tests/_compact_schema.py, replace _compact_schema_top_level_keys with it, and import it from both test files. Otherwise, drop the unchanged files from Modifies and record why C-020 reuse was skipped.
- Severity: high
- Component: protocol/a2ui
- File: tests/test_gh170_profile_required_keys.py
- Rationale: These are the SDK's own A2UI wire and catalog conformance tests, not an agent's tests. Two different parsers for the same schema can make the A2UI profile checks disagree without anyone noticing. Note: the working tree now has an untracked tests/_compact_schema.py and a modified tests/test_a2ui_wire.py, so a fix may already be underway. Verify against the current tree before filing.
