# w066 — deferred medium/low findings (unit:G1)

- Wave: w066
- Scope: unit:G1
- Date: 2026-10-25

Non-blocking — these did not block w066's archive. Address opportunistically or fold into a future wave.

Findings are deduped by file + description across all redteam rounds. Original round IDs are listed per item. All are sdkCandidate: true.

## Medium

### D-01 — chat.js CHUNK role recorded on a minted id (GH-254 item 1 parity)
- File: `agent_sdk/console/static/chat.js:661,671`
- Round IDs: RT-005 (r1), RT-003 (r2), RT-001 (r3)
- Issue: an id-less first TEXT_MESSAGE_CHUNK gets `chunkId = uuid()`, so `id` is truthy and a role like "tool" is recorded and the text dropped from history. chat.py:370 checks the raw `msg_id` (None) and keeps the text as the assistant reply. Probe: [CHUNK{delta:'x', role:'tool'}, RUN_FINISHED] -> chat.js folds nothing; ChatDriver returns 'x'.
- Fix: record a CHUNK role only when the frame itself carries a messageId (`explicitId = json.messageId !== undefined && json.messageId !== null && json.messageId !== ''`). Add a node test for an id-less (and empty-id) first CHUNK with role 'tool', asserting the text is folded as assistant.
- Codify: when console JS must match a Python driver, test id-less and empty-id frames; minted ids are truthy in JS but None in Python.

### D-02 — a2ui.js prints wire-supplied component name / surfaceId unclipped (GH-255 item 1)
- File: `agent_sdk/console/static/a2ui.js:238`
- Round IDs: RT-007 (r1), RT-002 (r3)
- Issue: fallback reasons and renderer notes (`unknown component ...`, `renderer failed`, `createSurface rejected ...`, `updateComponents/updateDataModel dropped ...`, `paint failed`) embed raw wire values. A 10,000-char component name paints a 10,019-char text node and a 10,043-char note, which chat.js prints via systemLine.
- Fix: wrap `root.component` and `surfaceId` in `clip(...)` in every notes.push and fallbackNode reason; clip fallbackText lines (MAX_LONG_TEXT / MAX_PROSE). Node test: 10,000-char component name and surfaceId, empty fallbackText, no note/text node over 256 chars.
- Codify: an "every printed string is clipped" rule also covers diagnostic notes and fallback reasons built from wire values.

### D-03 — DESIGN.md §7.2 out of date after GH-254
- File: `DESIGN.md:476`
- Round IDs: RT-002 (r2)
- Issue: still says a CHUNK role is taken on "the first chunk of an id"; code records it only before any buffered text. Missing: Reset aborts the request, stale frames/system lines dropped, guarded A2A contextId write-back, empty text skipped, minted id for an id-less buffer.
- Fix: update §7.2 to the GH-254 rules (role only before first buffered text, empty text skipped, minted id, Reset aborts via AbortController / postSse signal, stale-thread output dropped on both transports, contextId write-back skipped after Reset). Widen the GH-254 todo's Creates: list to include DESIGN.md §7.2.

### D-04 — thread-change test does not change thread mid-stream (GH-254 AC item 4)
- File: `tests/test_gh234_agui_chat_driver.py:423`
- Round IDs: RT-006 (r1)
- Issue: the test flips the thread in onPost (before any frame); the onFrame tests flip on the first frame. Nothing proves early frames are handled and later ones dropped.
- Fix: `let k = 0; onFrame = () => { if (++k === 3) state.threadId = 'T2'; }`; assert early frames were handled (run-started line or buffered text) while the RUN_FINISHED interrupt is not captured and nothing is folded.

### D-05 — deep-metadata regression test cannot fail (GH-253 item 1)
- File: `tests/test_gh235_nested_json_and_resume.py:340`
- Round IDs: RT-003 (r3)
- Issue: `test_a2a_deep_metadata_never_breaks_task_list` sends a body with no role/parts/messageId, so the route returns 400 (-32602 invalid message params) at any depth; a shallow body also gets 400. The test guards nothing.
- Fix: send a valid message (role, parts, messageId) with deep metadata; assert the specific depth error (e.g. `{'code': -32700, 'message': 'nesting too deep'}` or the route's fixed text) and MARKER not in r.text. Keep the GET /v1/tasks check; optionally add a below-cap control returning 200.
- Codify: a rejection test must assert the specific error code/message for the rule under test; a bare status code can be met by an unrelated validation failure.

## Low

### D-06 — leftover inline truncations bypass clip()
- File: `agent_sdk/console/static/a2ui.js:468,830,877`
- Round IDs: RT-008 (r1), RT-004 (r3)
- Issue: compactText (`slice(0, 200)`), waterfall axis label (`slice(0, 11)`) and multi-category axis label (`slice(0, 9)`) duplicate clip() without its surrogate-pair guard.
- Fix: `clip(text, 201)` (or 200 per clip semantics) in compactText; `clip(label, 12)` / `clip(label, 10)` for axis labels.
- Codify: after adding a shared truncation helper, grep for leftover `.slice(0, N)}…` patterns.

### D-07 — send() has its own silent busy check
- File: `agent_sdk/console/static/chat.js:869`
- Round IDs: RT-009 (r1), RT-006 (r3)
- Issue: `if (!text || state.busy) return;` returns silently; a typed resume or Enter while busy gets no busy note. C-081 guidance puts the busy note in the shared guard.
- Fix: drop `|| state.busy`; let runExclusive show the busy note; clear input.value only once runExclusive accepts the work.

### D-08 — Reset does not wake the retry back-off sleep
- File: `agent_sdk/console/static/retry.js:63`
- Round IDs: RT-010 (r1), RT-006 (r3)
- Issue: during a 429/503 Retry-After wait (up to MAX_DELAY_MS, 30 s) Reset aborts the fetch but not `await wait(delayMs)`, so the old run holds state.busy and the new session shows busy.
- Fix: pass the AbortSignal into postWithRetry; make wait end early on 'abort' (clear the timer) and return null with no further attempts.

### D-09 — A2A path lacks per-frame thread guard; threadAtSend read after await
- File: `agent_sdk/console/static/chat.js:396,423`
- Round IDs: RT-011 (r1), RT-004 (r2), RT-005 (r3)
- Issue: (a) the sendA2a readSse callback has no `state.threadId !== threadAtSend` guard (AG-UI has one), so stale output is dropped only because abort errors the stream. (b) sendA2a reads threadAtSend and signal after `await catalogIdsReady`; a Reset during that wait takes the new threadId with the aborted signal, and the fake 499 prints "stream request failed: HTTP 499" plus a trace into the fresh session.
- Fix: move threadAtSend/signal reads above `await catalogIdsReady` (or return early if `signal.aborted`); add `if (state.threadId !== threadAtSend) return;` at the top of the readSse callback and guard the trailing "stream closed without final:true" line. Node test: flip thread mid-stream on A2A, assert no later bubble/line.

### D-10 — no test covers the real abort chain
- File: `agent_sdk/console/static/chat.js:389`
- Round IDs: RT-005 (r2)
- Issue: node tests stub postWithRetry and postSse, so AbortError -> postAbortable fake 499 -> postWithRetry no-retry branch -> staleGuard suppression is never run. A retry.js change (retrying 499, treating it as network error) would go unnoticed.
- Fix: node test loading the real retry.js with a fetch stub that rejects on abort; abort mid-request; assert exactly one POST, no retry, no system line after threadId change.

### D-11 — C-081 registry row names a non-existent `guardedSend`
- File: `workspace/components/README.md:74`
- Round IDs: RT-006 (r2), RT-008 (r3)
- Issue: no `guardedSend` ever existed (`git log -S guardedSend` hits only workspace commits); the component is `runExclusive` (as DESIGN.md §7.2 says). Reuse greps find nothing.
- Fix: rename the row's symbol to `runExclusive`; note it owns the in-flight AbortController (state.abort) and the fixed busy note added by GH-254.

### D-12 — time-series cap is an inline slice, not capRows
- File: `agent_sdk/console/static/a2ui.js:642`
- Round IDs: RT-007 (r2)
- Issue: `allPoints.slice(-MAX_ROWS)` bypasses capRows/moreNote, contrary to DESIGN.md §7.1.
- Fix: add a keep-newest option (`capRows(items, limit, { tail: true })`) and use it, or amend §7.1.

### D-13 — closed-surface tombstones grow without limit
- File: `agent_sdk/console/static/a2ui.js:211`
- Round IDs: RT-008 (r2)
- Issue: deleted surfaces stay in `surfaces` with node=null; the isConnected sweep skips them, so create/delete pairs with fresh ids grow the map until resetSurfaces().
- Fix: keep closed ids in a capped Set (e.g. last 1,000) or prune oldest tombstones past a cap; add a test.

### D-14 — trendSpan reads prototype members for payload `dir`
- File: `agent_sdk/console/static/a2ui.js:595`
- Round IDs: RT-009 (r2)
- Issue: `ARROWS[dir]` with dir 'constructor' prints "function Object() { [native code] }" in the KPI card.
- Fix: `Object.prototype.hasOwnProperty.call(ARROWS, dir) ? ARROWS[dir] : ""` (or Map / Object.create(null)); node test with trend 'constructor'.

### D-15 — generic-sections cap test too loose
- File: `tests/test_gh239_console_caps.py:377`
- Round IDs: RT-010 (r2), RT-007 (r3)
- Issue: `assert 0 < len(tables) < 40` passes for 1..39; the note count is not checked, so MAX_SECTIONS = 10 is not pinned.
- Fix: assert `len(tables) == 10` and `"30 more sections" in _text(node)`.

---
Filed 2026-10-25 by /sdk-autoloop cycle 2: verified still-present mediums (and lows sharing a fix) are in #261–#267. Other lows stay here, unfiled.
