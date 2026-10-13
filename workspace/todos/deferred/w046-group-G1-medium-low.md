wave: w046
group: G1
date: 2026-10-13
status: non-blocking (medium/low)

Non-blocking — these did not block w046's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every unit redteam round for group G1 and deduped by file+description. Redteam IDs restart each round, so each heading carries its round label (R1..R3, in the order the rounds ran). Many findings recur across rounds with different wording. They are kept separately because their descriptions differ; the theme index below groups them. All are flagged sdkCandidate except R1 RT-012, R2 RT-009 and R2 RT-010.

## Theme index

1. MCP `tools/call` `content[0].text` id assertions cover only EntityList/DocumentList; EmailList, CalendarEvents, UserList, UserProfile (and FundPerformance) untested over MCP (GH-156 AC): R1 RT-004, R2 RT-007, R3 RT-002
2. Registry-wide id meta-test takes expected ids from sample values, not the schema; a new optional `*_id` field left unset slips past (LRN-241 drift): R1 RT-005, R2 RT-004, R3 RT-003
3. GH-157 SI-2: no test that an unauthenticated `initialize` (POST /mcp, /mcp/messages) gets 401 and no instructions; broad `pytest.raises(Exception)`; no test that error messages omit rendered text / artifact_vars values: R1 RT-006, R2 RT-005, R2 RT-010, R3 RT-009
4. GH-157 SI-6: rendered `mcp_instructions` not checked for SecretStr / credential values, and no recorded "docs-only" decision: R1 RT-007, R2 RT-005, R3 RT-004
5. DESIGN.md §4.3 and FundPerformance comment still describe the old `sanitize_text` + `_sanitize_cell` id pipeline; landed code uses `safe_id_text`; pb_id rendering change not in CHANGELOG: R2 RT-002, R3 RT-001, R3 RT-008
6. `safe_id_text` silently alters ids (truncation at 256 with no marker, whitespace to `_`, fullwidth bracket swaps), producing believable but wrong ids; not documented or tested: R2 RT-003, R3 RT-007
7. `FundPerformance` pb_id duplicate pipeline / `_safe_id` helper not registered under C-007; `_ID_NEUTRALISE` hand-copied from `_BARE_SEPARATORS`: R1 RT-009, R2 RT-009
8. CHANGELOG files GH-156/GH-158 behavior changes under `### Fixed` instead of `### ⚠️ Behavior changes` / `### 🟡 Protocol surface changes`: R1 RT-008
9. REVIEWS.md Round 2 row (line 198, "Always emit (as null)") not marked superseded by Round 12 (GH-158): R1 RT-010, R3 RT-010
10. GH-159 `_validate` in ag_ui.py echoes unbounded client `content[].type` into RUN_ERROR.message (needs allowlist or `safe_error_text(max_len=32)`): R1 RT-011, R3 RT-005
11. GH-159 `_validate` rejects non-text parts anywhere in replayed history, bricking a thread after one image upload; docstring contradicts: R3 RT-006
12. new-agent SKILL.md harness vs template copies not identical (LRN-208 diff fails): R2 RT-006
13. GH-158 skill-trap test sits in the GH-156 test file, silently skips absent template mirror (LRN-157), does not assert copies match: R2 RT-008
14. `mcp_instructions=` silently accepted on `artifacts_dir=` agents and sent unrendered: R2 RT-010
15. Release gate: `test_version_matches_pyproject` fails on stale editable install in .venv (0.9.0 vs 0.10.0); not caused by G1: R1 RT-012

## Findings

### R1 RT-004 [SDK] — medium — tests/test_gh156_mcp_text_ids.py
GH-156 AC: 'Per-model tests assert ids in to_plain_text() and in the MCP tools/call content[0].text.' The MCP tools/call tests cover only EntityList and DocumentList. EmailList (id and conversation id), CalendarEvents, UserList and UserProfile (id and manager id) have no MCP content[0].text assertion. These four are the Graph-backed types where RT-001 bites.
- Fix: Parametrize the MCP test over all six types (reuse `_id_sample_instances()` through one tier-1 tool per type, or one generic tool), and assert every collected id appears verbatim in `content[0].text`.
- sdkCandidate: true

### R1 RT-005 [SDK] — medium — tests/test_content_types.py
The registry-wide meta-test (`test_registry_wide_every_id_field_reaches_text`, line 1197) checks only ids that the hand-built samples in `_id_sample_instances()` (line 1075) actually set, because `_collect_id_values` skips empty or None values. If someone adds a new optional `*_id` field to an existing model (e.g. `EmailMessage.parent_folder_id`), the sample leaves it unset and the test still passes, even though `_body_text` never renders it. That is the hand-list drift LRN-241 exists to prevent.
- Fix: Derive the set of id-field paths from the schema (`_id_fields_in_schema` extended to return field paths). Assert that the sample sets a non-empty value for every one of those paths, or that the path is in `_ID_TEXT_EXEMPT` with a reason, before checking that the values reach the text.
- sdkCandidate: true

### R1 RT-006 [SDK] — medium — tests/test_gh157_mcp_instructions.py
The GH-157 SI-2 annotation requires 'add a test proving an unauthenticated initialize gets no instructions'. No such test exists. Every test in the file mints an admin key. The code is currently correct (`mcp_post` has `Depends(require_identity)`), but nothing pins that the agent-authored text stays behind auth on both POST /mcp and the legacy POST /mcp/messages path.
- Fix: Add a test that builds an app with `mcp_instructions='secret-ish rule'` and POSTs `initialize` without an Authorization header to /mcp (and /mcp/messages). Assert 401 plus WWW-Authenticate, and assert the response body does not contain the instruction text.
- sdkCandidate: true

### R1 RT-007 [SDK] — medium — agent_sdk/app.py
SI-6 annotation for GH-157: `artifact_vars` can carry settings values into `mcp_instructions.md`, and the rendered text goes to every MCP client model. The annotation asked for a build-time check that the rendered text holds no SecretStr or credential-field value, or 'at minimum, write SI: SI-6 with the docs-only decision stated'. Neither exists. app.py lines 646-663 render and store the text with no check, and DESIGN.md §5.5 and the CHANGELOG say only 'no secrets'. There is no recorded decision that docs-only is the accepted control.
- Fix: Preferred: after rendering, compare `mcp_instructions` against every `SecretStr` value on `settings` and any plain `artifact_vars` value whose key matches the redact `_SECRET_KEY` pattern. Raise a ValueError naming only the variable name, never the value. Otherwise, add an explicit 'SI-6: docs-only control (rationale…)' line to DESIGN.md §5.5 and the todo.
- sdkCandidate: true

### R1 RT-008 [SDK] — medium — CHANGELOG.md
The [Unreleased] GH-158 entry and the GH-156 entry each describe themselves as a 'Behavior change'. GH-158 removes an AG-UI wire key that consumers could key on, and GH-156 changes `to_plain_text()` output, a Standard Profile required interface. Both are filed under `### Fixed`. The project convention (every prior release) and LRN-153 put such entries under `### ⚠️ Behavior changes`, or `### 🟡 Protocol surface changes` for wire shape, so release tooling and readers looking for migration notes miss them.
- Fix: Move GH-158 under `### 🟡 Protocol surface changes` (or `### ⚠️ Behavior changes`) with a one-line Migration note ('treat parentMessageId as optional'). Move GH-156 under `### ⚠️ Behavior changes`. Keep `### Fixed` for pure bug fixes.
- sdkCandidate: true

### R1 RT-009 [SDK] — low — agent_sdk/models/content_types.py
`FundPerformance._body_text` (lines 1054-1058) still inlines the same `_sanitize_cell(sanitize_text(pb_id, max_len=256))` pipeline instead of calling the new `_safe_id`. So there are two copies of the id-rendering contract. The new helper is also private to content_types.py and not registered under C-007, which the plan's Reuses annotation asked for (Dimension 8: unregistered reusable utility).
- Fix: Route pb_id through the same helper, and move the helper into `agent_sdk/common/redact.py` as a registered C-007 sibling (see RT-001).
- sdkCandidate: true

### R1 RT-010 [SDK] — low — REVIEWS.md
The Round 2 table row at line 198 ('`parentMessageId` absent on first tool call | Always emit (as null)') has no pointer to Round 12. A reader or an advisor that greps Round 2 sees the superseded rule as current. Only Round 12 records the reversal.
- Fix: Add a short suffix to the line 198 row: '— SUPERSEDED by Round 12 (GH-158): omit when absent'.
- sdkCandidate: true

### R1 RT-011 [SDK] — low — agent_sdk/routes/ag_ui.py
This is GH-159 (G2) code inside an in-scope file. `_validate` (lines 155-159) echoes the client-supplied `content[].type` string into RUN_ERROR.message whenever `kind.isidentifier()`. `isidentifier()` accepts arbitrary-length Unicode identifiers, so the label is bounded only by the request body cap. The todo's C-007 annotation asked for a fixed allowlist label or `safe_error_text(max_len=...)`.
- Fix: Map known AG-UI part types (`image`, `audio`, `binary`, `file`, `document`, ...) to fixed labels and everything else to 'unknown', or pass the value through `safe_error_text(kind, max_len=32)` before interpolating it.
- sdkCandidate: true

### R1 RT-012 [SDK] — low — tests/test_version.py
This is not caused by G1. Full-suite run: 2924 passed, 1 failed. `test_version_matches_pyproject` fails because the installed package metadata says 0.9.0 while pyproject.toml says 0.10.0 (a stale editable install in .venv). The /sdk-test release gate will be red until this is fixed, which blocks the requested release. mypy is clean.
- Fix: Re-install the package into .venv (`uv pip install -e .` or `uv sync`) before /sdk-test and /sdk-release, then re-run the test.
- sdkCandidate: false

### R2 RT-002 — medium — DESIGN.md
[SDK] DESIGN.md §4.3 (line ~212) says each id is rendered with `sanitize_text(..., max_len=256)` then `_sanitize_cell`. The landed code uses the new `safe_id_text` (agent_sdk/common/redact.py:194). It keeps = : , @ unchanged, turns whitespace into _, and does not neutralise those separators. The FundPerformance comment block at agent_sdk/models/content_types.py:1040-1050 still describes the old 'cap first (sanitize_text), THEN strip separators (_sanitize_cell)' pipeline above a line that now calls _safe_id. The change in how pb_id renders (it now keeps '=' and ':', and whitespace becomes '_') is not in CHANGELOG.
- Fix: Rewrite the §4.3 sentence to name safe_id_text (C-007) and its exact transform. Update the FundPerformance comment to match the _safe_id call. Note the pb_id rendering change in the CHANGELOG GH-156 entry.
- sdkCandidate: true

### R2 RT-003 — medium — agent_sdk/common/redact.py
[SDK] safe_id_text (line 194) quietly rewrites ids into a believable but wrong value. It cuts them at 256 characters with no marker. It turns whitespace into '_'. It swaps ()[]<>| for fullwidth look-alikes. GH-156 exists so a text-only client model can copy these ids back into follow-up tool calls. An id that was cut or rewritten looks real, gets copied, and fails upstream as not-found or wrong-item, with no sign that it was changed. The docstring's 'byte-exact' claim holds only for a narrow set of characters, and no test or doc covers the rewrite case.
- Fix: When the cleaned id differs from the input (cut, whitespace or bracket replaced), mark it in the text, for example by adding '…' or '[altered]', or leave the id out with a note that the structured content holds the exact value. Add a test for each case, and write the behaviour down in DESIGN §4.3 and the C-007 registry entry.
- sdkCandidate: true

### R2 RT-004 — medium — tests/test_content_types.py
[SDK] test_registry_wide_every_id_field_reaches_text decides which types need a sample from the schema (_id_fields_in_schema). But it decides which ids to check from values set by hand in _id_sample_instances (_collect_id_values skips unset optional fields). If someone later adds an optional `*_id` field to EmailMessage, CalendarEvent and so on, and leaves it None in the sample, the test still passes even though the field never reaches the text. That is the hand-list drift LRN-241 warns about.
- Fix: In the registry-wide test, list every id/*_id field path from the schema (including nested item models). Assert that each path has a non-empty value in the sample, or is listed in _ID_TEXT_EXEMPT with a reason. Only then assert that each value appears in to_plain_text().
- sdkCandidate: true

### R2 RT-005 — medium — tests/test_gh157_mcp_instructions.py
[SDK] Two SI notes in the GH-157 todo are not done. (1) The SI-2 note asks for a test proving an unauthenticated initialize gets no instructions, and none exists in this file. (2) The SI-6 note asks for a build-time check that the rendered text holds no SecretStr or credential-field value, or 'at minimum' a recorded docs-only decision. Neither exists: DESIGN §5.5, docs/protocols.md and CHANGELOG only say 'no secrets'. Meanwhile artifact_vars can carry settings values into mcp_instructions.md, which is sent to every MCP client model.
- Fix: Add a test that POSTs initialize to /mcp with no Authorization header and asserts a 401 whose body has no 'instructions' and none of the agent text. Then either add a build-time check in agent_sdk/app.py (~line 658) that rejects mcp_instructions containing any SecretStr value from settings (the error must name the field, never the value), or write 'SI-6: docs-only, rationale …' into DESIGN §5.5.
- sdkCandidate: true

### R2 RT-006 — medium — harness/skills/new-agent/SKILL.md
[SDK] GH-157 AC says 'harness skill mentions (all copies identical)'. harness/skills/new-agent/SKILL.md and template/.claude/skills/new-agent/SKILL.md still differ at lines 73, 80, 131, 216-225, 233-234 and 254-257 (uv vs pip install steps, bootstrap token on stderr vs stdout, a uv.lock reminder). The GH-157 lines were synced in template commit c9684be, but the copies are not identical, so LRN-208's diff check fails for this skill.
- Fix: Bring template/.claude/skills/new-agent/SKILL.md to match harness/skills/new-agent/SKILL.md with a separate commit and push in the template repo (LRN-071). Then confirm `diff harness/skills/new-agent/SKILL.md template/.claude/skills/new-agent/SKILL.md` prints nothing.
- sdkCandidate: true

### R2 RT-007 — medium — tests/test_gh156_mcp_text_ids.py
[SDK] GH-156 AC requires per-model tests asserting ids in the MCP tools/call content[0].text. Only EntityList and DocumentList go through MCP tools/call (plus a URN EntityList). EmailList (id and conversation), CalendarEvents, UserList and UserProfile (including manager id) are only checked through to_plain_text(), and EmailList only outside MCP. A later change to how routes/mcp.py builds tool text for these types would not be caught.
- Fix: Add a tier-1 tool per remaining type (EmailList, CalendarEvents, UserList, UserProfile, FundPerformance), or parametrize one tool factory. Assert each id/*_id value appears in result.content[0].text over /mcp tools/call.
- sdkCandidate: true

### R2 RT-008 — low — tests/test_gh156_mcp_text_ids.py
[SDK] test_skills_have_no_stale_parent_message_id_trap guards GH-158 skill text but sits in the GH-156 test file. It skips any missing mirror with `if p.exists()`, including template/.claude/skills/ag-ui-check/SKILL.md, which is gitignored and absent in a clean checkout. It only checks that the old string is gone, not that the three copies match. This is the silent-skip pattern from LRN-157.
- Fix: Move the test to tests/test_gh158_agui_no_null_fields.py. For an absent template copy, use pytest.xfail(strict=True) or an explicit skip with a reason instead of a silent `if`. Assert the harness and .claude copies are byte-identical.
- sdkCandidate: true

### R2 RT-009 — low — agent_sdk/common/redact.py
[SDK] _ID_NEUTRALISE (line 181) is a hand-copied version of _BARE_SEPARATORS with only '=' removed. The C-007 registry note says not to re-inline these translate maps. If a new separator is later added to _BARE_SEPARATORS, ids will not pick it up.
- Fix: Build it from the original: `_ID_NEUTRALISE = {k: v for k, v in _BARE_SEPARATORS.items() if k != ord('=')}` (str.maketrans output is keyed by ordinal).
- sdkCandidate: false

### R2 RT-010 — low — agent_sdk/app.py
[SDK] The docstring (line ~105) and the docs say mcp_instructions= is for persona= agents. But build_app (lines 653-654) quietly accepts the kwarg on an artifacts_dir= agent with no mcp_instructions.md, and sends it without rendering it through the template (no artifact_vars, no StrictUndefined). Separately, test_undefined_variable_is_error uses pytest.raises(Exception), which would also pass on an unrelated error.
- Fix: Either raise ValueError when mcp_instructions= is set together with artifacts_dir=, or document that the kwarg is sent as-is for artifact agents. Tighten the test to pytest.raises(jinja2.exceptions.UndefinedError, match='nope').
- sdkCandidate: false

### R3 RT-001 — medium — DESIGN.md
DESIGN.md:212 (GH-156 paragraph) says each id is rendered via `sanitize_text(..., max_len=256)` then `_sanitize_cell`, but the code at agent_sdk/models/content_types.py:120 (`_safe_id`) uses `safe_id_text`. That function deliberately skips `_sanitize_cell` and keeps `= : , @` byte-exact. The design doc now describes a pipeline no id goes through.
- Fix: Rewrite the sentence to: 'Each id is rendered via `safe_id_text(..., max_len=256)` (C-007: control chars stripped, whitespace to `_`, only `()[]<>|` neutralised; `= + / : , . _ - ! ~ @` kept byte-exact so the model can copy the id back).' Mention that FundPerformance.pb_id moved to the same helper.
- Codify: When an implementation deviates from the AC's named pipeline on a redteam reuse note, update the DESIGN paragraph to the landed helper, not the AC wording.
- sdkCandidate: true

### R3 RT-002 — medium — tests/test_gh156_mcp_text_ids.py
The GH-156 AC asks for per-model tests that assert ids in the MCP `tools/call` `content[0].text`. Only EntityList (2 tests) and DocumentList go through MCP. EmailList (id and conversation id), CalendarEvents, UserList and UserProfile (id and manager id) are tested only through `to_plain_text()`.
- Fix: Parametrise the MCP test over `_id_sample_instances()` from tests/test_content_types.py. Register one tool per type that returns the sample, call it via `tools/call`, and assert every `_collect_id_values(sample)` value (after `_safe_id`) is in `content[0].text`.
- sdkCandidate: true

### R3 RT-003 — medium — tests/test_content_types.py
The registry meta-test `test_registry_wide_every_id_field_reaches_text` (~line 1179) reads the schema only as a yes/no ('has any id field'). It then checks only the id values the hand-built sample happens to set. Suppose a new optional id field is added later, such as `EmailMessage.thread_id: str | None = None`. The sample leaves it None, `_collect_id_values` skips it, and the test still passes. This is the same hand-list drift LRN-241 exists to catch.
- Fix: Walk the schema and list every id field path (e.g. `EmailList.messages.conversation_id`). Assert each path has a non-empty value in the sample, so a new optional id must be set in the sample or exempted. Then assert each of those values reaches the text.
- Codify: A model-derived meta-test must take its expected field set from the schema, not from which values the sample sets, or optional fields added later slip past it.
- sdkCandidate: true

### R3 RT-004 — medium — agent_sdk/app.py
GH-157 SI-6: the rendered `mcp_instructions` (app.py ~646-663) goes to every authenticated MCP client model. Nothing checks it before it ships. ArtifactLoader uses an unsandboxed Jinja Environment, so if `artifact_vars` holds settings, `{{ settings.x.get_secret_value() }}` renders the real secret into `initialize.instructions`. The todo's SI-6 note asked for a build-time check, or at least a recorded 'SI: SI-6 — docs-only' decision. Neither landed. Only a docs warning exists.
- Fix: After rendering, collect every SecretStr value from `settings` (and every resolved credential-field value, if available at build), and raise ValueError('mcp_instructions contains a secret value') if any non-empty one is a substring. The message must not echo the value. If the decision stays docs-only, add the 'SI: SI-6 — docs-only, accepted' line to the todo and to DESIGN §5.5.
- sdkCandidate: true

### R3 RT-005 — medium — agent_sdk/routes/ag_ui.py
GH-159 code in this file: `_validate` (~line 158) puts the client's raw `content[i].type` into `RUN_ERROR.message` whenever `str.isidentifier()` is true. There is no length cap, and Unicode identifiers of any size are allowed, so a 1 MB identifier is echoed back in full. The todo's C-007 reuse note required a fixed allowlist label or `safe_error_text(max_len=...)`. Neither is applied.
- Fix: Map the type to a fixed allowlist (`image`, `binary`, `audio`, `file`, `document`, else `unknown`), or wrap it as `safe_error_text(kind, max_len=32)` together with an ASCII-only check. Add a test with a 10k-char identifier type asserting the RUN_ERROR message is short.
- sdkCandidate: true

### R3 RT-006 — medium — agent_sdk/routes/ag_ui.py
GH-159 code in this file: `_validate` now rejects any user message anywhere in the replayed `messages` history that has a non-text part. Its own docstring (~lines 130-138, unchanged) still says content is 'never hard-rejected — not on unexpected part shapes', because a rejected item in replayed history 'would ... permanently brick the session' (RT-001). Many AG-UI clients keep the rejected user turn in local history, so after one image upload every later turn on that thread ends in RUN_ERROR.
- Fix: Apply the non-text check only to the newest user message (the turn being submitted). Keep stripping or ignoring non-text parts in older replayed history inside `_fold_history`. Update the docstring to describe the new rule. Add a test: history holding an old image part plus a new text turn must finish with RUN_FINISHED.
- sdkCandidate: true

### R3 RT-007 — low — agent_sdk/common/redact.py
`safe_id_text` (~line 194) is described as preserving ids so a model can copy them back. Yet it silently changes real ids: whitespace becomes `_`, `()[]<>|` become fullwidth characters, and anything past 256 chars is cut off with no marker. A model that copies such an id back gets a non-matching id and a confusing upstream 404. Neither the docstring, DESIGN nor CHANGELOG says ids may be changed.
- Fix: Document the lossy cases in the docstring and DESIGN §4.3. Add a marker when an id is cut or changed (e.g. append `…` on truncation), so the model and the operator can tell a damaged id from a real one.
- sdkCandidate: true

### R3 RT-008 — low — agent_sdk/models/content_types.py
FundPerformance.pb_id (~lines 1040-1055) now uses `_safe_id` (keeps `= : ,` byte-exact, no `_sanitize_cell`). The 13-line RT-006/RT-001 comment above it still says 'Cap first (sanitize_text), THEN strip separators (_sanitize_cell)'. The CHANGELOG GH-156 entry lists six types and does not mention that pb_id rendering changed (it used to neutralise `=`/`:`/`,`).
- Fix: Replace the stale comment with one line pointing at `_safe_id` / `safe_id_text`. Add 'FundPerformance.pb_id now rendered byte-exact for `= : ,` via safe_id_text' to the CHANGELOG [Unreleased] GH-156 entry.
- sdkCandidate: true

### R3 RT-009 — low — tests/test_gh157_mcp_instructions.py
The GH-157 SI-2 note asked for a test proving an unauthenticated `initialize` gets no instructions. None was added. `test_undefined_variable_is_error` uses the broad `pytest.raises(Exception, match='nope')`. No test checks that the over-cap, undefined-variable or both-set errors leave out the rendered text and artifact_vars values.
- Fix: Add a test: build an agent with mcp_instructions set, POST initialize with no Authorization header, assert 401 and that the instruction text is not in the body. Narrow the undefined-variable test to `jinja2.UndefinedError`. Add a test that sets artifact_vars={'k': 'SENTINEL'} plus an over-cap template and asserts 'SENTINEL' is not in str(exc).
- sdkCandidate: true

### R3 RT-010 — low — REVIEWS.md
Round 12 says it supersedes Round 2, but the Round 2 table row (REVIEWS.md:198, 'Always emit (as null) in ag_ui.py') is not marked. Someone reading Round 2 alone still sees the old ruling as current.
- Fix: Add a '(superseded by Round 12, GH-158)' note to the line 198 decision cell.
- sdkCandidate: true
