# w048 — GitHub issue 170

Sourced from open issues on wailuen/a2a-sdk. One item.
Run in parallel (group:G1).
Target: 0.12.1.

Maintainer ruling recorded before this wave ran.
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/170#issuecomment-6143894937

---

- [ ] `GH-170` A2UI: CalendarEvent.location display_name and is_online must always be emitted (Standard Profile v1.1) ‖ group:G1
  - Creates: (modifies `agent_sdk/models/content_types.py`, `agent_sdk/a2ui/catalog.py`, `tests/test_content_types.py`, `tests/test_a2ui_wire.py`, new `tests/test_gh170_profile_required_keys.py`, `docs/content-types.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/console/static/a2ui.js`, `.claude/agents/a2ui-advisor.md`
  - Severity: high
  - Root cause: Standard Profile v1.1 defines `CalendarEvent.location` as `{display_name, is_online, join_url?}`. `EventLocation` declares `display_name` and `is_online` as `| None = None`, and `wire()` uses exclude_none, so `EventLocation(join_url='u')` emits `{"join_url": "u"}`, which fails the Profile's required-key check. The compact schema in `catalog.py:229` teaches `location?:{display_name?,is_online?,join_url?}`.
  - Ruling (issue 170 comment 6143894937): fix by defaults, NOT by making the fields required. Input that omits them must stay valid.
  - AC: `EventLocation.display_name: str = ""` and `is_online: bool = False`; `join_url` stays optional. `EventLocation(join_url='u').wire()` (and the CalendarEvents wire output) contains `display_name` and `is_online`. `EventLocation()` with no arguments still validates.
  - AC: The `CalendarEvents` compact schema reads `location?:{display_name:str,is_online:bool,join_url?:str}`.
  - AC: New `tests/test_gh170_profile_required_keys.py`: for every Standard Profile type in `_COMPACT_SCHEMAS`, compare the keys the compact schema marks required (no `?`), including nested objects, with the keys the model always emits on the wire for a minimal valid instance. The table of required keys comes from the Standard Profile v1.1 field contracts (a2ui-advisor). Test fails on any mismatch.
  - AC: If that test finds the same mismatch in other card types, fix each the same way (a non-None default so the key is always emitted, and the schema text corrected), per the ruling. List each extra type fixed in the CHANGELOG entry.
  - AC: Plain-text output of `CalendarEvents` is unchanged for an empty `display_name` (no ` @ ` with nothing after it) and for `is_online=False`.
  - AC: CHANGELOG `[Unreleased]` entry under Fixed, citing the ruling URL; note that wire output now always carries the two keys (additive, not breaking).
  - GH: https://github.com/wailuen/a2a-sdk/issues/170
  - Reuses: C-020  # The new required-key test needs a compact-schema key parser and a model wire-key walker. Both already exist as private helpers in tests/test_a2ui_wire.py: _declared_wire_keys (line 1220) and _compact_schema_top_level_keys (line 1283). Extend these to handle nested objects and both key styles (quoted "manager?" in UserProfile, unquoted location? in CalendarEvents), then import them into tests/test_gh170_profile_required_keys.py. Do not write a second parser in the new file. A second parser that copes with only one quoting style would quietly skip keys and pass when it should fail. Separate gap in the same todo: the AC covers omitted input but not an explicit None. An agent that maps upstream data with nulls, such as EventLocation(display_name=src.get('displayName')), will now get a ValidationError, because str and bool reject None. The ruling only says omitted input must stay valid. Add a mode='before' validator that turns None into the default, and add an AC and a test for EventLocation(display_name=None, is_online=None). Otherwise this patch release can break existing callers.
  - Reuses: C-021  # The AC says the required-key table 'comes from the Standard Profile v1.1 field contracts (a2ui-advisor)'. That is exactly the machine-readable contract C-021 (StandardProfileV1Contract, planned at agent_sdk/a2ui/profile.py) is meant to hold. Hard-coding the table inside a test file creates a third hand-kept copy, after .claude/agents/a2ui-advisor.md and harness/agents/a2ui-advisor.md, and the copies will drift. Either add agent_sdk/a2ui/profile.py to Creates and build the table there as the first slice of C-021, or keep the table in one shared test module and note in the CHANGELOG/registry that it seeds C-021. Do not create profile.py without declaring it, because unscoped public modules are flagged under LRN-322/LRN-202. Per the C-021 note, do not add a per-type metadata row, since Profile v1.1 treats metadata as free-form on every type. Also apply LRN-110's Check to the extended scope: required-but-nullable fields (X | None with no default) need key-present-as-null, not a non-None default.

---

Archived 2026-10-14 by hand: wave archive step skipped because the protocol audit flagged pre-existing A2UI mediums/lows only (no critical/high). Both sdk-candidates (explicit-null coercion, shared compact-schema parser) verified fixed in the tree. Shipped in v0.12.1.
