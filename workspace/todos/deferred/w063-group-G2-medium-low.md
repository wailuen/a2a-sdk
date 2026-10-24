# w063 — unit:G2 — deferred medium/low findings

- Wave: w063
- Scope: unit:G2
- Date: 2026-10-24

> Non-blocking — these did not block w063's archive. Address opportunistically or fold into a future wave.

Findings were collected across all redteam rounds and deduped by file + description. IDs restart each round, so the round-local IDs are kept next to a stable `G2-NN` key. Close overlaps are marked "see also".

## Medium

### G2-01 (RT-002, round 1) — chat.js:557 — reset during retry restores stale interrupt
- Quote: `    if (!resp) {`
- Problem: postWithRetry can wait seconds (1s/2s/4s back-off, or Retry-After up to 30s each time). If the user clicks Reset session during that wait, reset clears pendingInterrupt and sets a new threadId, then this branch puts the old interrupt back. The next message in the fresh session is sent as a resume POST with a stale interruptId.
- Fix: save `const threadAtSend = state.threadId` before the POST; restore only `if (resumed && state.threadId === threadAtSend && pendingInterrupt === null)`. Or bump a reset generation counter and check it.
- Codify: Any state restored after an await must check that the session it belongs to was not reset in the meantime.
- sdkCandidate: true

### G2-02 (RT-003 round 1 + RT-001 later round) — agent_sdk/testing/chat.py:272 — chunk without messageId keyed under ""
- Quote: `                    reply_parts.setdefault(str(frame.get("messageId") or ""), []).append(delta)`
- Problem: In AG-UI, TEXT_MESSAGE_CHUNK only needs messageId on the first chunk; later chunks with no id continue the open message. The driver keys missing ids under "", so CHUNK(a,'Hel') + CHUNK(no id,'lo') returns 'Hel\nlo' instead of 'Hello'. Misses AC "TEXT_MESSAGE_CHUNK is handled like START+CONTENT for its messageId".
- Fix: track current_chunk_id; for TEXT_MESSAGE_CHUNK use `frame.get('messageId') or current_chunk_id`, update it when an id is present, close the current one on a new id. Add a test with an id-less continuation chunk expecting 'Hello'.
- Codify: TEXT_MESSAGE_CHUNK messageId is optional after the first chunk; consumers must carry the current message forward, not key on a missing id.
- sdkCandidate: true
- See also: G2-03 (same bug in console).

### G2-03 (RT-002, later round) — chat.js:584 (also noted at :580) — console chunk without messageId opens second bubble
- Quote: `              let buf = textBuffers.get(json.messageId);`
- Problem: a continuation TEXT_MESSAGE_CHUNK with no messageId opens a second bubble under key undefined; after the run an entry `{id: undefined, role: 'assistant'}` is added to history and sent on the next run.
- Fix: keep lastChunkId; resolve `const mid = json.messageId ?? (json.type === 'TEXT_MESSAGE_CHUNK' ? lastChunkId : undefined)` before lookup; set lastChunkId whenever a chunk carries an id.
- Codify: Console AG-UI handlers must resolve an omitted chunk messageId to the open chunk message before keying any buffer or history entry.
- sdkCandidate: true

### G2-04 (RT-004 round 1 at :719 + RT-003 later round at :721) — chat.js — chunk-only history fold: wrong order, partial text kept
- Quotes: `      if (buf) state.aguiMessages.push({ id, role: "assistant", content: buf.text() });` / `    for (const id of chunkOpen) {`
- Problem: (a) chunk-only messages are added to state.aguiMessages only after processStream ends, so they land after START/END messages (chunk 'a', tool call, START/END 'b' gives history [b, a]) and the next turn sends an out-of-order conversation. (b) The fold ignores the `terminal` flag, so partial text is added after RUN_ERROR or a dropped stream. START/CONTENT with no END is never added, and chat.py never returns partial text, so the clients disagree — opposite of the GH-234 rule in chat.py.
- Fix: add a chunk message to history when a different messageId or a non-text event closes it (spec auto-close), or reserve a placeholder index at first chunk. Add still-open ones at RUN_FINISHED; skip them on RUN_ERROR, dropped stream, or no terminal event.
- Codify: When the client owns AG-UI history, add messages in arrival order and only on a successful RUN_FINISHED, never as a pass after the stream ends; follow the same partial-text rule as the other message paths.
- sdkCandidate: true

### G2-05 (RT-005 round 1 at :179 + RT-004 later round at :173) — tests/test_gh234_agui_chat_driver.py — console tests are string greps
- Quotes: `    assert "TEXT_MESSAGE_CHUNK" in chat` / `def test_console_static_changes():`
- Problem: 'TEXT_MESSAGE_CHUNK' was already in chat.js at HEAD, so the assert passed before the fix; `"resetSurfaces" in chat` passes from the import alone. Nothing checks the pendingInterrupt restore, the chunk-only fold, that Reset clears painted surfaces, that a failed resume lets the user retry, or that a2ui.js dropped `components`. G2-03 and G2-04 passed these tests unnoticed.
- Fix: minimum — assert specific new code (`resetSurfaces();` inside the resetBtn handler, `if (resumed) pendingInterrupt = resumed`, the chunkOpen fold, absence of `components: []` / `entry.components =` in a2ui.js). Better — node-run tests with the existing DOM shim (as in test_gh215_console_generic_renderer.py, test_a2ui_wire.py): (1) paint a surface, resetSurfaces(), confirm a createSurface with the same surfaceId paints and is not rejected as duplicate; (2) drive chat.js stream handling (or an extracted pure function) with chunk-only, mixed, and RUN_ERROR streams and check state.aguiMessages.
- Codify: A console behavior fix needs a test that runs the code in node; a grep for a string is not proof that an acceptance criterion is met.
- sdkCandidate: true

## Low

### G2-06 (RT-006, both rounds) — agent_sdk/console/static/a2ui.js:27 — stale surfaces Map comment
- Quote: `/* surfaceId -> {catalogId, components: [], dataModel: {}, node, closed} */`
- Problem: still lists the removed `components: []` field and omits `_componentMap`, now the only component store.
- Fix: `/* surfaceId -> {catalogId, _componentMap: Map<id, component>, dataModel: {}, node, closed} */`. Optionally use `entry._componentMap.get("root")` in paintSurface instead of building an array and calling find.
- sdkCandidate: true

### G2-07 (RT-007, round 1) — agent_sdk/testing/chat.py:163 — agui_turn/agui_resume docstrings miss new return contract
- Quote: `        for multi-turn continuity.  Returns the assistant reply text.`
- Problem: agui_turn now returns "" whenever the stream did not end with RUN_FINISHED, even if text streamed. Docstrings of agui_turn and agui_resume do not say so; the class docstring for the `error` emit omits the fixed 'stream closed without a terminal event' message.
- Fix: document that the method returns "" and does not append to *messages* on RUN_ERROR or no terminal event, that partial text arrives only via the `text` emit, and list the fixed no-terminal error text under the `error` emit key.
- sdkCandidate: true

### G2-08 (RT-005, later round) — chat.js:560 — duplicate Resume form after failed resume
- Quote: `        if (formFields(resumed.responseSchema)) interruptForm(resumed);`
- Problem: if the interrupt has form fields but the user answered in the main text box, the original form stays. If the resume POST fails, the restore adds a second Resume form for the same interrupt.
- Fix: re-show the form only when the failed send came from the form (`payloadOverride !== undefined`), or remove any existing interrupt form first.
- sdkCandidate: true

### G2-09 (RT-007, later round) — tests/test_gh234_agui_chat_driver.py:133 — credential-leak test gaps
- Quote: `        except httpx.HTTPStatusError as exc:`
- Problem: in the http_error case nothing checks that HTTPStatusError was raised; if the driver swallowed the 500 the text checks are skipped and the test still passes. Also the AC asked for `credentials={'k': sentinel}` arriving only in X-Agent-Credentials, but the test passes `credentials={'X-Agent-Credentials': SECRET}` (line 50) because ChatDriver's credentials is a raw header map; that difference is undocumented.
- Fix: wrap the http_error call in `pytest.raises(httpx.HTTPStatusError)` and check str/repr on the caught exception. Note in the test docstring that credentials= is a header map (SC-E1).
- sdkCandidate: true
