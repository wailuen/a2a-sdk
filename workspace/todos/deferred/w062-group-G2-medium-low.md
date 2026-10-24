# w062 — group G2 deferred medium/low findings

- Wave: w062
- Scope: unit:G2
- Date: 2026-10-23

Non-blocking — these did not block w062's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — agent_sdk/agent/loop.py:1183
Quote: `    return _VALIDATION_TYPE_PHRASES.get(err_type, _UNKNOWN_TYPE_PHRASE)`
Description: [SDK] The new type-code allowlist is only the 24 codes in _VALIDATION_TYPE_PHRASES, so common built-in pydantic codes now render 'input failed validation' instead of the code. Verified: too_long, date_from_datetime_parsing and int_from_float all give 'tickers — input failed validation; d — input failed validation; n — input failed validation'. Before this change they showed the fixed code, which told the model how to fix its call. This quietly weakens self-correction for every tool, and the CHANGELOG 'Fixed' entry only says 'every code already in the list is unchanged'.
Fix: Add fixed phrases to _VALIDATION_TYPE_PHRASES for: too_short, too_long, date_parsing, date_from_datetime_parsing, datetime_parsing, datetime_from_date_parsing, time_parsing, url_parsing, url_type, uuid_parsing, uuid_type, int_from_float, decimal_parsing, multiple_of, union_tag_invalid, union_tag_not_found, none_required, missing_argument, tuple_type, set_type. These are fixed pydantic strings and do not widen the leak; keeps the AC (allowlist == the table). Add a test that too_long and int_from_float render a specific phrase. Name the remaining downgrade in the CHANGELOG entry.
Codify: Turning an echo fallback into an allowlist must carry over the common fixed codes the fallback used to show, or caller guidance silently gets worse.
SDK candidate: yes

## RT-002 (medium) — tests/test_gh212_id_safe_text.py:170
Quote: `        assert row.count("(id:") == 1`
Description: [SDK] The AC (SI-2, LRN-339) requires the hostile EmailList row to have 'exactly one `id:` and at most one `conversation:`'. The test checks only '(id:' and ', conversation:'. The actual row is `  2026-01-01T00:00:00Z | n@x.com | S (id: a）_（id:_b,_conversation:_c, conversation: a）_（id:_b,_conversation:_c)`, which contains 'id:' 3 times and 'conversation:' 3 times, so the AC as written fails. The ratified joined rendering keeps ':' and ',' raw, and the test was narrowed to pass. Nobody recorded that narrowing.
Fix: Do not change the joined rendering (HUMAN GATE locked it). Record the interpretation: assert row.count('(id: ') == 1 and row.count(', conversation: ') == 1 (the ASCII paren/space forms a forgery needs), state in the test docstring why bare 'id:' can repeat, and raise the AC wording on GH-212 so the plan matches what landed. Alternatively ask the maintainer whether the joined variant should also swap ':' for its look-alike.
Codify: When a ratified rendering cannot meet an AC's literal assertion, the test must say so and the AC must be amended, not silently narrowed.
SDK candidate: yes

## RT-003 (medium) — CHANGELOG.md:21
Quote: GH-212 entry (`safe_id_text` keeps `( )` and single spaces verbatim ... Changed: `agent_sdk/common/redact.py`, `agent_sdk/models/content_types.py`, `agent_sdk/__init__.py`, DESIGN.md §4.3, `workspace/components/README.md`.)
Description: [SDK] safe_id_text's output contract changed for every existing caller of agent_sdk.common.redact.safe_id_text. Downstream agents already import it: a2a-fpa src/tools/entity_lookup.py uses it, and src/common/account_labels.py:106 documents relying on 'spaces turned to underscores'. Callers that render an id joined into a row lose the forgery defence silently. No migration note. The replacement safe_joined_id_text is not exported from agent_sdk and not documented in docs/content-types.md.
Fix: Add a Migration line: callers that put a safe_id_text id inside a joined row must switch to agent_sdk.common.redact.safe_joined_id_text to keep the old look-alike rendering, and output that relied on '_' for spaces changes. Name safe_joined_id_text in docs/content-types.md 'Machine ids' (or export it from agent_sdk).
Codify: Changing the output of a sanitizer that agent repos import is a contract change: the CHANGELOG must name the replacement helper for callers who relied on the old output.
SDK candidate: yes

## RT-004 (low) — docs/content-types.md:237
Quote: `wire when false. Never join an id into a row with other fields: the SDK's two`
Description: [SDK] The doc says 'Never join an id into a row with other fields', but two lines earlier tells authors to put ids in an is_id ComparisonTable column, which IS joined into a ' | ' row. Under the relaxed alphabet a hostile is_id cell such as 'X (Revenue=99.0%)' prints a readable fake figure inside the row — the same forgery class the HUMAN GATE kept the defence against for the FundPerformance pb_id bit. The ruling covers is_id columns, so the code is correct, but neither the doc nor DESIGN.md §4.3 states the leftover risk, and the doc contradicts itself.
Fix: Reword to 'Never join an id into free text beside other fields; an is_id column is the one supported joined form', and add a sentence in docs/content-types.md and DESIGN.md §4.3 naming the leftover risk: ( ), spaces, ':' and '=' survive inside an is_id cell, while '|' is still neutralised so no extra column can be added. Do not change the code (ratified ruling).
SDK candidate: yes

## RT-005 (low) — tests/test_gh212_id_safe_text.py:161
Quote: `    row = hostile.to_plain_text().splitlines()[-1]`
Description: [SDK] The AC requires a hostile id 'cannot add a new text line or a new table column in to_plain_text() or MCP content[0].text'. For the is_id table column the test checks only to_plain_text(). The hostile ComparisonTable is not registered as a gh212_* tool, so the MCP text path is never exercised for an is_id column.
Fix: Add the hostile is_id ComparisonTable to _SAMPLES (registered as gh212_<key>) and run the line-count and ' | '-count assertions over _both(gh212_client, key), as the EntityList half already does.
SDK candidate: yes

## RT-006 (low) — tests/test_gh212_id_safe_text.py:155
Description: [SDK] The character loop at line 155 holds a literal invisible U+2028 LINE SEPARATOR, not a space, between '\x1b' and '\r'. A reader sees a space. HOSTILE_STANDALONE (line 38) contains no U+2028, NEL (\x85) or other C1 characters, so that iteration can never fail and the Unicode line-break part of the SI-2 claim goes untested.
Fix: Write the character as the escape ' ' and add ' ', '\x85' and '\x9b' to HOSTILE_STANDALONE, so the line-count and character-absence assertions really cover Unicode line breaks and C1 controls.
SDK candidate: yes

## RT-007 (low) — tests/test_gh212_id_safe_text.py:128
Quote: `async def test_entity_and_is_id_byte_exact(gh212_client) -> None:`
Description: [SDK] The AC says the byte-exact id tests (EntityList id: line, is_id column) reuse the C-031 walker _id_sample_instances/_collect_id_values. This test builds its own parallel _SAMPLES set. The is_id column is not reachable by the walker: _is_id_field excludes is_id, and ComparisonTable cells are not id fields. So ComparisonTable is_id byte-exactness lives outside the single C-031 copy.
Fix: Add a ComparisonTable sample with an is_id column holding '202601026118 (1688214-U)' to _id_sample_instances (or extend the walker to report is_id column cells as standalone id values), and drop the duplicated EntityList sample from _SAMPLES.
SDK candidate: yes

## RT-008 (low) — workspace/components/README.md:210
Quote: C-031 entry ("... the logic lives only as test-private helpers (`_id_sample_instances`, `_collect_id_values`) in `tests/test_gh156_mcp_text_ids.py` ... Not implemented.")
Description: [SDK] The C-031 entry still says the walker lives in tests/test_gh156_mcp_text_ids.py. It is defined in tests/test_content_types.py; test_gh156 only imports it. The entry also omits the new _JOINED_ID_SLOTS slot-kind map and the with_kind=True mode GH-212 added. Separately, the AC asks to update the 'C-030 row', but the registry table has no C-030 (or C-031) row, only sections (pre-existing gap, left in place).
Fix: Correct the C-031 location to tests/test_content_types.py, add one sentence on _JOINED_ID_SLOTS and _collect_id_values(with_kind=True), and add table rows for C-030 (safe_id_text + safe_joined_id_text, present) and C-031 (planned).
SDK candidate: yes

## RT-009 (low) — tests/test_gh230_safe_value_error.py:167
Quote: `def test_sdk_unknown_argument_code_keeps_its_phrase() -> None:`
Description: [SDK] This test only checks that UNKNOWN_ARGUMENT_ERROR_TYPE is a key in _VALIDATION_TYPE_PHRASES. It builds an unused model M and imports ToolInputValidationError/ToolEntry under noqa F401, but never renders an unknown_argument error through safe_validation_message. Likewise test_unknown_type_code_not_echoed (line 161) never asserts the generic 'input failed validation' phrase. A regression rendering an empty string would pass both.
Fix: Build a real unknown_argument ValidationError (via the registry's unknown-key path or InitErrorDetails with PydanticCustomError(UNKNOWN_ARGUMENT_ERROR_TYPE, ...)) and assert the rendered text contains "unknown argument (not in the tool's input schema)". Assert 'input failed validation' in the leak-code test. Delete the dead M class and the noqa imports.
SDK candidate: yes

## RT-010 (low) — agent_sdk/agent/loop.py:1181
Quote: `            if isinstance(hint, str) and hint.strip():`
Description: [SDK] The empty-message fallback checks hint.strip() on the raw text before sanitising. A message made only of control or line-break characters (e.g. '\x07' or ' ') passes the check, then safe_line_text turns it into '', so the field renders as 'ticker — ' with no phrase. That breaks the AC that a subclass with an empty message falls back to the generic phrase.
Fix: Sanitise first, then test: rendered = safe_line_text(hint); if rendered: return rendered. Otherwise fall through to the generic phrase. Add a parametrized case with message = '\x07 '.
SDK candidate: yes

## RT-011 (low) — tests/test_gh212_id_safe_text.py:145
Quote: `    assert all("is_id" not in c for c in plain.wire()["columns"])`
Description: [SDK] Lines 144 and 145 are the same assertion (copy-paste). The AC 'an existing table without is_id renders exactly as before' is checked only by the presence of fullwidth parentheses, not against the pre-GH-212 rendering, so other drift in non-id cells would go unnoticed.
Fix: Replace the duplicate line with a full-string comparison of plain.to_plain_text() against the exact expected pre-change text (header, rule and '  Acme | 202601026118 （1688214-U）').
SDK candidate: yes
