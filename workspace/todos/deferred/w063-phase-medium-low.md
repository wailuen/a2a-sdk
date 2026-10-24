# w063 — phase — deferred medium/low findings

- Wave: w063
- Scope: phase
- Date: 2026-10-24

Non-blocking — these did not block w063's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — agent_sdk/testing/chat.py:272
Quote: `reply_parts.setdefault(str(frame.get("messageId") or ""), []).append(delta)`

TEXT_MESSAGE_CHUNK handling keys each chunk by its own messageId, but AG-UI only requires messageId on the FIRST chunk of a message (harness/agents/ag-ui-advisor.md:81); later chunks that omit it are filed under the "" key and joined with "\n", splitting one message in two. Verified: chunks [{messageId:'a',delta:'Hel'},{delta:'lo'}] + RUN_FINISHED return 'Hel\nlo' instead of 'Hello'.

- Fix: Track the current chunk message id: use frame['messageId'] when present and remember it; when absent, append to the last chunk message id. Add a test with a chunk that omits messageId after the first one, asserting 'Hello'.
- Codify: AG-UI TEXT_MESSAGE_CHUNK carries messageId only on the first chunk; a consumer must inherit the open message id for later chunks, never key by the per-frame field.
- SDK candidate: yes

## RT-002 (medium) — agent_sdk/console/static/chat.js:584
Quote: `let buf = textBuffers.get(json.messageId);`

Console chunk handling has the same defect: a TEXT_MESSAGE_CHUNK that omits messageId (spec-legal after the first chunk) misses the existing buffer, opens a second streaming bubble keyed `undefined`, and later folds a second assistant history entry with no id, so one message is shown and replayed as two.

- Fix: Keep a `currentChunkId` variable; for TEXT_MESSAGE_CHUNK use `json.messageId ?? currentChunkId` as the key and update currentChunkId when messageId is present. Mirror the chat.py fix so both consumers agree.
- Codify: Every AG-UI consumer in the SDK (chat.py and chat.js) must resolve a chunk's message id the same way: inherit the open chunk message when messageId is absent.
- SDK candidate: yes

## RT-003 (medium) — agent_sdk/console/static/chat.js:721
Quote: `for (const id of chunkOpen) {`

Chunk-only messages are folded into state.aguiMessages after processStream() no matter how the run ended (RUN_ERROR, dropped stream, or no terminal event), so partial assistant text enters the client-owned history and is replayed on the next turn; START/CONTENT messages without END are NOT folded, and the same wave made chat.py refuse partial replies, so the two paths now disagree on what counts as a reply.

- Fix: Track `errored` in the RUN_ERROR case and fold chunkOpen entries only when the run ended with RUN_FINISHED (terminal && !errored && not dropped); otherwise discard them, matching both the START/CONTENT path and chat.py's `if not finished: return ""` rule.
- Codify: When one wave tightens 'partial reply is not a reply' on one AG-UI consumer, apply the same terminal-event gate to every sibling consumer's history fold.
- SDK candidate: yes

## RT-004 (low) — agent_sdk/console/static/chat.js:560
Quote: `if (formFields(resumed.responseSchema)) interruptForm(resumed);`

The failed-resume restore runs unconditionally: when the resume was sent by typing (the original form is only removed on its own submit) it appends a second identical Resume form, and when 'Reset session' is clicked while postWithRetry is still backing off it resurrects the old thread's interrupt into the new session, so the next send becomes a resume POST with a stale interruptId on a new threadId.

- Fix: Capture `const threadAtSend = state.threadId` before the POST and restore only when `state.threadId === threadAtSend && pendingInterrupt === null`; keep a reference to the currently shown interrupt form and remove it when a resume is sent (by text or form) so the restore never duplicates it.
- SDK candidate: yes

## RT-005 (low) — tests/test_gh234_agui_chat_driver.py:185
Quote: `block = chat[start:start + 400]`

Every GH-234 console AC (resetSurfaces clearing the registry, surface entry no longer holding a component list, failed-resume restore, chunk folding) is checked only by source-text substring/slice greps, which pass on dead or wrong code and break on harmless reformatting; the repo already has a live-node cross-check pattern (tests/test_card_console.py RT-004) that this wave did not use.

- Fix: Add node-executed tests (skip when node is absent): import a2ui.js, paint a surface, call resetSurfaces(), assert a follow-up updateComponents for that surfaceId is dropped as unknown; and extract sendAgui's restore/fold logic (or drive it with a stubbed postWithRetry/readSse) to assert pendingInterrupt is restored and chunk-only text is folded only on RUN_FINISHED.
- SDK candidate: yes

## RT-006 (low) — agent_sdk/testing/chat.py:163
Quote: `for multi-turn continuity.  Returns the assistant reply text.`

agui_turn (and agui_resume) docstrings still promise the assistant reply text, but _run_agui now returns "" whenever the stream did not end with RUN_FINISHED (unterminated or RUN_ERROR) and joins separate messageIds with "\n"; callers of this provisional API get no in-code statement of the new contract.

- Fix: Update both docstrings: returns the reply only when the run ended with RUN_FINISHED (messages joined with "\n"); returns "" after RUN_ERROR or a stream with no terminal event, with partial text still delivered via the `text` emit and nothing appended to messages.
- SDK candidate: yes

## RT-007 (low) — tests/test_gh233_workflow_scripts_parse.py:42
Quote: `assert result.returncode == 0, f"{path.name} has a JS syntax error"`

The failure message drops node's stderr (the line and caret that locate the error) and uses path.name, which is ambiguous because wave-cycle.js exists in harness/workflows, .claude/workflows and template/.claude/workflows.

- Fix: Use the repo-relative path and include result.stderr in the assertion message, e.g. `f"{path.relative_to(REPO_ROOT)} has a JS syntax error:\n{result.stderr}"`.
- SDK candidate: yes

## Release-gate (v0.20.1) ag-ui-advisor lows — open

- chat.js folds START/CONTENT/END messages into history at END time, before the run's outcome is known; chat.py appends nothing after RUN_ERROR (`agent_sdk/console/static/chat.js:600-607`). Hold folds until RUN_FINISHED.
- Typing a resume while the form shows, then a failed POST, renders a second form (`chat.js:557`). Track and remove the current form node.
- An id-less chunk with no earlier chunk id is folded with `id: undefined` (`chat.js:586-596`, `:731-734`). Use `uuid()` or skip.
- chat.py ignores `TEXT_MESSAGE_START.role` (non-assistant text joins the reply) and leaves the user message in `messages` after a failed turn (`agent_sdk/testing/chat.py:153`, `:274-285`).

Fixed at the gate: empty messages add no "\n" separator; chunk id resets on TEXT_MESSAGE_START/END (chat.py and chat.js).
