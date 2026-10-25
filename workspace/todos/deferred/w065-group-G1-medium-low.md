# w065 — group G1 — deferred medium/low findings

- Wave: w065
- Scope: unit:G1
- Date: 2026-10-24
- Source: every redteam round of unit G1, deduped by file + description (round IDs listed per item)

> Non-blocking — these did not block w065's archive. Address opportunistically or fold into a future wave.

All items are sdkCandidate: true.

## Medium

### D-01 chat.js role predicate differs from C-072 `_is_role` (R1 RT-003, R2 RT-001, R2 RT-006)
- File: agent_sdk/console/static/chat.js:617 (START path), :635-636 (CHUNK path)
- Problem: chat.js accepts `role: ""` as a role; chat.py `_is_role` requires a non-empty string. START with `role: ""` + "hello": chat.js drops the reply, chat.py keeps it as assistant. CHUNK path tracks only earlier CHUNKs (`seenChunkIds`), while chat.py ignores a role once any text frame exists (`key not in reply_parts`): CONTENT(k1) then CHUNK(k1, role "tool"/"user") is dropped by chat.js, kept by chat.py. The "chat.py agrees" comment (line ~766), C-074 row and DESIGN.md §7.2 parity claim are false.
- Fix: one `isRole = (v) => typeof v === "string" && v !== ""` on both paths; on CHUNK, skip role recording when the id already had text from any frame type (`textBuffers.has(id)` before this frame). Node cases: `role: ""` on START and CHUNK; CONTENT-then-CHUNK-with-role. Say "non-empty string role" in C-074 row and DESIGN.md §7.2.
- Codify: a JS mirror of a Python fold rule must copy the exact predicate; test both copies against one case table incl. empty string and mixed frame types.

### D-02 chat.js history fold posts empty and id-less assistant messages (R1 RT-004, R2 RT-002)
- File: agent_sdk/console/static/chat.js:772
- Problem: START+END with no CONTENT folds `{role:"assistant", content:""}`; CONTENT with no messageId folds an assistant message with `id: undefined`, and the next POST sends it without an id. C-072: append only non-empty replies, every message carries an id (AG-UI BaseMessage.id is required).
- Fix: `if (buf && buf.text())`; mint an id (`id ?? uuid()` at buffer creation, or `id: id || uuid()` at fold). Node tests on the next POST body: no-messageId CONTENT gives a string id; START+END with no content folds only the user message.
- Codify: a client owning AG-UI history never posts an id-less or empty assistant entry; test the next POST body.

### D-03 Replay test cannot detect duplicate paint (R1 RT-005, R2 RT-003)
- File: tests/test_gh239_console_caps.py:183
- Problem: harness never attaches the first node to a parent, so a2ui.js takes the "new node" branch; `len(res[1]["nodes"]) == 1` is what a duplicate-paint bug also produces. In-place `replaceWith` path and surface count (GH-244 item 3) untested.
- Fix: append returned nodes to a fake transcript root; assert second call returns `nodes == []`, root has one child still showing the KPI value, `notes == []`, surface count 1 (test-only size getter or updateDataModel probe).
- Codify: replace-in-place tests must attach painted nodes to a parent in the fake DOM.

### D-04 test_gh214 node test silently skips; loses always-on deleteSurface guard (R1 RT-010 part, R2 RT-004)
- File: tests/test_gh214_no_delete_surface.py:90
- Problem: bare `pytest.skip("node not installed")` with no CI guard (LRN-226 class); skip precedes the `"deleteSurface" not in chat` check, so CI without node loses that guard.
- Fix: move the chat.js source assertion to its own never-skipping test; give the node test a `needs_node` mark plus `test_gh214_node_available_in_ci` / `_IN_CI` loud-fail (pattern: tests/test_card_console.py:291).
- Codify: replacing a source grep with a node test must not make an always-on assertion skippable.

### D-05 Column cap duplicates capRows/moreNote (R1 RT-007, R2 RT-011)
- File: agent_sdk/console/static/a2ui.js:684
- Problem: inline slice + `moreColumnsNote` copy, against the C-059 "Reuses" rule.
- Fix: `capRows(items, limit = MAX_ROWS)`, `moreNote(items, limit = MAX_ROWS, noun = "")`; use `capRows(allColumns, MAX_COLUMNS)` and `moreNote(allColumns, MAX_COLUMNS, "columns")`; delete `moreColumnsNote`.

## Low

### D-06 "Node stays attached" assertion is vacuous (R1 RT-006, R2 RT-005)
- File: tests/test_gh214_no_delete_surface.py:111
- Problem: stub FNode has no `isConnected`, so `painted.isConnected !== false` is always true; node never attached. GH-244 item 4 untested.
- Fix: append `painted` to a root FNode before deleteSurface; assert `painted.parentNode === root` and `root.children.includes(painted)` after. Drop the `isConnected` read.
- Codify: assert only on fields the DOM stub maintains.

### D-07 Reset mid-stream leaks old-run output and surfaces (R1 RT-008, R2 RT-007)
- File: agent_sdk/console/static/chat.js:231 (Reset), :675 (`handleCustom(json)`)
- Problem: old run keeps painting bubbles, the `interrupted: ...` line and A2UI_UPDATE frames into the cleared transcript, and re-registers surfaceIds after `resetSurfaces()`.
- Fix: AbortController per sendAgui, aborted on Reset; minimum: readSse callback returns early when `state.threadId !== threadAtSend`. Node case: Reset mid-stream, then A2UI_UPDATE gives no render and no registry entry.

### D-08 Thread-change test does not change thread mid-stream (R1 RT-010, R2 RT-017)
- File: tests/test_gh234_agui_chat_driver.py:414
- Problem: `state.threadId` changes in onPost, before any frame; GH-243 AC item 1 asks for a change from a frame callback.
- Fix: add `onFrame(i)` hook to the readSse stub; change thread after TEXT_MESSAGE_CONTENT, before RUN_FINISHED; assert empty history, null pendingInterrupt, no live form.

### D-09 MultiCategoryChart notes unlabelled and scale counts hidden categories (R1 RT-009, R2 RT-010)
- File: agent_sdk/console/static/a2ui.js:867 (notes), :838 (totals)
- Problem: two bare "N more" notes; `totals` sum all categories incl. capped ones, so stacks never reach the top.
- Fix: "N more periods" / "N more categories" via parameterised moreNote (D-05); compute totals over capped `categories` with the same `Math.abs` the bars use.

### D-10 MultiCategoryChart product still up to 10,000 rects (R2 RT-009)
- File: agent_sdk/console/static/a2ui.js:832
- Problem: periods and categories each capped at MAX_ROWS; untrusted counts still drive DOM size (GH-244 item 1).
- Fix: cap categories low (6 colour classes or ~12) or cap periods x categories at a fixed total; update DESIGN.md §7.1 and the C-059 row.

### D-11 Resume click silently ignored while busy (R2 RT-008)
- File: agent_sdk/console/static/chat.js:509
- Problem: `runExclusive` returns with no feedback; looks like a dead button.
- Fix: set the form's `err.textContent` to "busy, try again when the run finishes", or disable submit while busy.

### D-12 Time-series cap drops newest points (R2 RT-012)
- File: agent_sdk/console/static/a2ui.js:624
- Problem: keeps first 100 points; right axis label looks like series end.
- Fix: keep last MAX_ROWS (`slice(-MAX_ROWS)`) or downsample evenly; say which in the note; update DESIGN.md §7.1.

### D-13 Generic renderer does not cap the number of table sections (R2 RT-013)
- File: agent_sdk/console/static/a2ui.js:487
- Problem: thousands of array-of-object keys paint thousands of 100-row tables; DESIGN.md §7.1 omits this gap.
- Fix: capRows over row-array keys plus "N more sections" note, or document the gap in §7.1.

### D-14 Dead `existing.closed` branch; createSurface after delete re-opens (R2 RT-014)
- File: agent_sdk/console/static/a2ui.js:137
- Problem: deleteSurface sets `closed` then deletes the entry, so the branch never runs; replayed createSurface paints a second node, contradicting DESIGN.md §5.4/§7.1.
- Fix: keep a closed-surfaceId Set (cleared by resetSurfaces) and reject, or delete the branch and document re-open. Add a node test.

### D-15 DESIGN.md §7.1 claims ChildList template expansion is supported (R2 RT-015)
- File: DESIGN.md:467
- Problem: a2ui.js header says it is out of scope (display-only renderer).
- Fix: say ChildList template expansion is out of scope, matching a2ui.js.

### D-16 Source-only tests needlessly marked @needs_node (R2 RT-016)
- File: tests/test_gh239_console_caps.py:114 (and test_no_spread_over_payload_arrays, line 173)
- Problem: they read source text only, but skip without node, incl. the "no Math.max(...spread)" guard.
- Fix: remove @needs_node from both.

---
Filed 2026-10-25 by /sdk-autoloop cycle 1: verified still-present mediums (and lows sharing a fix) are in #251–#260. Other lows stay here, unfiled.
