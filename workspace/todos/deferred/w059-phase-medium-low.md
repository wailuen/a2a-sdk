# w059 — phase — deferred medium/low findings

- Wave: w059
- Scope: phase
- Date: 2026-10-22

Non-blocking — these did not block w059's archive. Address opportunistically or fold into a future wave.

## Medium

### RT-003 — agent_sdk/testing/turns.py
- Finding: [SDK] line 205 `at.failed = bool(errors) and not at.reply`: an AG-UI attempt that streams some text and then ends in RUN_ERROR (not rate-limit text) is classified as a success. The partial reply is returned as ok=True, and the user+assistant pair is saved to the messages state file, so a failed run gets judge-scored as a completed turn.
- Fix: Treat any RUN_ERROR frame as a failed attempt whatever the partial text, e.g. `at.failed = bool(errors)`. Optionally carry the GH-220 RUN_ERROR.code through the emit to classify rate_limited. Add a test where text deltas are followed by RUN_ERROR.
- Codify: A run-level error frame means the turn failed even when text streamed before it. Classifiers must not let a partial reply hide a terminal error.
- SDK candidate: yes

### RT-004 — agent_sdk/testing/turns.py
- Finding: [SDK] line 110 `elif self.status is not None: self.reason = "http-error"`: every non-2xx status (401/403/400/404/500) and every transport error counts as a failed attempt, and the loop retries it with back-off for the full 540 s budget. The AC limits retries to 429, rate-limit text, a failed task or an empty reply. A wrong key file or a down agent makes each turn of each scenario spin for 9 minutes inside one of 3 shared slots, which stalls the whole acceptance run.
- Fix: Retry only on 429, rate-limit text, failed task, empty reply and (optionally) transport errors or 5xx with a small cap. Return at once on 4xx other than 429 with failureClass 'turn-failed'. Add a test that a 401 makes exactly one attempt.
- Codify: Retry helpers must name the statuses they retry. A catch-all retry turns a configuration error into a budget-long stall.
- SDK candidate: yes

### RT-005 — harness/workflows/acceptance-api.js
- Finding: [SDK] line 114 `ACC_QUERY="QUERY_TEXT" .venv/bin/python3 -m agent_sdk.testing.turns ...` tells scenario agents to put the user query inside shell double quotes. A query with `$`, a backtick or `"` (e.g. 'revenue above $5M') is expanded or broken by the shell, so the agent receives a silently changed query ('$5M' becomes 'M'). The same shape is at the AG-UI prompt (~157) and in the acceptance SKILL.md, and it is mirrored to the template.
- Fix: Have the helper read the query from a file or stdin (e.g. `--query-file` or a heredoc with a quoted delimiter `<<'Q'`), or tell agents to use single quotes with `'\''` escaping. Update both prompts, the skills and the template mirror together.
- Codify: Never splice free-form user or scenario text into a shell double-quoted string. Pass it through a file, stdin or a quoted heredoc.
- SDK candidate: yes

### RT-006 — agent_sdk/testing/mcp.py
- Finding: [SDK] line 99 `raise McpError("mcp JSON-RPC error")`: run_gate calls client.call_tool (line 205) without catching McpError. A sample whose args fail tool input validation (JSON-RPC -32602, no isError result) or an HTTP error on one call aborts the whole gate. The CLI prints only 'FAIL: mcp JSON-RPC error', without the tool name or sample= args. The AC requires the stop to name the tool and its args.
- Fix: In run_gate, wrap call_tool in try/except McpError. Append a failure `tool {name} args {json}: tools/call JSON-RPC error` (still no raw body) and return. Add a test with a sample that fails schema validation.
- Codify: Gate output must name the failing item on every failure path, including protocol-level errors, not only on the isError result path.
- SDK candidate: yes

### RT-007 — harness/workflows/wave-cycle.js
- Finding: [SDK] line 533 `def fresh(g): return since is not None and any(... os.path.getmtime(m)>since ...)`: a pattern Creates: path (e.g. workspace/learning/LRN-NNN-*.md) passes only when a match is newer than this run's Implement start. When a wave is re-run after a partial run, a pattern deliverable written in the earlier run is older than `since`, and an implementer that sees it already exists does not touch it. The group is then marked INCOMPLETE, its dependents are pruned and archive is blocked for good. The same logic is in .claude/workflows/sdk-wave.js.
- Fix: For pattern paths, accept a match that is tracked or untracked-but-new relative to the wave's base commit (e.g. `git log`/`git status` against the commit before the wave), not only mtime > this run's start. Or record the pattern match in the todo body on first delivery. Add a resume test.
- Codify: A freshness check keyed to one run's start time must still work for a resumed run. Key it to the wave's base commit instead.
- SDK candidate: yes

### RT-008 — harness/workflows/wave-cycle.js
- Finding: [SDK] line 473 TODO_SCAN_PY only recognises todos written as `- [ ] `ID``, with the id in backticks. A hand-edited todo without backticks (`- [ ] P1-01 ...`) is not in todoFacts. Its HUMAN GATE marker and Depends: text are then never seen, and the cross-check only catches scan ids that the model missed, not the reverse. So the hold fails open for that todo. The same logic is in .claude/workflows/sdk-wave.js.
- Fix: Also fail Parse when a todo id the model parsed is absent from todoFacts (the model→scan direction). Or widen TODO to accept an unquoted leading id token. Add a test with a non-backtick HUMAN GATE todo.
- Codify: A deterministic cross-check between a script and a model parse must run in both directions, or the gate fails open on whatever the script cannot see.
- SDK candidate: yes

### RT-009 — DESIGN.md
- Finding: [SDK] line 340 '- Terminal: `RUN_FINISHED` or `RUN_ERROR`, exactly one.' DESIGN §5.3 never mentions the new GH-220 wire facts: RUN_ERROR.code from the ErrorCategory vocabulary, and RUN_FINISHED always carrying outcome {type:'success'}. Only docs/protocols.md was updated, so the design spec no longer matches the wire (the LRN-425 principle).
- Fix: Add to the §5.3 terminal bullet: RUN_ERROR carries `code` (ErrorCategory value; validation/not_found/internal for route-level errors; never built from client input), and RUN_FINISHED always carries `outcome`.
- Codify: Each wire-shape change must update DESIGN.md's protocol section in the same todo, not only docs/.
- SDK candidate: yes

### RT-010 — agent_sdk/routes/a2a.py
- Finding: [SDK] line 1104 `def cancel_task_record(record: TaskRecord, store: Any) -> None:` is a new shared teardown helper. The AG-UI route (ag_ui.py line 58) imports it, and future out-of-loop cancel paths must reuse it. It is not registered in workspace/components/README.md, and neither are MCP_INTERRUPT_SUFFIX, SlotLimiter or McpClient. Its `store: Any` annotation also drops the TaskStore type.
- Fix: Register cancel_task_record as a C-NNN component with its contract: it takes an identity-scoped TaskRecord, commits CANCELED through C-019 and repairs through C-018. Type `store` as TaskStore. Register the other three reusable helpers or say why they are not components.
- SDK candidate: yes

## Low

### RT-011 — agent_sdk/agent/events.py
- Finding: [SDK] line 86 adds `code: str | None = None` to ToolResultEvent, and CHANGELOG announces it as a new public field. No producer in loop.py or runner.py ever sets it, and no consumer reads it. The GH-220 todo scoped only DoneEvent.code. This is dead public API surface.
- Fix: Remove ToolResultEvent.code and its CHANGELOG mention, or populate it from AgentError.category at the loop's tool-failure sites and consume it, with a test.
- SDK candidate: yes

### RT-012 — agent_sdk/routes/ag_ui.py
- Finding: [SDK] line 494 `event.code or "internal"`: cancel_task_record (a2a.py ~1174) publishes DoneEvent(ok=False, error=_CANCELLED_RUN_ERROR_TEXT) with no code. A user tasks/cancel seen by an AG-UI subscriber therefore yields RUN_ERROR code 'internal', which tells clients the server faulted. docs/protocols.md does not document what code a cancellation gets.
- Fix: Give the cancel DoneEvent a fixed documented code. ErrorCategory has no 'cancelled', so either add one with a ruling or document that cancellation maps to 'internal'. Add a test.
- SDK candidate: yes

### RT-013 — agent_sdk/testing/mcp.py
- Finding: [SDK] McpClient._post never sends the MCP-Protocol-Version header after initialize. MCP 2025-06-18 Transports says the client MUST send it on all later requests. The gate only passes because the server's GH-200 absent-header fallback covers it, so the acceptance gate never exercises the header path real clients (Claude.ai) use.
- Fix: Store result['protocolVersion'] from initialize and send it as MCP-Protocol-Version on every later POST. Add a test that the header is sent.
- SDK candidate: yes

### RT-014 — agent_sdk/console/static/chat.js
- Finding: [SDK] line 493 `form.addEventListener("submit", ...)` calls sendAgui("", r.payload) without checking that this form's interrupt is still the pending one. A stale form left in the transcript after a newer interrupt resumes the new interrupt with the old schema's payload. After the pending interrupt is consumed, it falls into the non-resume branch and posts an empty user message (payloadOverride is ignored there).
- Fix: Capture the interruptId in the form closure. On submit, proceed only if pendingInterrupt?.interruptId matches; otherwise show 'this prompt is no longer active' and remove the form. Also remove any open form when a new interrupt or run starts.
- SDK candidate: yes

### RT-015 — agent_sdk/console/static/interrupt.js
- Finding: [SDK] coerceValue enum matching is exact and case-sensitive (`String(v) === text`). For ActionGate's DEFAULT_CONFIRM_SCHEMA (enum approved/rejected), typing 'Approved', 'approve' or 'yes' in the console now gives a local error and sends nothing. Before, that text reached parse_decision, whose vocabulary already classifies those answers.
- Fix: Compare enums case-insensitively. Optionally, when a single-field schema has an enum, fall back to sending the raw text in that field so the server-side vocabulary classifies it. Add a test for 'Approved'.
- SDK candidate: yes

### RT-016 — agent_sdk/console/static/a2ui.js
- Finding: [SDK] line 680 renderBarChart still draws one row per bar with no cap (SVG height = bars.length * rowH), and the GH-215 AC says every list/table renderer caps rows with the shared MAX_ROWS constant. The generic renderer's key/value table (renderGeneric scalarRows) is also uncapped.
- Fix: Apply capRows/moreNote to BarChart bars and to the generic scalar rows, or record in the todo why charts are exempt.
- SDK candidate: yes

### RT-017 — workspace/learning/LRN-455-stale-redteam-findings.md
- Finding: [SDK] line 20 says 'Findings whose quote is gone are dropped'. The landed rule (wave-cycle.js/sdk-wave.js dropStaleFindings, harness redteam.md line 175) drops a finding only when the quote was seen present in an earlier round. The LRN Prevention text, the CHANGELOG GH-211 entry and the template redteam.md copy all describe the older, simpler rule. harness/skills/acceptance/SKILL.md line 319 also says the helper persists to /tmp/acc-{RUN_KEY}-*.txt, but turns.py defaults to tempfile.gettempdir(), which is not /tmp on macOS.
- Fix: Update LRN-455 Prevention, the CHANGELOG GH-211 entry and the template redteam.md to the 'seen present earlier, gone now' rule. Fix the SKILL path text or have acceptance-api.js pass --state-dir /tmp.
- SDK candidate: yes
