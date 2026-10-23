wave: w050
scope: group
group: G4
date: 2026-10-15

Non-blocking — these did not block w050's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G4. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.

## Findings

### RT-001
- status: card half closed by GH-219 (the agent card no longer carries `x-sdk.outputSchema`, so it cannot drift); the MCP `tools/list` outputSchema half stays open.
- severity: medium
- file: agent_sdk/models/content_types.py
- description: Raised in two rounds. The GH-177 remap is a model-wide `@model_serializer(mode='wrap')` on DocumentItem (around lines 1430-1442). It runs on every serialization, not just wire(). Verified: `DocumentItem(web_url='u', last_modified='d').model_dump()` has no web_url/last_modified, so `DocumentItem.model_validate(doc.model_dump()).last_modified is None`. model_dump() in python mode and model_dump_json() both lose the fields, although the ruling kept them on the model because a downstream agent reads last_modified. Also: `model_dump(exclude={'link'})` still emits 'link' because the serializer adds it back, and `DocumentList.model_json_schema(mode='serialization')` collapses DocumentItem to `{'type':'object','additionalProperties':true}` because the serializer is annotated `-> dict[str, Any]`. The CHANGELOG says 'Both stay readable on the model' / 'the model attributes are unchanged' and does not mention that model_dump changed.
- fix: Limit the remap to the wire path. Either override DocumentList.wire()/DocumentItem wire() to post-process each documents[i] dict, or gate the serializer on a serialization context only ContentModel.wire() passes (e.g. `model_dump(..., context={'a2ui_wire': True})` and check `info.context`). Then model_dump()/model_dump_json() keep web_url/last_modified and round-trip losslessly. Give the serializer a TypedDict return type so the serialization schema stays precise. Add tests: `model_validate(model_dump())` keeps last_modified, and `exclude={'link'}` is honoured. If model-wide behaviour is the intent, record it in the CHANGELOG Breaking entry as a model_dump change and add a round-trip test.
- codify: A wire-only key remap must not be a model-wide @model_serializer; it silently changes model_dump round-trips, exclude= handling and serialization schemas.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/agent/registry.py
- description: Raised in two rounds. `ToolEntry.output_schema()` (around line 721) returns `emits.model_json_schema()` in validation mode. For a tool that emits DocumentList, both MCP tools/list outputSchema and the agent card x-sdk.outputSchema (routes/agent_card.py:120) still advertise DocumentItem.web_url and last_modified. Verified property list: id, name, type, modified, link, size, web_url, last_modified, modified_by. After GH-177, structuredContent / wire() never carries those two keys, so the advertised schema and the emitted wire disagree — the same contract drift GH-177 set out to remove, and against the ruling that only contract keys are taught.
- fix: Hide the alias fields from the advertised JSON schema: annotate web_url/last_modified as `SkipJsonSchema[str | None]`, or add a json_schema_extra hook on DocumentItem that pops them, or build the advertised schema in serialization mode once RT-001 gives a precise serialization schema. Add a test that, for DocumentList, outputSchema DocumentItem properties equal the wire key set (contract keys plus modified_by) and exclude web_url/last_modified.
- codify: When a wire serializer drops model fields, the MCP/agent-card outputSchema derived from model_json_schema() must drop them too, or the advertised and emitted shapes drift.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/console/static/a2ui.js
- description: Raised in two rounds. The GH-177 AC says the console renderer reads modified/link. renderDocumentList (lines 867-886) only swaps the precedence of modified and last_modified (reads d.modified first) and never reads `d.link`. The CHANGELOG Breaking entry (line 13) still says 'the console renderer reads `modified`/`link`', which is false for link, so the release notes misdescribe the landed code (AC partially met). No test covers the a2ui.js change.
- fix: Option 1: render d.link as an anchor built with el() and an href attribute (never innerHTML), allow only http:/https: schemes (parse with `new URL()`; reject javascript:/data:), add rel='noopener noreferrer', per the todo's console-href SI note. Option 2: keep link unrendered and change the AC and CHANGELOG to say the renderer reads `modified` (falling back to last_modified) and does not show link. Either way, add a static test that greps a2ui.js for the new key order.
- codify: A CHANGELOG line that claims a renderer reads a key must be checked against the renderer diff before release.
- sdkCandidate: true

### RT-004
- severity: medium
- file: CHANGELOG.md
- description: The GH-177 migration note (line 13) says 'read `modified` instead of `last_modified` on the wire'. When a tool sets both fields with different meanings (the downstream ilevel get_document sets modified=periodEnd and last_modified=uploadDate), the last_modified value is now dropped from the wire with nothing carrying it, and reading `modified` returns the other date. The note does not warn about this data loss.
- fix: Add to the GH-177 Breaking entry: 'When both `modified` and `last_modified` are set, `modified` wins and the `last_modified` value is not on the wire; tools that used them for different dates must pick one or move the second into `metadata`.' Add the same sentence to docs/content-types.md §'DocumentItem wire keys'.
- codify:
- sdkCandidate: true

### RT-005
- severity: low
- file: agent_sdk/models/content_types.py
- description: DocumentList._body_text (around lines 1460-1473) changes the text fallback in two ways the CHANGELOG does not mention. (1) It adds a new '    modified by: <value>' line; the old code at HEAD never rendered modified_by, even though the AC said 'as today'. (2) When both are set, it now prefers modified over last_modified; the old code preferred last_modified. Both change content[0].text, which models and MCP clients see.
- fix: Add a text-format-change note to the GH-177 CHANGELOG entry naming the new 'modified by:' line and the modified-over-last_modified precedence (now matching wire()). Keep test_text_date_matches_wire_modified_when_both_set as the guard.
- codify:
- sdkCandidate: true

### RT-006
- severity: low
- file: docs/content-types.md
- description: Raised in two rounds. The 'SDK extensions on Profile types (GH-179)' table (around line 121) lists the EntityList, CalendarEvent, ColumnDef and ComparisonTable extensions but leaves out DocumentItem `modified_by`. That extension is only described in the separate 'DocumentItem wire keys (GH-177)' section (around line 330, after the security guidance), so the one table of SDK extensions is incomplete.
- fix: Add a row `| DocumentItem (in DocumentList) | modified_by |` to the SDK extensions table. Either move the GH-177 section next to it or cross-link the two.
- codify:
- sdkCandidate: true
