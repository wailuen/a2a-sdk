# w067 — unit:G1 — deferred medium/low findings

- Wave: w067
- Scope: unit:G1
- Date: 2026-10-25

Non-blocking — these did not block w067's archive. Address opportunistically or fold into a future wave.

## RT-003 (medium) — agent_sdk/console/static/a2ui.js:401
Quote: `for (const para of String(fallbackText).split(/\n/)) {`
- Problem: fallbackNode clips each fallback line to MAX_PROSE but caps neither the number of lines nor the total text, so a fallback text of many lines still paints an unbounded number of DOM nodes (e.g. 100k lines -> 100k divs); the per-line clip does not bound the output as GH-263 item 2 / C-059 intend, and test_fallback_text_lines_are_clipped only checks per-line length.
- Fix: Clip the whole fallbackText to MAX_PROSE first, then split, and cap the line list with capRows(lines) plus moreNote(lines.length - MAX_ROWS, 'lines'); add a test with >MAX_ROWS lines asserting the line count and the more-note.
- SDK candidate: yes

## RT-004 (medium) — workspace/components/README.md:81
Quote: `| C-088 | postSse abort signal | agent_sdk/console/static/api.js::postSse | present |`
- Problem: The new reusable exports `abortableSleep(ms, signal)` and the signal-aware `postWithRetry(doPost, {..., signal})` in agent_sdk/console/static/retry.js are not registered in the component registry (no row names retry.js, postWithRetry or abortableSleep), and C-088 still describes only postSse, so a future console action that posts a run has no registry pointer to the abortable back-off.
- Fix: Add a component row for `postWithRetry` / `decideRetry` / `abortableSleep` (agent_sdk/console/static/retry.js: 429/503 + network retry before the first SSE frame, back-off sleep woken by the run's AbortSignal, abort -> 499 -> no retry), or extend C-088 to say the same signal must be passed to postWithRetry.
- SDK candidate: yes

## RT-005 (low) — agent_sdk/console/static/a2ui.js:41
Quote: `for (const surfaceId of closed.slice(0, Math.max(0, closed.length - MAX_TOMBSTONES))) surfaces.delete(surfaceId);`
- Problem: pruneTombstones orders tombstones by Map insertion (surface creation), not by close time, so a long-lived surface closed most recently is the first one forgotten once 200 newer-created surfaces are closed, and a replayed createSurface for exactly that just-closed id is accepted; this contradicts the comment 'only the newest MAX_TOMBSTONES of them' and the CHANGELOG 'oldest forgotten first'.
- Fix: When a surface is closed in the deleteSurface loop, re-insert it (`surfaces.delete(id); surfaces.set(id, entry)`) so Map order is close order, and add a test that closes an early-created surface last and verifies its tombstone survives the prune.
- SDK candidate: yes

## RT-006 (low) — agent_sdk/console/static/retry.js:91
Quote: `} catch (_e) {`
- Problem: `waited()` treats every error from the wait function as an abort and makes postWithRetry return null silently; a non-abort failure of an injected sleep (or a future sleep bug) is swallowed with no system line, instead of only an AbortError being treated as Reset.
- Fix: Return false only when `_e && _e.name === "AbortError"` (or `signal && signal.aborted`); rethrow anything else so runExclusive reports it.
- SDK candidate: yes

## RT-007 (low) — agent_sdk/console/static/chat.js:700
Quote: ``systemLine(`tool args (raw): ${raw}`);``
- Problem: chat.js system lines still print wire values with no clip(): raw tool-call args (unbounded accumulated fragments), `run error: ${json.message}` at :740, `interrupted: ${fmtJson(interrupts)}`, tool names and task ids; GH-263's 'unclipped diagnostics' fix was applied to a2ui.js only, so the console's diagnostics are still unbounded on the chat side.
- Fix: Import clip (C-084) from a2ui.js into chat.js and wrap every wire value printed by systemLine (raw args with MAX_RAW, error/interrupt messages with MAX_LONG_TEXT, names/ids with MAX_TEXT).
- SDK candidate: yes

## RT-008 (low) — agent_sdk/console/static/chat.js:662
Quote: `if (id !== undefined && id !== null) chunkId = id;`
- Problem: A TEXT_MESSAGE_CHUNK with `messageId: ""` sets chunkId to "" and buffers under the empty key, while ChatDriver (agent_sdk/testing/chat.py:370, `if msg_id:`) treats an empty id as absent and inherits the previous chunk id, so the console and the test driver fold differently, contrary to the C-074 'track turns.py/chat.py parity' row.
- Fix: Use `if (id) chunkId = id; else { if (chunkId === undefined) chunkId = uuid(); id = chunkId; }` to match chat.py, and add a node test with an empty-string messageId following an id'd chunk.
- SDK candidate: yes

## RT-009 (low) — agent_sdk/console/static/a2ui.js:653
Quote: `const points = capRows([...allPoints].reverse()).reverse(); // newest MAX_ROWS, oldest first`
- Problem: Spreading `data.data` turns a malformed string payload into an array of characters and paints an empty chart with 'N points', where the previous code threw and showed the renderer-error fallback; the cap silently accepts a non-array wire value.
- Fix: Use `const allPoints = Array.isArray(data.data) ? data.data : [];` (or throw on non-array so paintSurface falls back) and keep the capRows/reverse cap.
- SDK candidate: yes

## RT-010 (low) — tests/test_gh234_agui_chat_driver.py:198
Quote: `const BUSY_NOTE = "busy: wait for the current run to finish";`
- Problem: The node harness defines its own BUSY_NOTE instead of extracting the constant from chat.js, so test_send_while_busy_shows_the_fixed_note_and_keeps_the_text compares the harness copy with itself and passes even if chat.js's BUSY_NOTE text changes or drifts.
- Fix: Extract the `const BUSY_NOTE = ...;` line from chat.js into the harness (as the functions are extracted) and assert its value once against the expected literal.
- SDK candidate: yes
