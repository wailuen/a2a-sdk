# w064 — group G3 — deferred medium/low findings

- Wave: w064
- Scope: unit:G3
- Date: 2026-10-24

Non-blocking — these did not block w064's archive. Address opportunistically or fold into a future wave.

Findings from every redteam round, deduped by file + description.

## Medium

### RT-001 — successful run after Reset session still writes into the new session
- File: agent_sdk/console/static/chat.js:741 — `for (const id of finished ? order : []) {`
- Problem: the thread check from GH-238 only covers a failed resume POST. A run that succeeds after Reset session still writes into the new session: the RUN_FINISHED fold (:741) pushes the old thread's assistant messages into the fresh state.aguiMessages, and the interrupt branch (:660) sets pendingInterrupt and shows a Resume form for the old thread. The next send is then a resume with a stale interruptId on the new threadId, which is the same bug GH-238 item 1 names.
- Fix: rename resumedThread to threadAtSend (it is already captured for every send at :520). Skip the fold, the interrupt capture and interruptForm when state.threadId !== threadAtSend. Add a node test where onPost or a frame callback changes state.threadId and FRAMES carry text plus an interrupt RUN_FINISHED; assert state.aguiMessages and pendingInterrupt stay empty.
- Codify: every async continuation in the console AG-UI client must re-check that the thread is unchanged before it mutates session state, not only the failure path.
- sdkCandidate: true

### RT-002 — Resume form submit bypasses the busy guard; stale form survives RUN_ERROR
- File: agent_sdk/console/static/chat.js:509 — `sendAgui("", r.payload);`
- Problem: the Resume form's submit calls sendAgui directly. It skips the state.busy guard in send() and has no try/catch, so a typed send can run at the same time as a form resume. RUN_ERROR (:671-673) clears pendingInterrupt but never calls removeInterruptForm(), so a Resume form from the other run can stay on screen with no pending interrupt. Submitting it takes the normal path: it posts an empty user message and silently drops the payload. A thrown error becomes an unhandled rejection with no systemLine.
- Fix: in the RUN_ERROR case call removeInterruptForm() next to pendingInterrupt = null. In the submit handler, return early unless pendingInterrupt === pending. Route the form submit through the same busy guard and try/catch as send(), for example a shared runExclusive(fn) helper.
- Codify: an interactive control that triggers a protocol request must go through the same concurrency guard as the main send path and must be removed whenever its backing state is cleared.
- sdkCandidate: true

### RT-003 — node-run console tests lack the CI loud-fail guard
- File: tests/test_gh234_agui_chat_driver.py:178 — `needs_node = pytest.mark.skipif(_NODE is None, reason="node is not installed")`
- Problem: the GH-242 AC says to follow the tests/test_card_console.py RT-004 pattern. That pattern includes a CI guard (test_live_handle_a2a_artifact_cross_check_available_in_ci) that fails loudly when node is missing in CI. test_gh234 and test_gh239_console_caps.py (line 21 pytestmark) only skip. The old source greps were deleted, so a CI runner without node now has zero coverage of the GH-238/GH-239 console behaviour, and the run still shows as passing.
- Fix: add a test_*_available_in_ci test to both files, matching test_card_console.py:291-300: when CI is truthy and node is absent, fail. Also make the module-level pytestmark in test_gh239 conditional so that guard test is not itself skipped.
- Codify: a node-run console test that replaces a source grep must carry the CI loud-fail guard, otherwise removing the grep silently drops coverage in CI.
- sdkCandidate: true

### RT-004 — GH-234 resetSurfaces / Reset session behaviour now untested
- File: tests/test_gh234_agui_chat_driver.py:177
- Problem: the rewrite deleted test_console_static_changes. It was the only test that checked GH-234's resetSurfaces export, the surfaces.clear() body and its wiring into chat.js Reset session (grep finds no other test mentioning resetSurfaces). No node-run replacement was added, so the GH-234 Reset behaviour (registry cleared, pendingInterrupt and shownForm cleared) is now untested.
- Fix: add a node test that drives a2ui.js: renderA2ui creates surface S, resetSurfaces() runs, then an updateDataModel for S reports 'unknown/closed surface S'. Add a chat.js harness case that runs the reset handler body and asserts pendingInterrupt === null and no live form remains.
- Codify: when a source-grep test is replaced by behavioural tests, every assertion it held must have a behavioural replacement or be removed on purpose with a note.
- sdkCandidate: true

### RT-005 — chat.js history rules no longer match chat.py (C-072)
- File: agent_sdk/console/static/chat.js:740 — `// after RUN_FINISHED (a partial reply is not a reply; chat.py agrees)`
- Problem: the comment claims chat.js matches chat.py, but the history rules differ after GH-237 changed C-072 in the same wave. (1) chat.js folds every START or chunk message as role 'assistant', even when the START carries role developer/system/user, and sends it back to the server mislabelled. chat.py filters these out. (2) A TEXT_MESSAGE_CONTENT with no START is dropped from both the display and history; chat.py counts it as assistant. (3) The user message is pushed into state.aguiMessages before the POST (:551) and kept after RUN_ERROR, a missing terminal event or a failed POST. chat.py now appends the user message only on RUN_FINISHED.
- Fix: either apply the C-072 rules in chat.js: record an explicit non-assistant role from START or the first CHUNK and leave it out of the fold; give CONTENT without a START a buffer; push the user message only on RUN_FINISHED, posting a copy (messages.slice() plus the user entry). Or change the comment to state the differences and record them in DESIGN.md §7. Add node tests for each case.
- Codify: when C-072 (chat.py) changes its history contract, the console chat.js mirror must change in the same wave or its parity comment must be removed.
- sdkCandidate: true

## Low

### RT-006 — CHANGELOG GH-238 bullet names chat.js by basename only
- File: CHANGELOG.md:15 — "- GH-238: console `chat.js` restores the interrupt after a failed resume POST ..."
- Problem: the wave rule says each CHANGELOG entry names every changed agent_sdk/ file by repo path (LRN-491). The GH-238 bullet names only the basename `chat.js`. `grep -F agent_sdk/console/static/chat.js` over the [Unreleased] section finds nothing.
- Fix: replace "console `chat.js`" with "console `agent_sdk/console/static/chat.js`".
- sdkCandidate: true

### RT-007 — test_gh239 assertion only checks for the word "dropped"
- File: tests/test_gh239_console_caps.py:95 — `assert res[1]["notes"] == [] or not any("dropped" in n for n in res[1]["notes"])`
- Problem: the first half of the `or` is implied by the second, so the assertion only checks for the word 'dropped'. It does not check that the update was applied. A regression that keeps the entry but ignores the updateDataModel value would still pass.
- Fix: assert that res[1]['notes'] has no 'unknown/closed surface p' entry, and that the repainted node's text shows the new value 2 (via _text).
- sdkCandidate: true

### RT-008 — only BarChart is capped; other chart renderers are not
- File: agent_sdk/console/static/a2ui.js:755 — `const segments = data.segments || [];`
- Problem: GH-239 capped BarChart because untrusted row counts drive DOM size. renderWaterfallChart (segments), renderMultiCategoryChart (periods x categories rects plus legend) and renderTimeSeriesChart (points) still draw every element with no cap. DESIGN.md §7.1 now says rendering is capped, which reads as broader than the code.
- Fix: apply capRows/moreNote to waterfall segments and multi-category periods, and either cap or downsample time-series points. Or narrow the DESIGN.md §7.1 sentence to list exactly which renderers are capped.
- sdkCandidate: true
