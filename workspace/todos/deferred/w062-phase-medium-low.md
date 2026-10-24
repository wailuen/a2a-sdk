# w062 — phase redteam: deferred medium/low findings

- Wave: w062
- Scope: phase
- Date: 2026-10-23

Non-blocking — these did not block w062's archive. Address opportunistically or fold into a future wave.

Findings from every redteam round, deduped by file + description. Repeat reports of the same defect across rounds are merged into one entry. All entries are SDK candidates. Original round IDs are listed per entry.

## Medium

### D-01 — strict schema decides nullability before resolving `$ref` (GH-206)
- File: `agent_sdk/common/schema.py:91` — `if _nullable_inner(pval) is not None:`
- Round IDs: RT-002, RT-004
- Problem: `MaybeInt = TypeAliasType('MaybeInt', Optional[int])`; `class O(BaseModel): b: MaybeInt` gives strict outputSchema `{b: {type: integer}}, required: [b]`. `O(b=None)` dumped with exclude_none is `{}` and fails `'b' is a required property`. structuredContent breaks the server's own outputSchema (MCP 2025-06-18).
- Fix: follow the property's local `$ref` chain first (same recursion guard), then run `_nullable_inner` and the required/keep_null logic on the resolved node. Add a TypeAliasType Optional regression test validating structuredContent against the strict outputSchema.
- Codify: a strict-schema rewrite that changes `required` must decide nullability after `$ref` inlining.

### D-02 — strict schema still emits anyOf-with-null in several positions (GH-206)
- File: `agent_sdk/common/schema.py:43` (`len(options) != 2`), `:131` (`if inner is not None and keep_null:`)
- Round IDs: RT-003, RT-001
- Problem: AC says strict output has no anyOf-null except the recursive case. It remains for: `Optional[Union[int, str]]` (3-option anyOf); list items / dict values (`list[Optional[str]]`, `dict[str, Optional[int]]`); required `Optional[Enum]`/const output fields with no default; required Optional fields whose inner has no single type. Copilot Studio-style strict clients reject this shape.
- Fix: drop the null option from wider unions at property positions (same `required` rule); for list items/dict values use `type: [X, "null"]`; for enums add null to `enum` with `type: ["string","null"]`. Or record the exceptions in a ruling comment and the AC. Add fixtures for each position in `tests/test_gh206_strict_schema_mode.py`.
- Codify: a null-collapse mode for strict clients must handle nullable unions of any width and be tested at every position a nullable can occupy.

### D-03 — strict schema leaves dangling `discriminator.mapping` pointers (GH-206)
- File: `agent_sdk/common/schema.py:108` — `out[key] = value`
- Round IDs: RT-004, RT-005, RT-003
- Problem: `$defs` is deleted but `discriminator.mapping: {'a': '#/$defs/A', ...}` is copied through and points at nothing.
- Fix: in `_Flattener._finish` / `flatten_schema`, drop `discriminator.mapping` (or the whole `discriminator`) once targets are inlined. Test that no `'#/$defs/'` string remains except in kept recursive `$defs`.
- Codify: when inlining `$defs`, rewrite or remove every string pointer into `$defs`, not only `$ref` keys.

### D-04 — GH-206 ruling deviation not ratified; CHANGELOG contradicts itself
- File: `agent_sdk/common/schema.py:97` — `keep = not self.keep_required and pname in required_names and "default" not in pval`
- Round IDs: RT-005, RT-003, RT-004
- Problem: ruling (issuecomment-6359827730) says anyOf[X, null] becomes X and the field leaves `required`, for input and output. Code keeps required-nullable input fields required, and output keeps `type: [X, "null"]` (or anyOf for enum/const). No ratification on GH-206. CHANGELOG GH-206 entry states the ruling wording, then the opposite.
- Fix: post the deviation on GH-206 and record the maintainer's ratification URL in the wave file, or implement the ruling literally. Reword the CHANGELOG entry to describe only what ships.
- Codify: a wave that departs from a maintainer ruling must record the deviation on the issue for ratification and must not describe the ruling text as shipped behaviour.

### D-05 — strict-schema conformance sweep filters out the errors it should catch
- File: `tests/test_rt001_strict_required_nullable_output.py:65`
- Round IDs: RT-009
- Problem: only errors containing "null" fail; missing-required errors are ignored; models whose `model_construct()`/`wire()` raise are skipped silently. D-01 would pass.
- Fix: fail on any validator error; build valid samples or assert skipped count is zero; add a ContentModel with a required `X | None` field checked through real MCP tools/call.
- Codify: a schema-conformance test must not filter validator errors by message text.

### D-06 — MCP gate count breaks with `mcp_skills='tool'` (GH-205)
- File: `agent_sdk/testing/mcp.py:174`
- Round IDs: RT-006, RT-006, RT-003
- Problem: tools/list returns N+1 (built-in `load_skill`); all three acceptance SKILL.md copies (line 200) pass `--expected-count <N tier-1 tools>`, so the C-056 `run_gate` fails every such agent.
- Fix: exclude `load_skill` from the count in `_check_list`/`run_gate`, or document N+1 in `docs/testing.md` and all three SKILL.md copies. Add a `run_gate` test against an `mcp_skills='tool'` app with `expected_count=len(registry.tier1())`.
- Codify: adding a non-registry tool to tools/list must update every count-based consumer in the same change.

### D-07 — `load_skill` tool missing `openWorldHint`
- File: `agent_sdk/routes/mcp.py:605` — `"annotations": {"readOnlyHint": True},`
- Round IDs: RT-007, RT-012
- Problem: MCP default for missing openWorldHint is true; LRN-043 requires explicit hints.
- Fix: `{"readOnlyHint": True, "openWorldHint": False}`; assert both in `tests/test_gh205_mcp_skills.py::test_tool_mode_lists_and_calls`.
- Codify: every tool the SDK lists on MCP, built-ins included, must state openWorldHint explicitly (LRN-043).

### D-08 — GH-230 validation-phrase allowlist: code, AC, docs and LRN disagree
- File: `agent_sdk/agent/loop.py:1183` / `:1190`; `workspace/learning/LRN-470-pydantic-type-code-echo.md:17`; `workspace/components/README.md:267` (C-050)
- Round IDs: RT-008 (round A), RT-005 (round C), RT-010 (round D)
- Problem: earlier round: allowlist was only the 25 `_VALIDATION_TYPE_PHRASES` codes, so common pydantic codes (too_long, int_from_float, date_parsing, uuid_parsing, ...) lost their hint. Landed code now echoes every pydantic built-in code (`_BUILTIN_ERROR_CODES`) verbatim, but the AC, C-050, CHANGELOG Fixed entry, `docs/tools.md` and the LRN-470 Check still say non-table codes render 'input failed validation'. LRN-470 Check points at `_VALIDATION_TYPE_PHRASES.get(` default, which no longer exists.
- Fix: pick one contract. Either narrow the code to the AC, or update the AC, C-050, CHANGELOG, `docs/tools.md` and LRN-470 to say the allowlist is pydantic's ErrorType literal plus `UNKNOWN_ARGUMENT_ERROR_TYPE`, and point the Check at `_validation_phrase` / `_BUILTIN_ERROR_CODES`. Name any remaining downgrade in the CHANGELOG.
- Codify: turning an echo fallback into an allowlist must carry over the common fixed codes, and every doc describing it must match.

### D-09 — `SafeValueError` subclass with bad `message` not caught at definition (GH-230)
- File: `agent_sdk/models/errors.py:75` — `message: str = ""`
- Round IDs: RT-002
- Problem: ruling says fail at boot when detectable. `class X(SafeValueError): pass` and `message = 5` import fine and fall back silently.
- Fix: add `__init_subclass__` raising TypeError when `message` is not a str or is blank after `safe_line_text`; keep runtime fallback. Test both bad subclasses.
- Codify: "fail at boot when detectable" means check the class with `__init_subclass__`.

### D-10 — console A2UI surface registry grows without bound (GH-214)
- File: `agent_sdk/console/static/a2ui.js:28` (`const surfaces = new Map();`), `:137`
- Round IDs: RT-009, RT-007, RT-006
- Problem: only pruned in the deleteSurface branch, which the SDK no longer sends. Each entry holds components, a data model copy and a DOM node.
- Fix: prune entries with `!entry.node.isConnected` on each `renderA2ui`, cap/evict oldest beyond N, or clear on new conversation. Note the choice in the header comment. Add a node-harness test that the registry stays bounded.
- Codify: when a wire change removes the message a client used to free state, audit every first-party consumer for state only that message released.

### D-11 — replayed snapshots resend `createSurface` for open surfaces (GH-214)
- File: `agent_sdk/routes/a2a.py:1240` — `stream, abort = await _open_stream(request, record, identity)`
- Round IDs: RT-002 (round D)
- Problem: tasks/resubscribe first frame and tasks/get replay every earlier A2UI artifact with its original surfaceId. Without deleteSurface, a client gets a duplicate createSurface (A2UI v0.9.1 error; console logs it).
- Fix: document in the GH-214 Breaking/Migration entry and DESIGN.md §5.4 that replayed createSurface for a held surface is a no-op; make the console idempotent and quiet; add a resubscribe replay test.
- Codify: removing a lifecycle-closing message must be checked against every replay path, not only live emit.

### D-12 — `surfaceId` lifetime documented per turn, actually per artifact (GH-214)
- File: `docs/protocols.md:53`; also `agent_sdk/a2ui/translator.py:26`, DESIGN.md §5.4/§7.1, CHANGELOG Migration line
- Round IDs: RT-012, RT-020
- Problem: `translate()` makes a fresh uuid4 surfaceId per artifact; a client keying lifetime per turn would merge cards.
- Fix: say "each artifact (A2A artifact / AG-UI A2UI_UPDATE) carries a fresh surfaceId" everywhere.
- Codify: a migration note about surface lifetime must state the real granularity.

### D-13 — `safe_id_text` output changed without Migration note (GH-212)
- File: `agent_sdk/common/redact.py:250`; `CHANGELOG.md:21`
- Round IDs: RT-008, RT-004
- Problem: public helper (now exported from `agent_sdk`) no longer swaps spaces or `( )`. Downstream joined rows lose the GH-156 forgery defence silently. `safe_joined_id_text` is not exported top-level nor named in `docs/content-types.md`.
- Fix: add a **Migration:** line naming `agent_sdk.common.redact.safe_joined_id_text` for joined-row callers; consider exporting it beside `safe_id_text`; name it in docs "Machine ids".
- Codify: changing a sanitizer agent repos import is a contract change; the CHANGELOG must name the replacement.

### D-14 — GH-212 SI-2 test silently narrowed the AC
- File: `tests/test_gh212_id_safe_text.py:170` — `assert row.count("(id:") == 1`
- Round IDs: RT-011, RT-011
- Problem: AC requires exactly one `id:` and at most one `conversation:`; real row has three of each because the ratified joined rendering keeps `:` and `,`. Not recorded on GH-212 or in the wave file.
- Fix: keep the code (HUMAN GATE). Assert on `'(id: '` and `', conversation: '`, explain in the docstring, amend the AC on GH-212 / wave file, or ask the maintainer whether the joined variant should swap `:`.
- Codify: when a ratified rendering cannot meet an AC literally, the test must say so and the AC must be amended.

### D-15 — GH-229 no-echo / bare-args static tests miss likely regressions
- File: `tests/test_gh131_acceptance_api_args_normalization.py:66`, `:48`, `:23`
- Round IDs: RT-022, RT-023, RT-010, RT-016
- Problem: `+ e.message` (SyntaxError can quote the keyFile path) and `+ JSON.stringify(normalizedArgs)` both pass the no-echo test. `test_no_bare_args_read_after_guard` scans only from `const BASE_URL` onward, missing helpers defined above (e.g. `buildScenarioPrompt`). `_after_guard` is dead code with a missing marker.
- Fix: after stripping string literals, ban `normalizedArgs`, `JSON.stringify`, `e.message`, `\be\b` and template literals (or allow only badArgs/join); scan the whole file outside the guard for `\bargs\b` in code; delete `_after_guard`; add mutation checks injecting each leak.
- Codify: a static "error never echoes input" test must ban the parsed object and the caught exception's message, proven by mutation.

### D-16 — component registry entries stale (C-015, C-031)
- File: `workspace/components/README.md:115-116`, ~210
- Round IDs: RT-010, RT-013
- Problem: C-015 says "Verified against current code" but cites stale lines (chat.js 407-408 / 669-670, now 457-458 / 732-733; testing/chat.py 421-427). C-031 says the walker is in `tests/test_gh156_mcp_text_ids.py` (it is in `tests/test_content_types.py`) and omits `_JOINED_ID_SLOTS` / `with_kind`.
- Fix: cite by symbol (`handleA2aArtifact`, AG-UI CUSTOM `A2UI_UPDATE` handler, `extract_a2ui`) or current lines; correct C-031.
- Codify: a registry entry edited by a wave must re-check every cited line or cite by symbol.

## Low

### D-17 — `docs/protocols.md` overstates strict mode ("no anyOf with null")
- File: `docs/protocols.md:135`
- Round IDs: RT-013, RT-014, RT-006, RT-005
- Fix: align with `docs/deployment.md` (collapse only at property positions; list items, dict values, wider unions, required-nullable output fields incl. enum/const keep null), or fix code per D-02.

### D-18 — `load_skill` description has no length cap
- File: `agent_sdk/routes/mcp.py:593`
- Round IDs: RT-018, RT-015, RT-007, RT-008
- Fix: cap each skill description and the joined text at `_MAX_DESCRIPTION_LEN` with an "...and N more" marker, or fail at boot. Add a test.

### D-19 — tools/call `load_skill` served when unlisted; arguments not validated
- File: `agent_sdk/routes/mcp.py:716`
- Round IDs: RT-017, RT-016, RT-012, RT-008
- Problem: empty/fully excluded catalog hides it from tools/list but tools/call returns isError 'skill not found' instead of -32602. Accepts extra keys and missing/non-string `name` despite `additionalProperties:false`, `required:[name]` (unlike GH-196 registry tools).
- Fix: serve only when `_mcp_skills(app)` is non-empty, else `__jrpc_unknown_tool__` path; reject bad arguments with the registry argument-error shape (or drop `additionalProperties: False`).

### D-20 — reserved name `load_skill` defined three times
- File: `agent_sdk/routes/mcp.py:576`; `agent_sdk/agent/loop.py` `LOAD_SKILL_TOOL`; literal in `agent_sdk/app.py:665`
- Round IDs: RT-017, RT-008
- Fix: import `LOAD_SKILL_TOOL` from `agent_sdk.agent.loop` in `routes/mcp.py` and `app.py`; delete the copies.

### D-21 — `mcp_description` validation assumes str
- File: `agent_sdk/agent/registry.py:515`
- Round IDs: RT-019, RT-018, RT-009, RT-009
- Problem: `mcp_description=123` raises AttributeError not ValueError; value stored unstripped; tier-2 value silently ignored; `docs/tools.md` says "at boot" but it runs at decoration.
- Fix: isinstance check raising `ValueError("mcp_description must be a string")`; store `.strip()`; reject on tier=2 (or document); fix docs; extend bad-value parametrize in `tests/test_gh207_mcp_description.py`.

### D-22 — `mcp_skills` typed loosely and validated late
- File: `agent_sdk/app.py:117`, `:661`
- Round IDs: RT-020, RT-019, RT-010, RT-007
- Problem: `str | None` lets type checkers accept 'both'; the three GH-205 checks run after `_build_credential_store()` (and API key / OAuth stores), leaving them open on failure.
- Fix: `Literal["tool", "prompts"] | None`; keep runtime check; validate in `Agent.__init__` or at the top of `build_app` before stores are built.

### D-23 — empty-message fallback checks hint before sanitising
- File: `agent_sdk/agent/loop.py:1181`
- Round IDs: RT-021
- Problem: `'\x07'` passes `hint.strip()`, then `safe_line_text` gives '' and renders `'ticker — '`.
- Fix: sanitise first, return only if non-empty, else generic phrase. Add a parametrized `'\x07 '` case.

### D-24 — `validate_a2ui_delivery` error still describes the removed split (GH-214)
- File: `agent_sdk/agent/runner.py:381-382`
- Round IDs: RT-014, RT-021
- Fix: reword, e.g. "translate() output has no open messages after dropping deleteSurface (never delivered, GH-214); malformed translate() output". Keep the "empty open" substring.

### D-25 — empty-open guard never exercised (GH-214)
- File: `tests/test_gh214_no_delete_surface.py:67`
- Round IDs: RT-015, RT-023
- Problem: feeding `[]` is rejected earlier by `_validate_a2ui_wire`; the post-filter guard is never reached. Admin-console AC test only greps JS with cwd-relative paths.
- Fix: feed `[{"version":"v0.9.1","deleteSurface":{"surfaceId":"s"}}]`, assert `match='empty open'` on A2A `build_artifact` and AG-UI `_RunMapper.map`; build JS paths from `Path(__file__)`.

### D-26 — close-message tests deleted instead of rewritten (GH-214)
- File: `tests/test_a2ui_wire.py:248`
- Round IDs: RT-016, RT-022
- Fix: rewrite `test_split_a2ui_delivery_isolates_delete_surface` / `_empty_input` to assert delivered A2A/AG-UI arrays from a real `translate()` contain no deleteSurface and equal its output; keep empty-input as an empty-open rejection; cite https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762.

### D-27 — CHANGELOG placement for GH-214 departs from ruling
- File: `CHANGELOG.md:10`
- Round IDs: RT-024
- Fix: note Breaking-vs-Changed placement and its §4.0/LRN-153 reason on GH-214 for ratification, or follow the ruling.

### D-28 — caller-supplied `surface_id` reuse now collides (GH-214)
- File: `agent_sdk/a2ui/translator.py:171`
- Round IDs: RT-013
- Fix: document that `surface_id` must be unique per artifact, or reject/warn on reuse via SurfaceRegistry; add a CHANGELOG note.

### D-29 — `is_id` joined-row leftover risk undocumented (GH-212)
- File: `docs/content-types.md:237`
- Round IDs: RT-025, RT-025
- Problem: doc says never join an id into a row, but `is_id` ComparisonTable columns are joined with ' | '; `( )`, spaces, `:` and `=` survive (e.g. `'X (Revenue=99.0%)'`).
- Fix: reword to "never join an id into free text beside other fields; an is_id column is the one supported joined form"; state the leftover risk in docs and DESIGN.md §4.3 (`|` still neutralised). No code change (ratified).

### D-30 — `ColumnDef.is_id` adds an outputSchema property unannounced
- File: `agent_sdk/models/content_types.py:817`
- Round IDs: RT-014
- Fix: note the outputSchema addition in the CHANGELOG GH-212 entry; add `is_id` to the ColumnDef docstring's SDK-extension list.

### D-31 — GH-207 loop-keeps-docstring AC tested on the wrong object
- File: `tests/test_gh207_mcp_description.py:61`
- Round IDs: RT-026, RT-027, RT-011
- Fix: drive one loop turn with `FakeModelClient` and assert the tool spec given to the model has the docstring description.

### D-32 — `test_gh230` test hygiene
- File: `tests/test_gh230_safe_value_error.py:168`, `:179`
- Round IDs: RT-026, RT-015
- Problem: dead noqa imports and unused model; stray bare expression; class inside try; `text` unbound on no-raise; never renders an `unknown_argument` error through `safe_validation_message`.
- Fix: `pytest.raises(ValidationError)` per case; remove dead code; add a real `unknown_argument` ValidationError assertion.

### D-33 — `routes/mcp.py` docstrings out of date
- File: `agent_sdk/routes/mcp.py:44`
- Round IDs: RT-026
- Fix: list prompts/list, prompts/get (-32601 unless `mcp_skills='prompts'`), conditional `capabilities.prompts`, the `load_skill` built-in and `AGENT_SDK_MCP_SCHEMA_MODE=strict`; fix `_handle_tools_list` "Tier 1 only".

### D-34 — stale `deleteSurfaceSemantics` reference
- File: `tests/test_rt001_a2ui_data_encoding_hint.py:6`
- Round IDs: RT-011
- Fix: mark the reference as removed (superseded by the GH-214 ruling URL).

### D-35 — GH-229 wave-file `Creates:` names the wrong test file
- File: `workspace/todos/active/w062-gh-issues.md:162`
- Round IDs: RT-024, RT-028, RT-016, RT-011
- Problem: lists `tests/test_gh131_wave_cycle_args_normalization.py` (unchanged); tests landed in untracked `tests/test_gh131_acceptance_api_args_normalization.py`.
- Fix: update the entry to the new file and make sure it is staged with the wave commit.
