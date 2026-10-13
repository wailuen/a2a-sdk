wave: w046
group: G2
date: 2026-10-13
status: non-blocking (medium/low)

Non-blocking — these did not block w046's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every unit redteam round for group G2 and deduped by file+description. Redteam IDs restart each round, so each heading carries its round label (R1..R3, in the order the rounds ran). Many findings recur across rounds with different wording. They are kept separately because their descriptions differ; the theme index below groups them. All R1 and R3 findings are flagged sdkCandidate; no R2 finding is.

## Theme index

1. AG-UI GH-159 check covers only list-shaped content; dict-shaped (single-object) non-text content passes `_validate` and is `str()`-coerced into model text by `_fold_history` (binary/base64 payload leaks to the model): R1 RT-003, R3 RT-001
2. DESIGN.md not updated where the behavior lives: §5.1 lacks text-only input rule (-32005/415, -32602 empty text); A2A error table -32005 row lacks non-TextPart input; §5.3 line 339 "History processing (not rejection)" contradicted: R1 RT-004, R2 RT-002, R3 RT-003
3. GH-159 resume tests use a non-existent taskId, only on `:send`; no real input-required task, no `:stream` resume, no HTTP status, no proof interrupt stays pending; AG-UI tests thin (payload echo, history turn, dict content, labels): R1 RT-005, R2 RT-004, R3 RT-006
4. CHANGELOG files GH-159 (and GH-158) behavior changes under `### Fixed` with inline note, not `### ⚠️ Behavior changes` + migration note; release should be a minor bump (0.11.0): R1 RT-006
5. `contrib/action_gate/gate.py` `parse_decision` docstring still says DataPart/FilePart-only resume arrives as "" -> UNCLEAR; A2A input-required `responseSchema` invites DataPart replies that are now rejected; docs/protocols.md does not say A2A resumes must be TextPart: R2 RT-003, R3 RT-005
6. docs/protocols.md:32 "Nothing is silently dropped" and CHANGELOG overclaim; only the newest user message is checked, replayed history non-text parts are dropped, resume runs skipped: R2 RT-005, R3 RT-002
7. `_validate` docstring self-contradiction: RT-001 paragraph still says content is never hard-rejected: R2 RT-006, R3 RT-007
8. `_task_count` test helper returns None when store lacks `_records`, making "no task created" asserts vacuous: R2 RT-007, R3 RT-009
9. `_KNOWN_PART_TYPES` omits `video`, so a video part is labelled "unknown": R2 RT-008, R3 RT-008
10. A2A text-only check runs in `_parse_send` before the public `Agent.set_sync_reply` hook; undocumented public-API behavior change: R3 RT-004
11. AG-UI still accepts an empty/whitespace newest user message (A2A rejects with -32602); AG-UI rejection path emits RUN_STARTED + STATE_SNAPSHOT before RUN_ERROR, which AC/CHANGELOG do not state: R3 RT-010

## Findings

### R1 RT-003 [SDK] — medium — agent_sdk/routes/ag_ui.py
Non-text content can bypass the rejection when it is sent as one object instead of a list. If content is a dict such as {'type':'binary','data':...}, _validate skips it (the 'if not isinstance(content, list): continue' at line 105). _fold_history then runs str(content) on it (lines 103-105) and sends the Python repr to the model. Probe confirmed the model received 'SECRETBYTES' from the binary data field. This breaks the 'no silent drop / reject non-text' AC: the binary payload is turned into text instead of rejected.
- Fix: In _validate, reject user content that is neither a str nor a list ('user message content must be a string or a list of parts'). Or treat a dict as a one-item list and run the same part-type check. Add a test for dict-shaped content.
- sdkCandidate: true

### R1 RT-004 [SDK] — medium — DESIGN.md
The design doc was not updated in the sections that own this behavior. §5.1 'Inbound Message validation' (line 268) still lists only the messageId rule. It does not mention text-only input, -32005/415 for FilePart/DataPart, or -32602 for empty text. §5.3 still says 'History processing (not rejection)' and 'RUN_ERROR is reserved for agent-side failures, not large-but-valid client history', which the new AG-UI rejection contradicts. GH-159 appears only as a parenthetical inside the GH-128 §5.4 paragraph.
- Fix: Add the text-only inbound rule, with its error codes and its ordering (after model validation, before task creation, covering send/stream/resume), to §5.1 next to the messageId rule. Add a GH-159 bullet to §5.3 that says which user message is checked (after the RT-001 fix) and that the result is RUN_ERROR.
- sdkCandidate: true

### R1 RT-005 [SDK] — medium — tests/test_gh159_reject_non_text_parts.py
Tests do not cover several ACs. (1) The 'resume' and 'stream' cases are combined: the only resume test posts to /v1/message:send with a missing taskId 'no-such-task'. message:stream resume is never tested, and no test uses a real interrupted task to show that a rejected non-text or empty resume leaves the interrupt pending and resumable. (2) AG-UI covers only one list-shaped binary part. It does not check that the 'AAAA' data is absent from the response, and it does not test a replayed-history turn, dict-shaped content, or the label limits.
- Fix: Add an interrupted-task fixture (e.g. via contrib.action_gate) and assert -32005/-32602 on both /v1/message:send and /v1/message:stream resume, with the task still in input-required afterwards. Add AG-UI tests for: payload not echoed, history containing an earlier non-text turn (after the RT-001 fix), dict content, and a long or odd type label.
- sdkCandidate: true

### R1 RT-006 [SDK] — low — CHANGELOG.md
GH-159 rejects A2A and AG-UI inputs that used to be accepted (any FilePart/DataPart, even mixed with text, and empty-text resumes). The entry files this under '### Fixed' with an inline 'Behavior change:' note. It has no '⚠️ Behavior changes' heading and no migration guidance, which goes against the heading rule in earlier releases (RT-007, LRN-153). A patch bump at /sdk-release would understate the change.
- Fix: Move the GH-159 entry (and GH-158's) under a '### ⚠️ Behavior changes' heading in [Unreleased], with a one-line migration note for clients that send FilePart/DataPart or empty-text resumes. Cut the release as a minor bump (0.11.0).
- sdkCandidate: true

### R2 RT-002 — medium — DESIGN.md
DESIGN.md was only patched in the §5.4 A2UI paragraph. The A2A error table (line 288) still lists -32005 ContentTypeNotSupported only for 'unacceptable acceptedOutputModes', with no row for non-TextPart input. §5.1 does not state that input is text-only or that empty text is -32602. §5.3 line 339 still says 'History processing (not rejection)... RUN_ERROR is reserved for agent-side failures', which GH-159's newest-user-part RUN_ERROR now contradicts.
- Fix: Extend the -32005 table row to 'unacceptable acceptedOutputModes; any inbound FilePart/DataPart (GH-159, HTTP 415)'. Add the -32602 empty-text rule to §5.1. Amend §5.3 line 339 to carve out the newest-user-message non-text part rejection, noting that replayed history is still folded, not rejected.

### R2 RT-003 — medium — agent_sdk/contrib/action_gate/gate.py
This file depends on the A2A resume value. Its parse_decision docstring (lines 126-128) still says 'a resume carrying only a DataPart/FilePart arrives as "" -> UNCLEAR', which is now false: that resume is rejected with -32005/415 before deliver_resume. Also, the A2A input-required status metadata (runner.py:1375) advertises an object-typed responseSchema, which invites a schema-following A2A client to reply with a DataPart. Every such reply is now hard-rejected, and docs/protocols.md does not say that A2A resumes must be TextPart text.
- Fix: Update the gate.py docstring: A2A resume is text-only, and a non-text resume is rejected at the route with 415 while the interrupt stays pending. In docs/protocols.md (interrupt/resume paragraph), state that A2A resumes must carry a TextPart and that responseSchema describes the AG-UI payload only.

### R2 RT-004 — medium — tests/test_gh159_reject_non_text_parts.py
test_resume_rejects_non_text_and_empty posts taskId='no-such-task', so it never puts a real task into the interrupted state. It never covers the message:stream resume path. It does not assert the HTTP status. It does not prove the AC 'an empty string can no longer resume a task', i.e. that a real interrupted task stays input-required and deliver_resume is never called.
- Fix: Drive a tool that raises ToolInterrupt (as example publish_note does) until the task is input-required. Then send FilePart-only and empty-text resumes on both /v1/message:send and /v1/message:stream. Assert 415/-32005 and 400/-32602, assert the task is still input-required, and assert a later text resume still succeeds.

### R2 RT-005 — low — docs/protocols.md
docs/protocols.md:32 says 'Nothing is silently dropped', and the CHANGELOG GH-159 entry says 'AG-UI user messages with non-text content parts now end in RUN_ERROR'. In fact only the newest user message is checked. Non-text parts in older replayed user messages are still silently dropped by _fold_history (the intended ruling, but the docs overclaim).
- Fix: Reword both to: 'the newest user message is rejected if it has non-text parts; non-text parts in replayed history are folded out, not rejected (so a thread is never bricked)'.

### R2 RT-006 — low — agent_sdk/routes/ag_ui.py
The _validate docstring contradicts itself. The new GH-159 paragraph says the newest user message's non-text parts are rejected. The next, unchanged paragraph still says 'Message CONTENT is never hard-rejected — not on control characters, not on unexpected part shapes (RT-001)'.
- Fix: Edit the RT-001 paragraph so it says content is never rejected EXCEPT for the GH-159 newest-user non-text check, and explain why that check cannot brick a thread: it ignores history and skips resume runs.

### R2 RT-007 — low — tests/test_gh159_reject_non_text_parts.py
_task_count returns None when the store has no _records attribute. Every 'no task created' assertion (assert _task_count(app) == before) then becomes None == None and passes vacuously if the store implementation or attribute name changes.
- Fix: Assert isinstance(app.state.task_store, InMemoryTaskStore) (or use a public count/list_tasks_for_identity) inside _task_count so it can never return None silently.

### R2 RT-008 — low — agent_sdk/routes/ag_ui.py
_KNOWN_PART_TYPES = {binary, image, audio, file, document} omits 'video', which AG-UI multimodal input content also defines, so a video part is reported as 'unknown'. The error is safe but less clear than the AC's 'clear error naming the part type'.
- Fix: Add 'video' to the allowlist after checking it against the pinned AG-UI input-content types, and cite the source of the list in a comment.

### R3 RT-001 [SDK] — medium — agent_sdk/routes/ag_ui.py
The GH-159 AG-UI check only looks at list-shaped content. A user message whose content is a single object (e.g. {"type":"image","data":"<base64>","mimeType":"image/png"}) passes _validate (line ~165 only checks isinstance(content, list)). _fold_history line 106 then turns it into text with str(content), so the raw base64 payload is sent to the model as text instead of being rejected. Confirmed: _validate returns None and _fold_history yields "{'type': 'image', 'data': 'QUJDREVG', ...}". The AC 'no silent drop' is not met for this shape.
- Fix: In _validate, for the newest user message, reject any content that is neither a str nor a list (or a dict whose type is not 'text') using the same allowlisted label path. Add a test that dict-shaped non-text content gets RUN_ERROR and creates no task.
- Codify: A content-type gate must cover every shape the history fold coerces, not just the canonical list shape; otherwise the coercion path becomes a bypass.
- sdkCandidate: true

### R3 RT-002 [SDK] — medium — docs/protocols.md
docs/protocols.md:32 says 'Nothing is silently dropped', and the CHANGELOG [Unreleased] GH-159 entry says AG-UI user messages with non-text parts end in RUN_ERROR. The code only checks the NEWEST user message and skips the check on resume runs. Non-text parts in earlier user messages are still silently dropped by _fold_history. tests/test_gh159_reject_non_text_parts.py:81 (test_agui_history_non_text_does_not_brick_thread) pins that drop as intended behavior. The published docs contradict both the code and the test.
- Fix: Reword docs/protocols.md and the CHANGELOG entry: AG-UI rejects non-text parts in the newest user message (the new input of this run). Non-text parts in replayed history are dropped so a session cannot be bricked. Resume runs are not checked. Remove 'Nothing is silently dropped', or limit it to A2A.
- sdkCandidate: true

### R3 RT-003 [SDK] — medium — DESIGN.md
DESIGN.md only gets a parenthetical inside §5.4's A2UI GH-128 bullet (line ~358). §5.1 (A2A) has no statement of the text-only input rule or the -32005/415 and -32602 mapping. §5.3 line 339 still says 'History processing (not rejection) ... RUN_ERROR is reserved for agent-side failures, not large-but-valid client history'. That is now inaccurate: client content in the newest user message triggers RUN_ERROR, with a newest-only, skip-on-resume scope. The design doc no longer describes the AG-UI validation contract.
- Fix: Add a GH-159 bullet to §5.1: text-only input, any non-TextPart gets -32005/HTTP 415 naming the kind only, empty text gets -32602, checked in _parse_send before config, resume and task creation. Add one to §5.3: newest-user-message check, allowlisted label, history drop, resume skip. Amend line 339 to match.
- sdkCandidate: true

### R3 RT-004 [SDK] — medium — agent_sdk/routes/a2a.py
_unsupported_input_error runs inside _parse_send (line 443), before the public Agent.set_sync_reply hook (app.py:205) is called in message_send. A downstream agent whose sync_reply hook handled FilePart/DataPart messages or empty pings now gets -32005/-32602 before its hook runs. No task is created on that path, so the AC did not require this ordering. The CHANGELOG 'Behavior change' note does not mention the sync_reply hook, so this is an undocumented change to public API behavior.
- Fix: Either document in the CHANGELOG and in the set_sync_reply docstring that the hook now only ever receives text-only, non-empty messages, or move the check after the sync_reply branch (still before _create_task_record and resume). Add a test pinning the chosen order.
- sdkCandidate: true

### R3 RT-005 [SDK] — medium — agent_sdk/contrib/action_gate/gate.py
This file consumes the A2A resume value. The parse_decision docstring (lines 126-128) says 'the route extracts TextPart text only, so a resume carrying only a DataPart/FilePart arrives as "" -> UNCLEAR'. After GH-159 that cannot happen. The route rejects such a resume with -32005 (or -32602 for empty text), and the interrupt stays pending. The stale docstring misleads gate authors about what A2A resume values can arrive.
- Fix: Update the docstring: A2A resume values are always non-empty text. Non-text or empty resumes are rejected at the route (GH-159) and never reach the handler.
- sdkCandidate: true

### R3 RT-006 [SDK] — medium — tests/test_gh159_reject_non_text_parts.py
test_resume_rejects_non_text_and_empty (line 50) only posts to a taskId that does not exist ('no-such-task'), and only on /v1/message:send. It never creates a real input-required task. So it does not prove the AC 'an empty string can no longer resume a task': that deliver_resume is not called and the interrupt stays pending and resumable afterwards. The /v1/message:stream resume branch, which opens a subscription before _resume_or_error, has no resume rejection test at all.
- Fix: Add tests that park a real task in input-required (tool raising ToolInterrupt). Send a FilePart-only resume and an empty-text resume on both :send and :stream. Assert -32005/-32602, that the task is still input-required, and that a later text resume succeeds.
- sdkCandidate: true

### R3 RT-007 [SDK] — low — agent_sdk/routes/ag_ui.py
The _validate docstring (line ~145) still says 'Message CONTENT is never hard-rejected — not on control characters, not on unexpected part shapes (RT-001)'. The new code rejects unexpected part shapes in the newest user message: a non-dict list entry, {"text":"hi"} with no type, or {"type":"TEXT"} all give RUN_ERROR 'unknown'. The prepended GH-159 paragraph and the RT-001 paragraph contradict each other.
- Fix: Rewrite the RT-001 paragraph: replayed history content is never hard-rejected; the newest user message's part types are (GH-159).
- sdkCandidate: true

### R3 RT-008 [SDK] — low — agent_sdk/routes/ag_ui.py
_KNOWN_PART_TYPES (line 127) = {binary, image, audio, file, document} leaves out 'video', one of AG-UI's multimodal input content types. A video part is rejected (correctly) but labelled 'unknown', which gives the client a less clear error.
- Fix: Add 'video' to the allowlist and add a test case for it.
- sdkCandidate: true

### R3 RT-009 [SDK] — low — tests/test_gh159_reject_non_text_parts.py
_task_count (line 17) returns None when the store has no _records attribute. The 'no task created' checks (assert _task_count(app) == before) then compare None == None and pass without checking anything. A store swap in the fixture would quietly turn off the key AC assertion.
- Fix: Assert the count is not None (or use a public store count or listing API) so the check fails loudly instead of passing without checking.
- sdkCandidate: true

### R3 RT-010 [SDK] — low — agent_sdk/routes/ag_ui.py
GH-159 now rejects empty text on A2A (-32602), but AG-UI still accepts a newest user message whose text is empty or whitespace (e.g. [{"type":"text","text":""}]). Confirmed: _validate returns None and _fold_history yields {'text': ''}. A task is created and the empty block goes to the model, which providers commonly reject. The run fails later with a generic RUN_ERROR instead of a clear validation error. Also, the AC wording 'rejected before a run starts' does not match the chosen path: RUN_STARTED and STATE_SNAPSHOT are emitted before RUN_ERROR. That path is allowed by §5.3, but the AC and CHANGELOG do not say so.
- Fix: Optionally reject an empty newest user message in _validate with a fixed message, matching A2A. State in the CHANGELOG/docs that AG-UI rejection is RUN_STARTED, then RUN_ERROR, with no task created.
- sdkCandidate: true
