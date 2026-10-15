# w050 — GitHub issues 174–179

Sourced from open issues on wailuen/a2a-sdk. Groups run in order G1 → G5.
Most items edit `agent_sdk/models/content_types.py`, so they are split into
separate groups; only items with disjoint code files share a group.
Target: 0.14.0 (GH-176 is a breaking boot check).

Maintainer rulings recorded before this wave ran.
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/174#issuecomment-6187888176
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/175#issuecomment-6187888514
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/176#issuecomment-6187889280
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/177#issuecomment-6187888894
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/179#issuecomment-6187889614

---

- [ ] `GH-174` Column headers and metric labels keep ASCII brackets ‖ group:G1
  - Creates: (modifies `agent_sdk/common/redact.py`, `agent_sdk/models/content_types.py`, `tests/test_content_types.py`, new `tests/test_gh174_label_ascii.py`, `docs/content-types.md`, `CHANGELOG.md`)
  - Reads: `tests/test_gh156_mcp_text_ids.py`
  - Severity: low
  - Root cause: `ColumnDef.label` and `MetricItem.label` go through `safe_cell_text`, which swaps `( ) , :` etc. for full-width look-alikes, so author-written labels like `IRR (%)` render as `IRR （%）` in every text fallback.
  - Ruling (issue 174 comment 6187888176, amends the GH-167 ruling for author-written labels): labels keep ASCII `( ) ,` as written. Only grammar-breaking characters are neutralised: line breaks/control characters always, `|` in a table header row, `:` in a `label: value` metric row. Cell values from data keep `safe_cell_text` unchanged.
  - AC: New helper in `agent_sdk/common/redact.py` (e.g. `safe_label_text(value, *, neutralise: str, max_len=...)`) built on the existing redact helpers (C-007); no second sanitizer.
  - AC: `ComparisonTable(title="x", columns=[ColumnDef(key="a", label="Actual (%)")], rows=[{"a": "1"}]).to_plain_text()` contains `Actual (%)`; `KpiCard(title="x", metrics=[MetricItem(label="IRR (%)", value=1)]).to_plain_text()` contains `IRR (%): 1`.
  - AC: A header label containing `|` and a metric label containing `:` or a line break cannot forge a column or a `label: value` row (tests).
  - AC: Any other card that renders an author-written label (not data) through `safe_cell_text` is listed in the CHANGELOG and moved to the helper only if it is clearly author-written; data cells are untouched.
  - AC: CHANGELOG `[Unreleased]` Fixed entry citing the ruling URL, flagged as a text-format change.
  - GH: https://github.com/wailuen/a2a-sdk/issues/174
  - Reuses: C-034  # Build safe_label_text on safe_line_text (agent_sdk/common/redact.py:184), not straight on safe_error_text/C-007. It already does the line-break/control-char collapse and keeps ( ) , as written. Add only the targeted '|' (header) or ':' (metric row) swap on top. Then G2's GH-175 cut-marker change reaches labels automatically. A label helper that calls safe_error_text(value, max_len=...) directly would cut with no marker after G2 lands, which is a second truncation rule.
  - Reuses: C-007  # For the '|' and ':' swap, reuse the look-alike map safe_cell_text already uses (_BARE_SEPARATORS / _SPACED_SEPARATORS in redact.py) for just those characters. Do not add a third translate table. Per LRN-339, test with a hostile label and search for the hostile value; do not match a line prefix.
  - SI: SI-2  # Adds a new sanitizer to agent_sdk/common/redact.py (the C-007 SI-2 module) that leaves ( ) , as written. The todo has no SI: field. The helper must still collapse every str.splitlines() break and C0/C1/DEL control character, and must cap length. Tests must show a header label with '|' cannot forge a column, and a metric label with ':' or a newline cannot forge a 'label: value' or 'id:' row (LRN-339). Data cells stay on safe_cell_text.

- [ ] `GH-178` docs: BriefingKpiItem non-finite wording; dead `_rejects_non_finite` hook ‖ group:G1
  - Creates: (modifies `docs/content-types.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/models/content_types.py`
  - Severity: medium
  - Root cause: `docs/content-types.md` ('Non-finite numbers (GH-173)') says `BriefingKpiItem` keeps rejecting in both cases; the code coerces nullable `delta` to None (CHANGELOG 0.13.0 matches the code). `_Wire._rejects_non_finite` is never set anywhere.
  - AC: Docs say `BriefingKpiItem.value` rejects a non-finite value and `delta`, like every nullable float, becomes null.
  - AC: The dead `_rejects_non_finite` hook is handled in GH-179's group (G5) since it is in `content_types.py`: remove it there, or keep it with a test. This todo only edits docs.
  - AC: CHANGELOG `[Unreleased]` Fixed entry.
  - GH: https://github.com/wailuen/a2a-sdk/issues/178

- [ ] `GH-175` Cut standalone slots show '…'; titles get a 1024-char cap ‖ group:G2
  - Creates: (modifies `agent_sdk/common/redact.py`, `agent_sdk/models/content_types.py`, `tests/test_content_types.py`, new `tests/test_gh175_title_cap_marker.py`, `docs/content-types.md`, `CHANGELOG.md`, `workspace/components/README.md` (C-034 entry: cut marker and caps; C-036 entry: cross-reference))
  - Reads: `agent_sdk/routes/ag_ui.py` (`_cut_middle`, the C-036 marker this cut must not merge with)
  - Severity: medium
  - Root cause: `safe_line_text` caps every standalone slot at `LINE_TEXT_MAX_LEN` (256) by plain truncation with no marker. A warning at the end of a 297-char title was silently lost from `content[0].text`; `wire()` keeps the full title, so text and structured output disagree.
  - Ruling (issue 175 comment 6187888514): a cut slot ends with a visible `…` counted within the cap. Titles (card titles and other title/header slots) get a 1024-char cap; names and other standalone slots stay at 256. Both caps are public constants, documented in `docs/content-types.md` and on the title fields.
  - AC: `safe_line_text("A" * 300)` (name cap) returns 256 chars ending in `…`; a 1100-char card title renders 1024 chars ending in `…`; a title of 1024 or fewer chars is unchanged.
  - AC: New public constants (e.g. `TITLE_TEXT_MAX_LEN = 1024` next to `LINE_TEXT_MAX_LEN`), exported where `safe_line_text` is.
  - AC: The `safe_line_text` registry entry (C-034) in `workspace/components/README.md` is updated (no longer "no truncation marker").
  - AC: CHANGELOG `[Unreleased]` Fixed entry citing the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/175
  - Reuses: C-034  # Add the '…' marker inside safe_line_text, after the control-char collapse and strip. Do not change safe_error_text: its value[:max_len] cut runs before the collapse, and its 64-char default for log/error text (C-007) is pinned by tests/test_redact.py. Also put the GH-174 safe_label_text cap (landed in G1) through the same marker cut, so labels and titles use one rule. The AC lists only safe_line_text and titles.
  - Reuses: C-036  # C-036 truncate_middle (planned) is the counted-marker middle cut for history and tool results. The ruling here is a tail cut with a one-char '…'. Keep it a separate small helper in redact.py and add a cross-reference in the C-034/C-036 registry entries, so a later wave does not merge the two marker formats by accident.
  - SI: SI-2  # Changes truncation in the redact.py SI-2 helpers. The todo has no SI: field. Raising title caps to 1024 grows untrusted text in content[0].text. Cut after the control-char collapse, so the 1024-char budget cannot be filled with stripped characters and a line break cannot survive the cut. Do not change safe_error_text's 64-char default, which caps log and error text.

- [ ] `GH-176` register_content_type reserves the 18 Basic Catalog primitive names ‖ group:G3
  - Creates: (modifies `agent_sdk/models/content_types.py`, new `tests/test_gh176_basic_catalog_names.py`, `tests/test_gh172_component_name_rules.py`, `docs/content-types.md`, `CHANGELOG.md`, `workspace/components/README.md` (C-020 entry: `BASIC_CATALOG_COMPONENTS` placement note))
  - Reads: `agent_sdk/a2ui/catalog.py`
  - Severity: medium
  - Root cause: `register_content_type` refuses `RESERVED_COMPONENTS` and case-folded clashes (GH-172) but not the Basic Catalog primitives; `component='Card'` and `component='Text'` register and shadow the primitives on a case-sensitive client.
  - Ruling (issue 176 comment 6187889280): same rule as GH-172 — refuse to boot on a name equal to a primitive ignoring case; error names the card and the clash.
  - AC: New `BASIC_CATALOG_COMPONENTS` (Text, Card, Column, Row, List, Tabs, Button, Image, Icon, Video, AudioPlayer, Divider, Modal, CheckBox, TextField, DateTimeInput, ChoicePicker, Slider) included in the reserved check with casefold comparison.
  - AC: Also fix the check order (GH-179 item 4): the `isinstance(component, str)` + PascalCase regex check runs before any `.casefold()`, so `component=5` raises the documented `ValueError`, and a snake_case name gets the PascalCase message.
  - AC: Tests: `Card`, `Text`, `Textfield`, `checkbox` refused; `component=5` gives ValueError; valid names still register.
  - AC: CHANGELOG `[Unreleased]` Breaking entry citing the ruling URL with a **Migration** line.
  - GH: https://github.com/wailuen/a2a-sdk/issues/176
  - Reuses: C-021  # BASIC_CATALOG_COMPONENTS is profile/catalog data. Define it next to the A2UI catalog (agent_sdk/a2ui/catalog.py, or the planned C-021 agent_sdk/a2ui/profile.py) and import it into content_types.py. Today the 18 names exist only in .claude/agents/a2ui-advisor.md and harness/agents/a2ui-advisor.md. Extend the existing GH-172 casefold loop at content_types.py:1440-1446 over RESERVED_COMPONENTS + BASIC_CATALOG_COMPONENTS. Do not add a second loop. Also move the isinstance/_COMPONENT_NAME_RE check (now at line 1452) above the 'component in RESERVED_COMPONENTS' check at line 1416 and the casefold.

- [ ] `GH-177` DocumentList emits only contract keys (plus documented modified_by) ‖ group:G4
  - Creates: (modifies `agent_sdk/models/content_types.py`, `agent_sdk/a2ui/catalog.py`, `agent_sdk/console/static/a2ui.js`, `tests/test_content_types.py`, `tests/test_a2ui_wire.py`, new `tests/test_gh177_document_contract_keys.py`, `docs/content-types.md`, `CHANGELOG.md`)
  - Reads: `tests/_compact_schema.py`
  - Severity: medium
  - Root cause: `_COMPACT_SCHEMAS['DocumentList']` and `DocumentItem` teach and emit `web_url`, `last_modified`, `modified_by`; the frozen Profile v1.1 `DocumentItem` contract is `id, name, type, modified, link, size`. `web_url` duplicates `link`, `last_modified` duplicates `modified`, so a contract-following renderer shows blanks.
  - Ruling (issue 177 comment 6187888894): keep all three fields on the model (tools can set and read them; a downstream agent reads `last_modified`). On the wire: fill `link` from `web_url` and `modified` from `last_modified` when the contract key is empty; do NOT emit `web_url`/`last_modified`. `modified_by` stays on the wire as a documented SDK extension but is not taught in the compact schema. Compact schema teaches contract keys only.
  - AC: `DocumentItem(id="1", name="n", web_url="u", last_modified="d", modified_by="m").wire()` == `{"id","name","link":"u","modified":"d","modified_by":"m", ...}` with no `web_url`/`last_modified`; contract keys set explicitly win over the aliases. Attribute access `doc.last_modified` still works.
  - AC: The plain-text fallback still shows the modified date and `modified_by` as today.
  - AC: The console renderer (`a2ui.js`) reads `modified`/`link` (keeping a fallback to the old keys is fine).
  - AC: Test pins the emitted key set; uses the shared parser in `tests/_compact_schema.py` (C-020) for the schema check.
  - AC: CHANGELOG `[Unreleased]` entry citing the ruling URL (wire change: two keys no longer emitted; not breaking for model users).
  - GH: https://github.com/wailuen/a2a-sdk/issues/177
  - Reuses: C-020  # Already cited: use tests/_compact_schema.py (parse_schema / required_paths / emitted_paths / top_level_keys) for the key-set pin. Do not write a new schema parser in tests/test_gh177_document_contract_keys.py.
  - SI: console-href  # The AC has a2ui.js read 'link'. Today renderDocumentList (a2ui.js:867-885) renders no anchor. If the change turns link into an <a href>, it is a model-controlled URL in the admin console. Allow only http/https schemes (no javascript:/data:), and render through el() text nodes only, never innerHTML.

- [ ] `GH-179` Low-severity A2UI conformance drift (9 items) ‖ group:G5
  - Creates: (modifies `agent_sdk/models/content_types.py`, `agent_sdk/a2ui/catalog.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py` (`_validate_a2ui_wire` accepts a str from MarketBriefing), `agent_sdk/routes/ag_ui.py` (AGENT_ARTIFACT data shape), `agent_sdk/common/json_strict.py` (new `dumps_strict`), `agent_sdk/common/sse.py` (`sse_data` uses it), `agent_sdk/routes/mcp.py` (`_is_writable` and the legacy SSE queue write use it), `tests/test_content_types.py`, `tests/test_a2ui_wire.py`, `tests/test_gh171_fallback_schema_required.py` (KpiCard compact-schema pin follows item 2), new `tests/test_gh179_conformance_drift.py`, `docs/content-types.md`, `CHANGELOG.md`, `uv.lock` (package version resync to 0.13.0; no dependency change), `workspace/components/README.md` (C-038 entry: `_rejects_non_finite` opt-out removed))
  - Modifies: (fix rounds w050 RT-001/RT-002, lone-surrogate rule) modifies `agent_sdk/common/json_strict.py` (`loads_strict` refuses lone surrogates, which also changes `POST /oauth/register` in `agent_sdk/routes/oauth.py` to 400 `invalid_client_metadata` with no code change there; new `scrub_unencodable`), `agent_sdk/agent/runner.py` (`_agent_message` and `set_task_status` scrub stored text), `agent_sdk/routes/a2a.py` (`_strict_json_response` scrub fallback, per-task `tasks/list` entries), `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/mcp.py`; adds `tests/test_rt001_lone_surrogate_writers.py`, `tests/test_rt_w050_lone_surrogate_state.py`
  - Reads: `agent_sdk/a2ui/translator.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/agent_card.py` (AGENT_ARTIFACT valueSchema)
  - Severity: low
  - Root cause: see the issue body; pre-existing items from the w049 protocol audit.
  - Ruling (issue 179 comment 6187889614): item 1 — keep the extra keys on the wire and document each as an SDK extension; do not remove them.
  - AC (1): EntityList `title`/`showing`, event-level `CalendarEvent.is_online`, `ColumnDef.unit`/`highlight`, `ComparisonTable.sort_by`/`sort_order` are documented as SDK extensions in docstrings and docs; wire output unchanged.
  - AC (2): Compact schemas add KpiCard `change_pct?`, TimeSeriesChart `subtitle?`, and show TimeSeries `data[].value` as nullable (`value:num|null`).
  - AC (3): `ComparisonTable.rows` and `CategoryValue.metadata` non-finite values follow the GH-173 rule so `wire()` and `to_plain_text()` agree (no literal `nan`/`inf` in text).
  - AC (4): Done in GH-176 (G3); verify only.
  - AC (5): `MarketBriefing.wire()` returns `to_markdown()`; the translator special case keeps working; test.
  - AC (6): Few-shot examples in `catalog.py` show only the resolved data object (no sibling `component` key) or are labelled as such.
  - AC (7): Fallback field summary renders Literal values (`"a|b"`), list element types (`[str]`) and all union arms; the legend explains `|null`.
  - AC (8): Class-keyed `functools.cache` memos in `content_types.py` become weak-keyed (like `_NEXT_BODY_TEXT`); test that a dynamic subclass can be garbage-collected.
  - AC (9): A2A non-stream responses (`message:send`, `tasks/get`) go through one strict-serialize helper; a non-finite value that bypassed validation returns a fixed -32006 error, not HTTP 500 (test).
  - AC (GH-178 code part): remove the unused `_Wire._rejects_non_finite` hook, or use and test it.
  - AC: CHANGELOG `[Unreleased]` entries per item.
  - GH: https://github.com/wailuen/a2a-sdk/issues/179
  - Reuses: C-038  # Item 3 (ComparisonTable.rows, CategoryValue.metadata non-finite): send these through the existing _assert_finite recursive check (content_types.py:250) / the C-038 _Wire hook. The same split is already used by ChartSection.data and TableSection.data. Do not add a third non-finite path. The GH-178 code part (_rejects_non_finite at content_types.py:323/330) is the C-038 opt-out flag, so update the C-038 registry entry if it is removed.
  - Reuses: C-007  # Item 9: put the strict-serialize helper in agent_sdk/common/json_strict.py next to loads_strict (e.g. dumps_strict), not privately in routes/a2a.py. Use A2A_INVALID_AGENT_RESPONSE from agent_sdk/models/errors.py, not a literal -32006. Match runner.py:458-468's existing serialize-check pattern and its fixed-text SI-2 rule. sse.py:25 and routes/mcp.py:361/1200 already call json.dumps(allow_nan=False) inline and should use the same helper (LRN-364).
  - SI: SI-2  # Item 9 changes A2A transport response writing (agent_sdk/routes/a2a.py), but the todo has no SI: field. The -32006 body must be fixed text, never str(exc) and never the offending value or key. Log only through frame_locations (no exc_info). Coverage gap (LRN-364): the AC names only message:send and tasks/get. tasks/list (a2a.py:895-915) and tasks/cancel (a2a.py:945-1044) also return Task JSON through JSONResponse and would still 500. Also message:send has three JSONResponse return sites (572, 589, 602). Every non-stream route needs the helper and a test.
  - SI: SI-5  # Item 9 edits the A2A route handlers. Keep identity: Identity = Depends(require_identity) and guard_origin on every touched route. The -32006 path must run after auth, not in a wrapper or exception handler that could answer before require_identity runs.

---

Archived 2026-10-15 by hand. The wave ended with the phase budget used up and one high (RT-001 round 8: DocumentItem serializer stripped web_url/last_modified from the model transcript fold). Fixed by hand: TRANSCRIPT_DUMP_CONTEXT, test tests/test_gh177_document_contract_keys.py::test_transcript_fold_keeps_last_modified_and_web_url. Mediums/lows deferred in workspace/todos/deferred/w050-*.md.
