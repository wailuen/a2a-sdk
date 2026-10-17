wave: w055
group: A4
date: 2026-10-17

Non-blocking — these did not block w055's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group A4. All findings are
SDK-level (sdkCandidate: true). Context: GH-193 (A2A interrupt resume accepts a single
application/json DataPart, delivered to resume_handler as {"status": None, "payload": data}).

## Findings

### RT-001
- severity: medium
- file: agent_sdk/example/agent.py
- description: The reworked publish_note confirmed() reads only top-level status, or payload.status when status is None. It never reads payload.decision. So the SDK's own console AG-UI resume ({status:"resolved", payload:{decision:text}}, agent_sdk/console/static/chat.js:491) always declines. An A2A DataPart resume in the shape GH-193's tests and CHANGELOG present as canonical ({"decision":"approved"}) also declines. Reading payload.status is also the nested-status pattern that action_gate documents as blocked. No test covers the example handler on the DataPart path.
- fix: Classify the resume value with agent_sdk.contrib.action_gate.gate.parse_decision, or also read payload.decision (decision first, then status per the advertised responseSchema). Add a test: A2A DataPart {"status":"approved"} and the console AG-UI shape {status:'resolved', payload:{decision:'yes'}} both publish, and a bare 'resolved' declines.
- codify: When a resume handler is changed to accept structured payloads, test it against every first-party resume shape (console AG-UI, A2A DataPart, A2A text), not only the shape its responseSchema advertises.

### RT-002
- severity: medium
- file: agent_sdk/contrib/action_gate/gate.py
- description: The module docstring (lines 4-7) and the parse_decision docstring (lines 126-129) still say A2A always delivers a plain string, and that a resume carrying only a DataPart arrives as "" and is UNCLEAR. After GH-193, a DataPart resume arrives as {"status": None, "payload": data} and can APPROVE via payload.decision. This is the security contract that downstream gate authors rely on, and it is now wrong. The CHANGELOG says 'action_gate needs no change', yet its docs needed one.
- fix: Update both docstrings: A2A text resumes give a str, and an A2A single-DataPart resume gives {status: None, payload: <data>}, classified exactly like AG-UI (payload.decision approves, payload.status is never read). Cite GH-193.
- codify: When a transport's resume value shape changes, grep contrib/ and docs for prose describing the old shape (e.g. 'plain string', 'arrives as ""') and update it in the same change.

### RT-003
- severity: medium
- file: agent_sdk/routes/agent_card.py
- description: The agent card still advertises defaultInputModes ["text/plain"] only. docs/protocols.md:32 still opens 'Input is text only'. DESIGN.md:360 still says routes/a2a.py 'rejects any non-TextPart ... so even a well-formed object DataPart is refused'. Yet interrupt resumes now accept an application/json DataPart. Neither DESIGN.md nor any decision record notes the card-vs-behavior gap or how a client discovers the structured-resume path (the responseSchema in the input-required status metadata).
- fix: Add a DESIGN.md entry (GH-193 ruling URL) saying DataPart input is interrupt-scoped, deliberately not in defaultInputModes, and discoverable via the interrupt's responseSchema metadata. Correct the DESIGN.md:360 parenthetical. Reword the opening sentence of docs/protocols.md so 'text only' is scoped to fresh messages.
- codify: Any narrowing of an input-mode rule must update the agent-card rationale and every DESIGN.md sentence that restates the old rule, or record why the card intentionally differs.

### RT-004
- severity: medium
- file: tests/test_gh193_data_part_resume.py
- description: AC 'A DataPart resume on a working or unknown task keeps today's error order and never reveals whether the task exists' (SI-5 annotation) is tested only for an unknown task on message:send. Untested: a working task (expect 501 -32004), a terminal task, another identity's task (expect 404, same as unknown, including the DataPart+FilePart and DataPart+TextPart shapes), and every refusal shape on message:stream. The stream path claims an admission slot via _open_stream before _resume_or_error validates the parts. A manual probe confirmed today's behavior is correct, but nothing pins it.
- fix: Add parametrized tests over {send, stream} x {working, terminal, foreign, unknown} x {[DATA], [DATA, FilePart], [DATA, TEXT]}, asserting identical status/code for foreign and unknown. Also add the bad-shape matrix on message:stream, asserting the task stays input-required and no stream slot leaks.
- codify: An existence-non-leak AC needs a foreign-identity test on every route that implements it, not just an unknown-id test on one route.

### RT-005
- severity: low
- file: docs/protocols.md
- description: Lines 32-39 run the new GH-193 resume rule into the existing AG-UI sentence with semicolons ('... any other mixed or repeated shape is `-32602`; AG-UI rejects non-text ...'). This makes the trailing '(maintainer ruling on GH-159)' look like the citation for the GH-193 rule. The GH-193 ruling URL is not cited, and the error order (part check runs after the task-state checks) is not documented.
- fix: Split into separate sentences or a paragraph. Cite https://github.com/wailuen/a2a-sdk/issues/193#issuecomment-6229360550. State that the part check runs after the 404/501 task-state checks for DataPart resumes, while a FilePart-only resume is still refused at parse time with -32005.

### RT-006
- severity: low
- file: agent_sdk/routes/a2a.py
- description: _resume_value is annotated `Any | JSONResponse`, which collapses to Any. Mypy cannot check that callers handle the error branch, and the str/dict contract given to resume_handler is not expressed in the type.
- fix: Annotate as `str | dict[str, Any] | JSONResponse`, or return a (value, error) pair, so the isinstance narrowing in _resume_or_error is checked.

### RT-007
- severity: low
- file: CHANGELOG.md
- description: The GH-193 entry sits after a stray blank line inside the `### Changed` list, which splits the Markdown list in two. Some renderers then show it as a separate loose list.
- fix: Remove the blank line before the GH-193 bullet. Also fix the 'action_gate needs no change' claim alongside RT-002 (say the docstrings were updated).
