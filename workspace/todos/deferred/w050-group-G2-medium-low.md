wave: w050
scope: group
group: G2
date: 2026-10-15

Non-blocking — these did not block w050's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G2. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in two rounds. The GH-175 ruling (issue 175 comment 6187888514) says both caps are documented "in docs/content-types.md and on the title fields". Only the docs and the redact.py docstring were updated. None of the 8 title fields that now render with `max_len=TITLE_TEXT_MAX_LEN` say so: KpiCard.title (line 693), TimeSeriesChart.title (758), ComparisonTable.title (818), BarChart.title (855), EntityList.title (882), MarketBriefing.title (966), WaterfallChart.title (1022), MultiCategoryChart.title (1075). Nor do the names that keep the 256 cap. The ContentModel docstring (around line 420) still says only "caps the length", with no number. The issue reporter asked for the cap on ContentModel.title so agents can design against it.
- fix: Add a short note on each title attribute (a comment or the class docstring, not `Field(description=...)` unless verified not to change compact/fallback/JSON schema output). For example: "Text fallback caps this at TITLE_TEXT_MAX_LEN (1024) with a trailing …; wire() keeps the full value" (see RT-003 for the MarketBriefing exception). Add the matching LINE_TEXT_MAX_LEN note on the name/subject fields (EntityItem.name, UserSummary/UserProfile.display_name, DocumentItem.name, CalendarEvent.subject). Put both constants into the ContentModel docstring paragraph on delimiter safety.
- codify: When a maintainer ruling names where something must be documented ("on the title fields"), every named place is an acceptance item; check the model attributes, not only the docs page.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in two rounds. Some title slots still have no cap at all, against the ruling that titles ("card titles and other title/header slots") get a 1024-char cap with a visible '…'. (a) MarketBriefing: the KPI line "KPI {item.title}:" (line 979) and the "CHART (...): {title}" / "TABLE: {title}" section header lines (lines 986-994) are rendered with `_sanitize_cell` / `safe_cell_text`, which never cuts. Probed: a 5000-char ChartSection data['title'] renders a 5021-char line in MarketBriefing.to_markdown(), which since GH-179 (5) is also MarketBriefing.wire(). (b) EntityList._body_text (lines 892-894) fallback title, used when title is None, is `_sanitize_cell(f"{self.entity_type} list")` with no cap; a 5000-char entity_type gives a 5005-char first line (probed).
- fix: Cap these slots at TITLE_TEXT_MAX_LEN with the same '…' tail cut, then apply the separator swap (the fullwidth swap keeps length one-to-one, so the order is safe). Cleanest: a shared private `_cut_with_marker(text, max_len)` helper in redact.py, used by `safe_line_text`, plus an optional `max_len` on `safe_cell_text` or a small `safe_cell_title` wrapper. Add a test per slot.
- codify: A cap ruling scoped by slot meaning ("titles") must be applied to every rendered slot of that class, including fallback/computed headers and ones rendered through the joined-cell helper, not only the ones that already called safe_line_text.
- sdkCandidate: true

### RT-003
- severity: medium
- file: docs/content-types.md
- description: The new GH-175 docs text (line 237) says "The structured output (wire()) always keeps the full value." This is false for MarketBriefing. In the same release, GH-179 (5) made MarketBriefing.wire() return to_markdown(), which cuts the title at 1024 chars and as_of at 256, both with '…'. Probed: a 1100-char title gives a wire() first line of 1024 chars.
- fix: Change the sentence to: "wire() keeps the full value, except MarketBriefing, whose wire value is the to_markdown() text and so carries the same caps." Add a test that pins MarketBriefing's capped wire title so docs and code cannot drift apart again.
- codify: When two groups in one wave change the same contract (here, what wire() returns and how text is capped), re-check each group's docs claims against the merged code, not only against that group's own diff.
- sdkCandidate: true

### RT-004
- severity: medium
- file: tests/test_gh175_title_cap_marker.py
- description: Raised in two rounds. Only KpiCard's title is tested at 1024. Seven other call sites were switched to `max_len=TITLE_TEXT_MAX_LEN` with no test: TimeSeriesChart, ComparisonTable, BarChart, EntityList, MarketBriefing.to_markdown (also its wire() value now), WaterfallChart, MultiCategoryChart. If any drops the `max_len` argument and falls back to the 256 default, it silently cuts a 297-char title again — the exact GH-175 bug — and the suite still passes. No test runs the cap through a protocol surface either (MCP content[0].text, or the A2A TextPart the issue cites), which LRN-337 asks for when a cap is added.
- fix: Parametrize test_long_card_title_cut_with_marker, test_title_297_chars_not_cut_and_keeps_warning and test_title_at_1024_unchanged over every built-in card with a title. Build each card with minimal valid fields; assert the first line of to_plain_text() is 1024 chars ending in '…' (for MarketBriefing, also on wire()), and that a 1000-char title is unchanged. Add one MCP tools/call (or A2A) test asserting content[0].text carries the '…'-cut title. Optionally add a guard test that scans content_types.py for `_sanitize_line(self.title)` calls without `max_len=TITLE_TEXT_MAX_LEN`.
- codify: A cap applied at N call sites needs a parametrised test over all N, plus one test through the real surface where the bug was seen.
- sdkCandidate: true

### RT-005
- severity: low
- file: workspace/components/README.md
- description: Raised in two rounds. The todo's Reuses: C-036 note asked for a cross-reference between the C-034 and C-036 registry entries, so a later wave does not merge the two cut-marker formats. None was added: C-034 (lines 194-195) does not mention C-036, and C-036 (line 35 and lines 200-201) does not mention the C-034 tail cut. The C-036 entry (line 201) also still says "Head-only cuts that can drop ids are not allowed in new code." C-034's new '…' cut keeps only the start of the text, so a later review could flag it as breaking that rule or "fix" it into a C-036 middle cut. Also, the marker cut was written inline in safe_line_text, not as the small separate helper the note asked for.
- fix: Add one sentence to each entry. In C-034: "Tail cut with a one-char … (GH-175), intentionally distinct from C-036's counted middle-cut marker; do not merge." In C-036: "Does not apply to C-034 standalone display slots, which use a tail … cut by ruling GH-175." Optionally move the cut into a private `_cut_with_marker` helper in redact.py (see RT-002).
- sdkCandidate: true

### RT-006
- severity: low
- file: agent_sdk/common/redact.py
- description: Raised in two rounds. safe_line_text cuts with `text[: max_len - 1] + '…'` (line 213) after the strip, so the result can end in whitespace before the marker. Probed: `safe_line_text('A'*254 + '   BBBB')` and `safe_line_text('A'*254 + ' ' + 'B'*10)` both end in 'AA …'. Python cuts by code point, so the cut can also split a combining sequence, an emoji ZWJ sequence or a flag pair, leaving a broken glyph before the marker. The CHANGELOG GH-175 entry also does not flag this as a text-format change: every name over 256 chars now keeps 255 chars of content plus '…', where it used to keep 256 (the GH-174 entry does flag its text change).
- fix: Use `text[: max_len - len(LINE_TEXT_CUT_MARKER)].rstrip() + LINE_TEXT_CUT_MARKER`; the result stays at or under the cap. Update test_name_cap_ends_with_marker to assert `len(out) <= 256` and add a whitespace-boundary case. Optionally step back over a trailing U+200D or a lone regional indicator. Add "**Text-format change**" to the GH-175 CHANGELOG entry, noting that over-cap values lose one content character to the marker.
- sdkCandidate: true

### RT-007
- severity: low
- file: agent_sdk/__init__.py
- description: The new public names LINE_TEXT_CUT_MARKER, TITLE_TEXT_MAX_LEN and safe_label_text are reachable only from agent_sdk.common.redact (and the content_types namespace). The top-level package re-exports safe_cell_text, safe_block_text and safe_error_text (lines 23/46) but not safe_line_text, safe_label_text or the cap constants. That is uneven, even though the C-034 registry entry tells third-party ContentModel authors to import these helpers. LINE_TEXT_CUT_MARKER is also not mentioned in docs/content-types.md or the CHANGELOG.
- fix: Either re-export safe_line_text, safe_label_text, LINE_TEXT_MAX_LEN and TITLE_TEXT_MAX_LEN from agent_sdk/__init__.py next to safe_cell_text and add them to `__all__`, or state in docs/content-types.md that agent_sdk.common.redact is their only public home. Mention LINE_TEXT_CUT_MARKER in the docs paragraph on caps, or make it private (`_LINE_TEXT_CUT_MARKER`) if it is not meant to be public.
- sdkCandidate: true
