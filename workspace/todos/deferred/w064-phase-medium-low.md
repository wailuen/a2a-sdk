# w064 — phase redteam medium/low findings (deferred)

- Wave: w064
- Scope: phase
- Date: 2026-10-24

Non-blocking — these did not block w064's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across all phase redteam rounds. Duplicate reports from later rounds are merged into one entry (original round IDs noted).

## Medium

### D-01 — docs/protocols.md:179 — A2A catalog negotiation doc not updated for GH-240 (round IDs: RT-002)
- Quote: "A2A clients must list a domain catalog in `a2uiClientCapabilities.catalogs` to receive its surfaces (GH-180). ... `catalogs` wins when present (GH-213)."
- Issue: [SDK] Doc still tells A2A clients to list a domain catalog, never says a present catalogs list must also hold the Standard Profile URN (`catalogs: ["urn:acme:v1"]` silently loses every Standard card). Says v0.9 key used when catalogs is "absent or unusable" — wrong on A2A now: empty `catalogs: []` is kept as sent (keep_declared_catalogs=True) and wins. Only DESIGN.md §5.4 has the new rule; CHANGELOG lists docs/protocols.md as changed for GH-240.
- Fix: Rewrite line 179 for A2A: first list found (catalogs, then v0.9.supportedCatalogIds, then supportedCatalogIds), even empty, is the advertised set; Standard cards need CATALOG_ID in it; no key at all keeps the Standard default. Say AG-UI unchanged; cite GH-240 ruling URL.
- Codify: A wire negotiation change must update the client-facing protocol doc (docs/protocols.md), not only DESIGN.md.
- sdkCandidate: true

### D-02 — agent_sdk/routes/mcp.py:808 — load_skill missing/non-string `name` reported as "unknown argument" (round IDs: RT-003, RT-001)
- Quote: `bad_keys.append("name")`
- Issue: [SDK] Missing or non-str `name` goes through `_unknown_argument_error`; reply is "tool 'load_skill' input invalid: name — unknown argument (not in the tool's input schema)", false since `name` is the one required field. A model obeying it drops `name` and never succeeds. tests/test_gh205_mcp_skills.py pins the wrong text for `{}` and `{"name": 5}`.
- Fix: Keep `_unknown_argument_error` for extra keys only. Missing → pydantic `missing`; non-str → `string_type` (loc=("name",), both in _BUILTIN_ERROR_CODES), via `ValidationError.from_exception_data`, merged with extra-key errors, rendered by C-050 `safe_validation_message`. Update the two test cases.
- Codify: An argument-error helper named for one failure type must not be reused for missing or wrongly typed required fields; the message must name the real failure.
- sdkCandidate: true

### D-03 — agent_sdk/common/json_strict.py:53 — unruled 64-level ingress depth cap (round IDs: RT-004, RT-002)
- Quote: `_MAX_DEPTH = 64`
- Issue: [SDK] GH-235 asked only to map RecursionError to JSONDecodeError. Landed code adds a hard 64-level cap on all ingress (POST /mcp, /mcp/messages, /v1/message:send, /ag-ui/run, /oauth/register). Valid JSON that parsed in v0.20.1 is now -32700 "Parse error" (deep tool input, DataPart, forwardedProps, AG-UI state). Not in docs/protocols.md, DESIGN.md, C-040 row (README.md:37, detail :242) or any Breaking/Migration note; CHANGELOG files it under Fixed.
- Fix: Drop the cap (RecursionError backstop only), or keep it with a ruling: document limit and per-surface error in docs/protocols.md and DESIGN.md, add to C-040 row + detail, move CHANGELOG note to Breaking/Migration; consider a limit tied to pydantic's 255 minus envelope rather than 64.
- Codify: A new limit on input every protocol route accepts is a wire-contract change: needs AC, ruling, protocol docs and registry row before it ships (LRN-397).
- sdkCandidate: true

### D-04 — agent_sdk/console/static/chat.js:741 — reset mid-stream poisons new thread (round IDs: RT-005)
- Quote: `for (const id of finished ? order : []) {`
- Issue: [SDK] GH-238's thread-identity guard (resumedThread) covers only the failed-resume branch. Reset is not disabled while busy; old run's RUN_FINISHED folds its messages into the new thread's state.aguiMessages (741) and sets pendingInterrupt from the old thread (660), so the next message is sent as a resume with a stale interruptId → not_found RUN_ERROR.
- Fix: Skip both the post-run fold and the RUN_FINISHED interrupt assignment when state.threadId !== resumedThread. Add a node test resetting the thread during processStream (like the onPost hook).
- Codify: Every client-side history or interrupt write after an await must re-check the thread is still the one the run started on.
- sdkCandidate: true

### D-05 — agent_sdk/agent/loop.py:1180 — private bidi/format stripper outside redact module (round IDs: RT-003)
- Quote: `def _drop_format_chars(text: str) -> str:`
- Issue: [SDK] GH-241 said to use existing C-034 `safe_line_text` with no new stripper. A private Cf stripper was added in loop.py, so only the SafeValueError hint drops bidi chars; other C-034/C-007 consumers (titles, names, error text) still pass them. Second unregistered sanitiser that can drift.
- Fix: Move the Cf drop into agent_sdk/common/redact.py (C-034 option or named helper next to `safe_line_text`), call it from `_validation_phrase`, register in workspace/components/README.md, and rule whether other wire-bound safe_line_text uses should drop bidi too.
- Codify: Wire character sanitising lives only in common/redact.py; a private stripper elsewhere is a second copy of a registered component.
- sdkCandidate: true

## Low

### D-06 — agent_sdk/console/static/chat.js:551 — user message kept in history on failed turn (round IDs: RT-006)
- Quote: `state.aguiMessages.push({ id: uuid(), role: "user", content: [{ type: "text", text: text }] });`
- Issue: [SDK] Pushed before POST, never removed on POST failure, RUN_ERROR or no terminal event; next turn sends two user messages in a row. GH-237 made ChatDriver.agui_turn add it only after RUN_FINISHED, so the first-party clients differ.
- Fix: Build body from `[...state.aguiMessages, userMsg]` and push only after RUN_FINISHED (C-072), or pop on !resp / RUN_ERROR / no-terminal. Add a node test.
- sdkCandidate: true

### D-07 — agent_sdk/console/static/chat.js:740 — fold ignores non-assistant roles; "chat.py agrees" comment false (round IDs: RT-004)
- Quote: `// after RUN_FINISHED (a partial reply is not a reply; chat.py agrees)`
- Issue: [SDK] GH-237 made chat.py skip text from messages with explicit non-assistant roles (developer, system). chat.js (743) still folds every buffered message as 'assistant'. Console and ChatDriver build different history from the same stream.
- Fix: Record `json.role` from TEXT_MESSAGE_START / first TEXT_MESSAGE_CHUNK per id; skip non-'assistant' ids at the fold (C-072). Node test with a developer START next to an assistant message. Or reword the comment if the gap is wanted.
- Codify: When the reply-join rule changes in chat.py, the console fold in chat.js must change in the same wave.
- sdkCandidate: true

### D-08 — agent_sdk/routes/ag_ui.py:715 — non-list `resume` silently treated as [] (round IDs: RT-005)
- Quote: `resume = resume_raw if isinstance(resume_raw, list) else []`
- Issue: [SDK] A present non-list `resume` (dict or string) becomes [] and the run starts fresh instead of failing — the same silent drop GH-235 targeted.
- Fix: If present, not None, and not a list → RUN_ERROR "invalid resume entry", code 'validation', fixed text. Test with a dict resume and a hostile marker.
- sdkCandidate: true

### D-09 — agent_sdk/testing/mcp.py:173 — C-056 load_skill exclusion hard-coded and over-broad (round IDs: RT-007)
- Quote: `counted = sum(1 for t in tools if t.get("name") != "load_skill")`
- Issue: [SDK] Hard-codes the string instead of LOAD_SKILL_TOOL, and drops any tool named load_skill, including an agent's own when skills_dir is unset → false "tools/list count N-1 != N" gate failure.
- Fix: Import LOAD_SKILL_TOOL from agent_sdk.agent.loop; exclude only the SDK built-in (match title 'Load skill' and {readOnlyHint: true, openWorldHint: false}), or pass skills mode to run_gate.
- sdkCandidate: true

### D-10 — agent_sdk/app.py:670 — boot checks still run after credential store opens (round IDs: RT-008, RT-006)
- Quote: `skills = SkillsRegistry(self.skills_dir)`
- Issue: [SDK] Only mcp_skills/reserved-name checks moved ahead of `_build_credential_store()`. SkillsRegistry parse, exclude_from_catalog unknown-name check, mcp_instructions conflict and secret checks still raise after the store (sqlite handle) is open, against the GH-236 "failed boot leaves no open store" intent.
- Fix: Move those store-free checks ahead of `_build_credential_store()`, or wrap post-open code in try/except that closes the store and re-raises. Extend test_boot_checks_run_before_credential_store with an unknown exclude_from_catalog name.
- sdkCandidate: true

### D-11 — agent_sdk/console/static/a2ui.js:754 — waterfall/multi-category/fund-performance renderers not row-capped (round IDs: RT-009)
- Quote: `function renderWaterfallChart(data) {`
- Issue: [SDK] DESIGN.md §7.1 (line 471) says every list, table, bar chart and scalar-row table is capped at MAX_ROWS. renderWaterfallChart, renderMultiCategoryChart and renderFundPerformance draw all rows without capRows/moreNote.
- Fix: Route them through capRows/moreNote, or narrow the §7.1 sentence.
- sdkCandidate: true

### D-12 — agent_sdk/console/static/a2ui.js:141 — renderer logs replayed createSurface as protocol error, docs say no-op (round IDs: RT-009)
- Quote: `console.warn("[a2ui] protocol error: duplicate createSurface for open surface", surfaceId);`
- Issue: [SDK] DESIGN.md §5.4 (364) and §7.1 (469) say a replayed createSurface for a held surface is a no-op; the SDK renderer reports it as a protocol error.
- Fix: Soften DESIGN.md (a spec renderer may report it; console ignores and applies later updates), or downgrade the warning to match "no-op". Node test folding the same array twice: one surface, no error note.
- sdkCandidate: true

### D-13 — tests/test_a2ui_wire.py:1527 — tasks/get replay test is vacuous (round IDs: RT-011)
- Quote: `assert sids(first) and sids(first) == sids(second)`
- Issue: [SDK] Test DESIGN.md §5.4 relies on only checks a stored task returns the same surfaceId twice (always true). Never checks a renderer leaves the held surface alone (no duplicate card, no new node).
- Fix: Node test feeding the same artifact messages to renderA2ui twice; assert second call returns no new node and only the duplicate-createSurface warning (align with D-12).
- sdkCandidate: true

### D-14 — docs/content-types.md:240 — contradictory id-joining guidance (round IDs: RT-010)
- Quote: "control characters are neutralised). Never join an id into a row with other"
- Issue: [SDK] GH-241 rewrite says "Never join an id into a row with other fields", then "use it [safe_joined_id_text] for an id you join into a row of your own"; follows an is_id-cells section (ids in rows).
- Fix: One rule: ids in their own is_id column or standalone line; if you must join one into a delimited row, render it with agent_sdk.safe_joined_id_text.
- sdkCandidate: true

### D-15 — harness/workflows/acceptance-api.js:236/246 — transports entries not validated (round IDs: RT-012, RT-008)
- Quote: `if (normalizedArgs.transports != null && !Array.isArray(normalizedArgs.transports)) badArgs.push('transports (must be an array)')`
- Issue: [SDK] Guard checks array-ness only. `["A2A"]`/`["bogus"]` pass with runA2A and runAGUI both false → no transport runs, vacuous scores (LRN-073 class). `[1]` crashes `transports[0].toUpperCase()` (line 101) with an unnamed error. Template copy has the same gap.
- Fix: In both copies, inside the C-069 guard, reject any entry not in ['a2a','agui'] with fixed message, e.g. "transports (entries must be 'a2a' or 'agui')". Node mutation test; update template mirror in the same LRN-071 commit.
- sdkCandidate: true

### D-16 — workspace/components/README.md:63 — C-070 "shared helper" is duplicated code; stale line anchors (round IDs: RT-013)
- Quote: `| C-070 | mcp_paginate (shared cursor page helper: ...) | agent_sdk/routes/mcp.py (today inline in _handle_tools_list ~593-618 with private _decode_cursor/_encode_cursor ~546-560) | present |`
- Issue: [SDK] The try/except _InvalidCursor block is copied into _handle_tools_list and _handle_prompts_list; anchors stale (now ~581-599, ~696-716).
- Fix: Extract one `_page(entries, cursor)` helper (slice + nextCursor, or raise _InvalidCursor) used by both handlers; update the row with no line anchors.
- sdkCandidate: true

### D-17 — workspace/components/README.md:82 — C-006 detail repeats GH-240 sentence (round IDs: RT-010)
- Quote: "GH-240: `gated`/`from_metadata` take a transport-scoped keyword `keep_declared_catalogs` ..." (appears twice)
- Issue: [SDK] Two near-duplicate GH-240 sentences (mid-paragraph and end) — a double-applied edit, the drift the shared-file rule warns about.
- Fix: Merge into one: transport-scoped `keep_declared_catalogs`, A2A-only "present list kept as sent", public `negotiate_standard` field.
- sdkCandidate: true

### D-18 — tests/test_rt001_strict_required_nullable_output.py:52 — weak duplicate test left in place (round IDs: RT-007)
- Quote: `def test_every_builtin_content_type_sample_wire_validates() -> None:`
- Issue: [SDK] GH-242 AC met by a new strict test; the old one still uses `except Exception: continue` and fails only on null-related errors.
- Fix: Delete the old test or rewrite it as the strict version; consider validating `inst.wire()` instead of `model_dump(by_alias, exclude_none)`.
- sdkCandidate: true

### D-19 — tests/test_mcp_security_rt001_005.py:67 — changed files missing from wave todos; CHANGELOG path (round IDs: RT-011)
- Quote: `def test_decode_cursor_negative_rejected_by_unit() -> None:`
- Issue: [SDK] tests/test_mcp_security_rt001_005.py rewritten (clamp → -32602) and tests/test_gh240_field_summary_alias.py created, neither in any group's Creates/Modifies. GH-238 CHANGELOG entry names `chat.js` only, not `agent_sdk/console/static/chat.js` (LRN-491 checks file name only, so it passes).
- Fix: Add the first file to G1/GH-236 and the second to G4/GH-240 in the wave file; change the GH-238 CHANGELOG entry to the repo path.
- sdkCandidate: true
