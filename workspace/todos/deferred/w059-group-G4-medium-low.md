# w059 — Group G4 — deferred medium/low findings

- **Wave:** w059
- **Scope:** unit:G4
- **Date:** 2026-10-22
- **Status:** Non-blocking — these did not block w059's archive. Address opportunistically or fold into a future wave.

Findings were collected across every redteam round and deduped by file + description.
Several rounds reported the same defect under different RT ids; the "Seen as" line keeps the original ids.
All items are SDK candidates (`sdkCandidate: true`).

## Medium

### D1 — Interrupt form submit bypasses the send() busy guard
- **File:** `agent_sdk/console/static/chat.js` (~line 500)
- **Seen as:** RT-003 (r1), RT-003 (r2), RT-004 (r3)
- **Problem:** The multi-field interrupt form calls `sendAgui("", r.payload)` directly. `state.busy` is never set, the Send button stays enabled, errors are not caught (unhandled rejection, no `error:` line), and there is no mode check. A second concurrent AG-UI run can start on the same threadId. The form outlives its interrupt: after RUN_ERROR clears `pendingInterrupt`, or after a switch to A2A, a submit takes the non-resume branch, posts an empty user message and drops the payload. No test covers the form path.
- **Fix:** Move the busy/disable/try-catch-finally logic into one helper (e.g. `runExclusive(fn)`) used by both `send()` and the form. Return early if busy. The form keeps its interruptId; refuse submit unless `state.mode === 'agui'` and `pendingInterrupt` matches. Remove the form on run start, RUN_ERROR, new interrupt, mode switch and session reset. Add a form-submit test.
- **Codify:** Every console path that starts a run must go through the single busy-gated send wrapper, or concurrent runs on one thread become possible.

### D2 — Enum match in coerceValue is case-sensitive; regresses ActionGate replies
- **File:** `agent_sdk/console/static/interrupt.js` (~line 12-16)
- **Seen as:** RT-004 (r1), RT-008 (r2, low), RT-003 (r3)
- **Problem:** `DEFAULT_CONFIRM_SCHEMA.decision` has enum `["approved","rejected"]`. `yes`, `ok`, `approve`, `Approved`, `no`, `cancel` are now refused with "must be one of: approved, rejected". Before GH-216 these went as `{decision: text}` and `parse_decision` (`_AFFIRMATIVE`/`_NEGATIVE` in gate.py) accepted them. The resume prompt does not list allowed values. `test_gate_and_no_schema_use_decision` only tests literal `approved`.
- **Fix:** Match string enum values case-insensitively after trim, returning the canonical value. Show enum choices in the `↩ resume required` line and input placeholder. Test `Approved` → `{decision: 'approved'}` and the hint. If free-text `yes` must not work, document it in CHANGELOG.
- **Codify:** Tightening client-side validation to a server schema's enum can reject answers the server's own parser accepts; check the server vocabulary first, and show allowed values in the prompt.

### D3 — Catalog-id fetch has no timeout and now gates every send
- **File:** `agent_sdk/console/static/chat.js` (`loadCatalogIds` ~line 351; awaits from ~line 368)
- **Seen as:** RT-005 (r1), RT-012 (r2, low), RT-005 (r3)
- **Problem:** `sendA2a` and `sendAgui` `await catalogIdsReady`. The fetch of `/.well-known/agent-card.json` has no timeout. A stalled card blocks every send in both modes with Send disabled. Before G4 sends never depended on it.
- **Fix:** `signal: AbortSignal.timeout(3000–5000)` on the fetch, or `Promise.race` with a short timer; fall back to the Standard Profile default.
- **Codify:** A startup fetch that gates user actions needs a timeout and a fallback.

### D4 — JSON Pointer: prototype pollution and non-string paths fold to model root
- **File:** `agent_sdk/console/static/a2ui.js` (`pointerTokens` ~line 42-45, `pointerSet` ~line 72, `foldMessage` ~line 168, `paintSurface`)
- **Seen as:** RT-006 (r1), RT-002 (r2), RT-001 (r3)
- **Problem:** (a) `pointerSet` walks `__proto__`/`constructor`/`prototype`; `/__proto__/polluted` writes to `Object.prototype` (confirmed in node). Predates G4 but sits in the changed function. (b) Non-string paths (`5`, `{}`, `["a"]`, `0`, `false`) become `[]` via `String(p).split('/').slice(1)` or `path || ""`, so `updateDataModel` replaces the whole model with no note, and a root binding reads the whole model. Breaks the GH-215 AC "never folded to the model root".
- **Fix:** `pointerTokens` returns null for any non-string pointer (keep null/undefined, `""`, `"/"` aliases) and for any `__proto__`/`constructor`/`prototype` token. `updateDataModel` and the root `data.path` binding reject null/non-string with a note. Add parametrized node tests: `/__proto__/x`, `5`, `{}`, `0`.
- **Codify:** A path guard must check type as well as shape; String() coercion of a malformed path must never reach the root-replace branch.

### D5 — renderGeneric key/value table and section count are uncapped
- **File:** `agent_sdk/console/static/a2ui.js` (`renderGeneric` ~line 450-480, `scalarRows.map` ~line 469)
- **Seen as:** RT-007 (r1), RT-005 (r2), RT-002 (r3)
- **Problem:** 500 scalar keys → 500 `<tr>` rows (MAX_ROWS is 100). N array keys → N tables. Breaks the GH-215 AC "Every list/table renderer caps rows with one shared constant"; CHANGELOG claim "All list/table renderers share one MAX_ROWS cap (100)" is false.
- **Fix:** `capRows(scalarRows)` + `moreNote(scalarRows)`; cap array sections (MAX_ROWS or a total-row budget) with an "N more" note. Extend `test_row_cap_applies_with_more_note` with >MAX_ROWS scalar keys.
- **Codify:** The generic fallback renderer is a table renderer too; test the cap on every row-producing branch.

### D6 — Array/scalar-bound unknown components lost their raw JSON view
- **File:** `agent_sdk/console/static/a2ui.js` (`paintSurface` ~line 222)
- **Seen as:** RT-004 (r2)
- **Problem:** GH-215 deleted `jsonFallbackNode`. Array- and scalar-bound unknown components now go to the text fallback (Rows bound to `[{a:1}]` renders only `FB`). Previously an inspectable JSON `<pre>` (GH-28 interim). Conflicts with AC "raw JSON stays available in a collapsible block"; unlisted regression.
- **Fix:** For arrays of objects render `genericTable(rows)` + `moreNote`; always add the collapsible Raw JSON `<details>`. Text fallback only for null/undefined. Add a test.
- **Codify:** Removing an interim fallback must keep every input class it covered, not only the one the new feature targets.

### D7 — DESIGN.md §7.1 drifted from the generic renderer
- **File:** `DESIGN.md` (~line 464)
- **Seen as:** RT-008 (r1), RT-006 (r2)
- **Problem:** Still says "unknown component types render the artifact's TextPart fallback". Object-bound unknowns now render a generic data card; relative paths are rejected with a note. No G4 todo lists DESIGN.md.
- **Fix:** Update §7.1: generic card for object-bound unknowns, MAX_ROWS cap, per-message fold isolation, relative/non-string path rejection. Add DESIGN.md to the GH-215 todo's Modifies/Creates line and CHANGELOG file list.
- **Codify:** A console renderer behaviour change must update DESIGN §7.1 in the same todo.

### D8 — CHANGELOG misses new JS exports and two behaviour changes
- **File:** `CHANGELOG.md` (~lines 24-25)
- **Seen as:** RT-007 (r2)
- **Problem:** LRN-379: new exports (interrupt.js `buildResumePayload`/`buildPayloadFromValues`/`formFields`/`coerceValue`, a2ui.js `MAX_ROWS`) appear only under Fixed, with no Added line marked internal. Omits: array-bound unknowns lose JSON view (D6); enum-strict resume (D2).
- **Fix:** Add `### Added` lines marked "internal console helper, not stable API". State both behaviour changes under GH-215/GH-216.
- **Codify:** The CHANGELOG reconcile must list new JS module exports under Added, marked internal, as well as Python symbols.

### D9 — rescanScope never restores a declared path dropped at Parse
- **File:** `.claude/workflows/sdk-wave.js` (`rescanScope` ~lines 1118-1124); mirror in `harness/workflows/wave-cycle.js`, `.claude/workflows/wave-cycle.js`
- **Seen as:** RT-006 (r3)
- **Problem:** A path is added to a group's scope only if missing from `wave.allScope`. G4's todo declares `agent_sdk/console/static/interrupt.js` and `tests/test_card_console.py`; both were in allScope but not in G4's scope, so GH-216's main module was outside the unit-redteam scope.
- **Fix:** Run owner-matching for every scanned path; push into any owning group's `g.scope` that lacks it. Behaviour test in `tests/test_sdk_wave_behaviour.py` where Parse omits a declared path and the first rescan restores it.
- **Codify:** A scope re-scan must check each declared path against its owning group's scope, not only the wave-wide union.

## Low

### D10 — Invalid single-field resume input is echoed and cleared
- **File:** `agent_sdk/console/static/chat.js` (bubble ~line 764; return ~line 517)
- **Seen as:** RT-009 (r2)
- **Problem:** `send()` draws the user bubble and clears the input before `sendAgui` rejects the input. Transcript shows an unsent message; user must retype.
- **Fix:** Validate the resume payload (or return a status from `sendAgui`) before `bubble()` and clearing; keep text on failure.
- **Codify:** Echo a user message only after it has been accepted for sending.

### D11 — coerceValue fails open / mis-coerces
- **File:** `agent_sdk/console/static/interrupt.js` (default branch ~line 32-33)
- **Seen as:** RT-010 (r2), RT-007 (r3)
- **Problem:** object, array and union types (`["integer","null"]`) return the raw string with no error. Integers beyond `MAX_SAFE_INTEGER` lose precision. `number` accepts `0x10` → 16.
- **Fix:** Handle type arrays (first non-`null` member, or try each). object/array: `JSON.parse` + type check, else `{ok:false}`. Integers: require `Number.isSafeInteger`. Numbers: decimal regex `/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/`. Any other non-string type → `{ok:false}`.
- **Codify:** Schema coercion must fail closed on types it does not understand.

### D12 — Weak GH-215/GH-216 tests
- **File:** `tests/test_gh215_console_generic_renderer.py` (also `tests/test_gh216_console_interrupt_schema.py:139`)
- **Seen as:** RT-009 (r1), RT-011 (r2), RT-008 (r3)
- **Problem:** `test_first_send_awaits_catalog_ids` only checks source order; `test_render_a2ui_messages_is_guarded` only checks `try {` exists. `test_relative_pointer_never_folds_to_model_root` passes on the root-binding note alone. `test_integer_resume_delivers_int_to_tool` posts hand-written `{row_number: 2}`, not the JS builder/envelope output. Node-driven tests bare-skip when node is missing (LRN-226).
- **Fix:** Use the `_IN_CI` assert pattern from `tests/test_card_console.py` in both modules. Assert the specific "updateDataModel rejected: relative path" note and unchanged model. Drive chat.js send under node with stubbed fetch/postSse and assert first body's `a2uiClientCapabilities.catalogs` has the domain ids (incl. late card). Have the JS driver emit the full resume body and POST it in the end-to-end test.
- **Codify:** An AC test must fail when the specific branch it names regresses, not only when a neighbouring branch does.

### D13 — Stale resume comment; genericTable drops columns silently
- **File:** `agent_sdk/console/static/chat.js` (~lines 531-533); `agent_sdk/console/static/a2ui.js` (`genericTable`)
- **Seen as:** RT-009 (r3)
- **Problem:** Comment says payload "must be an object carrying `decision`"; it now comes from responseSchema. `genericTable` drops columns after 8 and all non-scalar columns with no note; with no scalar fields it renders up to 100 empty rows.
- **Fix:** Reword comment (`{decision: text}` is the no-schema fallback read by `parse_decision`). Add a note when columns are dropped; skip the table (keep raw JSON) when no scalar columns exist.
