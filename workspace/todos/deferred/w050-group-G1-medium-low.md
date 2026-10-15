wave: w050
scope: group
group: G1
date: 2026-10-15

Non-blocking — these did not block w050's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/common/redact.py
- description: `safe_label_text` (line 219) caps through `safe_error_text(value, max_len=max_len)`. That is a plain slice taken BEFORE the control-char collapse and strip, with no '…' marker. `safe_line_text` (GH-175, same file) cuts after the collapse and appends a visible '…'. So labels and titles now follow two different truncation rules: a 300-char label renders 256 'x' with no marker (verified). This is the exact "second truncation rule" the todo's C-034 Reuses note warned about. `test_helper_contract` checks only `len == 256`, so it cannot detect it. See RT-008 for the matching docs/CHANGELOG gap.
- fix: Build on C-034: `text = safe_line_text(value, max_len=max_len)`, then apply the targeted translate. Add a test asserting `safe_label_text('x'*300, neutralise='|')` ends with `LINE_TEXT_CUT_MARKER` and is exactly 256 chars.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/common/redact.py
- description: Raised in two rounds. `_LABEL_LOOKALIKES` (line 216) is a new third look-alike table (`{'|':'/', ':':'：', '│':'/', '｜':'/'}`). It copies entries from `_BARE_SEPARATORS` ('|', '│', '｜') and `_SPACED_SEPARATORS` (':'), which the todo's C-007 Reuses note forbade ("Do not add a third translate table"). It is also redundant inside itself: the '│'/'｜' keys sit in the dict AND are re-added by the `if '|' in neutralise: swap.update(...)` branch (lines 233-234), so that code does nothing. If one map changes, header/metric labels and data cells will drift apart.
- fix: Derive the swap from the existing maps: for '|', take the `_BARE_SEPARATORS` entries for '|', '│' and '｜'; for ':', take `_SPACED_SEPARATORS[':']`. Delete `_LABEL_LOOKALIKES` and the duplicate update branch.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/common/redact.py
- description: Raised in four rounds. `safe_label_text` is public and documented (docs/content-types.md:222: "swaps only the characters you name"), yet it does not handle a `neutralise` character other than '|' or ':'. Rounds disagree on the exact failure: three rounds verified a bare `KeyError` (`safe_label_text('a,b', neutralise=',')` -> KeyError ','; `neutralise='('` -> KeyError '('); one round reported the label coming back unchanged with no error (`safe_label_text('a,b(c)', neutralise=',')` -> 'a,b(c)'), which fails open for a security helper. Either way, a third-party ContentModel author who follows the docs gets an unexplained crash inside `to_plain_text()` or silently unprotected text. The failure mode should be re-verified against the final code.
- fix: Type the parameter as `neutralise: Literal['|', ':', '|:', '']` or validate it up front. Raise `ValueError` naming the supported characters for anything else. State the supported set in the docstring and in docs/content-types.md. Add a test for the error.
- sdkCandidate: true

### RT-004
- severity: medium
- file: agent_sdk/common/redact.py
- description: `safe_label_text(neutralise=':')` swaps every ':', including digit-flanked ones that `safe_cell_text` (the GH-130 rule) leaves alone. Verified: MetricItem labels 'Ratio 3:1' and 'Open 09:30' rendered as written before GH-174, but now render 'Ratio 3：1' and 'Open 09：30'. A fix meant to keep author labels as typed makes these labels worse, and the CHANGELOG text-format note does not mention it.
- fix: For ':', reuse `_SPACED_SEPARATOR_DIGIT_RE` semantics (keep digit-flanked ':'), as `safe_cell_text` does. Add a test that 'Ratio 3:1' renders unchanged and that 'a: 1' still cannot forge a row.
- sdkCandidate: true

### RT-005
- severity: medium
- file: tests/test_gh174_label_ascii.py
- description: Raised in four rounds. `test_metric_label_line_break_cannot_forge_row` (lines 36-39) checks only that no line starts with '  forged'. LRN-339 and the todo's SI-2 note ban this line-prefix check: forgery tests must search for the hostile value. The test would also pass if ':' were never swapped, because the collapse alone keeps the text off column 2, or if the indent changed. `test_metric_label_colon_cannot_forge_row` counts colons in one row instead of asserting the hostile 'a: 1' pair is absent. Coverage gaps: no test for the header look-alikes '│'/'｜' (which the helper swaps), no test for a line break, U+2028 or C1 characters such as NEL (0x85) in a `ColumnDef.label` or metric label, no test that a header label keeps ':' and ',' as written, and no cut-marker test.
- fix: Assert the hostile value is absent from the whole render: `assert 'forged: 9' not in card.to_plain_text()`, `assert 'a: 1' not in text`, and exactly one ': ' separator per metric row. Add header cases for 'A | B', 'A │ B' and 'A ｜ B' (header still has exactly len(columns)-1 ' | ' joins; assert 'A | B' not in text) and for 'Net, gross: x' kept verbatim. Add `ColumnDef.label` / metric label cases with '\n', U+2028 and '\x85' (header stays one line; hostile value never starts a line). Add the marker test once RT-001 is fixed.
- codify: LRN-339 applies to every new label or slot sanitizer: a forgery test must search the full render for the hostile value, not match a line prefix, and must cover every look-alike the helper claims to swap.
- sdkCandidate: true

### RT-006
- severity: medium
- file: workspace/components/README.md
- description: Raised in four rounds. The new public, reusable helper `agent_sdk.common.redact.safe_label_text` (redact.py:219; documented for third-party ContentModel authors in docs/content-types.md:220-225) is not in the component registry. The C-034 entry (line 33 and lines 194-195) was edited for GH-175 but does not name its new sibling; grep for 'label' in the registry finds nothing. So the safe_cell_text / safe_line_text / safe_id_text pairing guidance stays incomplete, and a later wave or agent repo may re-roll a label sanitizer (Dimension 8: unregistered reusable utility).
- fix: Add `safe_label_text` to the C-034 entry as a sibling (or register a new C-NNN) with a registry row and detail entry: signature `(value, *, neutralise, max_len=LINE_TEXT_MAX_LEN)`; built on `safe_line_text` (same cap and '…' marker) plus a targeted '|' or ':' swap from the C-007 maps (`_BARE_SEPARATORS` / `_SPACED_SEPARATORS`); keeps ( ) , as written; for author-written header/metric labels only, data stays on `safe_cell_text`. Put it in the pairing table next to `safe_cell_text`, `safe_line_text` and `safe_id_text`.
- codify: Every new public helper in agent_sdk/common/redact.py must be registered in workspace/components/README.md in the same wave, or the next wave adds a duplicate sanitizer.
- sdkCandidate: true

### RT-007
- severity: medium
- file: CHANGELOG.md (+ agent_sdk/models/content_types.py)
- description: Raised in three rounds. GH-174 AC4 is only partly met. The AC asks the CHANGELOG to list every other author-written label still rendered through `safe_cell_text`. The list (line 20: WaterfallSegment.label, BriefingKpiItem.title, MetricItem.unit, BarItem.category, MarketBriefing chart/table titles) leaves out `KpiTrend.period` (content_types.py:711), `BriefingKpiItem.unit` (content_types.py:981), the MultiCategoryChart category keys (`_sanitize_cell(k)` at content_types.py:1090, author-chosen series names like 'Equity (EU)') and period labels (content_types.py:1092), and the EntityList fallback title `_sanitize_cell(f"{self.entity_type} list")` (content_types.py:893), so `entity_type="deal (EU)"` still renders `deal （EU） list`. It also leaves `MetricItem.unit` (content_types.py:701) on `safe_cell_text`, although a unit is clearly author-written, against the AC's "moved to the helper only if it is clearly author-written" rule. The same KpiCard row still renders 'IRR (%): 1 USD （m）', so the GH-174 symptom is only half fixed in that row.
- fix: Move `MetricItem.unit` and `BriefingKpiItem.unit` (and `KpiTrend.period` if judged author-written) to `safe_label_text(..., neutralise=':')`; consider moving the EntityList fallback title to `safe_line_text` with `TITLE_TEXT_MAX_LEN`, since it is a standalone title slot. Otherwise add a sentence to the CHANGELOG saying why each is not clearly author-written. Either way, add `KpiTrend.period`, `BriefingKpiItem.unit`, the MultiCategoryChart category keys/period labels and the EntityList `entity_type` fallback title to the "NOT moved" list.
- codify: When an AC asks to audit every call site of a pattern, grep every call to the old helper and account for each hit in the CHANGELOG. Do not list only the ones that come to mind.
- sdkCandidate: true

### RT-008
- severity: low
- file: docs/content-types.md (+ CHANGELOG.md)
- description: Raised in two rounds. `ColumnDef.label` and `MetricItem.label` used to render full length (`safe_cell_text` has no cap). They now get a 256-char cap through `safe_label_text`. Neither the GH-174 CHANGELOG entry nor the "Author-written labels (GH-174)" paragraph in docs/content-types.md says so, or how a cut looks. The next docs paragraph says cut standalone values end in '…', so readers will assume labels do too, which is false today (see RT-001).
- fix: After RT-001 is fixed, add one sentence to the GH-174 CHANGELOG entry and to the docs section: labels share `safe_line_text`'s cap (`LINE_TEXT_MAX_LEN`, 256) and visible '…' marker; mention the `max_len` parameter.
- sdkCandidate: true

### RT-009
- severity: low
- file: tests/test_rt003_super_to_plain_text_no_recursion.py
- description: Raised in two rounds. The GH-174 todo lists this file under Creates/Modifies, but it is unchanged in the working tree. Either the todo's file list is stale or a planned assertion update was skipped. The file uses MetricItem labels with no separators, so it passes either way and gives GH-174 no coverage.
- fix: Confirm no change is needed and drop it from the todo's Modifies list (or note that it needed no change). Or add the intended assertion, e.g. that a subclass's `super()._body_text()` path renders a label like 'IRR (%)' unchanged.
- sdkCandidate: true
