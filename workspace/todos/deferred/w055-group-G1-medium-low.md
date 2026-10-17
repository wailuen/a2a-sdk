wave: w055
group: G1
date: 2026-10-17

Non-blocking — these did not block w055's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.
All findings are SDK-level (sdkCandidate: true). Context: GH-188..GH-198 (catalogs from emits, blocking send,
push config not supported, console retry policy, AG-UI malformed body, DataPart resume, empty-reply retry,
ChatDriver AG-UI resume, reject unknown tool args, A2A stream heartbeat, OAuth known redirect hops).

## Findings

### RT-001
- severity: medium
- file: agent_sdk/routes/ag_ui.py (root cause in agent_sdk/common/json_strict.py)
- description: Raised in two rounds. `_parse_body` (~line 517) catches only JSONDecodeError/ValueError. A deeply nested body well under the 1 MB cap (for example b'[' * 100000 or 200000) makes `loads_strict` raise RecursionError. It escapes before the StreamingResponse exists and gives an HTTP 500, not the GH-192 RUN_STARTED then RUN_ERROR 'malformed RunAgentInput body'. Verified with `_parse_body(b'['*200000)` and with the test client. This breaks DESIGN.md §5.3 ("the route handler never raises before the StreamingResponse exists"). `loads_strict` is shared, so the A2A and MCP ingress paths have the same hole.
- fix: In agent_sdk/common/json_strict.py:loads_strict, catch RecursionError and re-raise json.JSONDecodeError with a fixed message such as 'nesting too deep' (no excerpt, per SI-2), so every route's existing parse-error branch handles it. (Minimum alternative: catch RecursionError in `_parse_body` and return None.) Add b'[' * 100000 and b'{"a":' * 100000 to the parametrize list in tests/test_gh192_ag_ui_malformed_body.py, expecting RUN_STARTED followed by RUN_ERROR 'malformed RunAgentInput body'.

### RT-002
- severity: medium
- file: tests/test_gh195_chatdriver_agui_resume.py (also docs/testing.md:158, agent_sdk/example/agent.py:75-85)
- description: Raised in two rounds. The GH-195 acceptance check says to call agui_resume(id, payload={"decision": "approved"}) and expect RUN_FINISHED success. The test calls status="approved" (line 31) instead, and docs/testing.md teaches a form that, against the shipped example, declines silently. The example `publish_note.confirmed()` reads only status and payload.status, never payload.decision. `agui_resume` defaults to status="resolved" (which the console also always sends, chat.js:491), so the standard AG-UI shape returns {published: False, reason: 'user declined'}. The test never checks the payload reached the tool, never checks the tool result content, and never checks that RUN_FINISHED was a success rather than a second interrupt; it only checks `tool_done`, the scripted fake-model text, and that no error fired.
- fix: Call agui_resume(interrupt_id, ..., payload={"decision": "approved"}) exactly as the acceptance check says. Make example `confirmed()` read payload.decision/payload.status before the envelope's AG-UI `status` field (example/agent.py belongs to group A4, so coordinate), or script a tool whose resume handler goes through the action_gate. Assert the tool result content (capture TOOL_CALL_RESULT or the persisted task tool message), assert RUN_FINISHED with no interrupt outcome, and assert the interrupt emit did not fire again during the resume. In docs/testing.md, show the standard status="resolved" + payload.decision form, or label status="approved" as the SDK shorthand.
- codify: A test for an acceptance check must call the exact form the check specifies; switching to a shorthand that happens to pass can hide a real failure of the standard protocol shape.

### RT-003
- severity: medium
- file: agent_sdk/console/static/retry.js
- description: Raised in three rounds. On any non-retried failure, 401/403 included, `postWithRetry` calls traceFrame(`HTTP ${resp.status}`, await resp.text()) (~line 57-61), writing the raw server error body into the trace panel, which is part of the page. The GH-191 SI-5 note says the 401/403 failure must not render server error bodies into the page. The status-only system line is compliant; the trace write is not.
- fix: For 401/403 (or for all non-retried statuses), trace only the status or a fixed label such as `HTTP 401 (body not shown)`, or a short error code from parsed JSON. Do not read or render `resp.text()`. Add a node-driver case to tests/test_gh191_console_retry_policy.py that records traceFrame calls and checks no body is passed on 401/403.
- codify: When a todo carries an SI note about what may reach the page, check every place that writes to the page (the trace and debug panels too), not just the visible error line.

### RT-004
- severity: medium
- file: agent_sdk/testing/chat.py
- description: Raised in two rounds. `_run_agui` (~line 212-217) calls self._client.stream("POST", "/ag-ui/run", json=body) without self._merged_headers(). The SC-E1 `credentials` constructor option is documented as injected into every outbound request and is honoured on all A2A calls, but never reaches AG-UI. The new public `agui_resume` inherits the gap, so a test against an agent that needs X-Agent-Credentials cannot turn or resume over AG-UI.
- fix: Pass headers=self._merged_headers() to the client.stream call in `_run_agui`. Add a test that builds ChatDriver(credentials={...}) and checks the header arrives on both agui_turn and agui_resume (httpx MockTransport or a route spy).
- codify: When a shared helper is pulled out of an existing method, check that it still honours every class-wide promise (such as credential headers) on all transports.

### RT-005
- severity: low
- file: agent_sdk/console/static/chat.js
- description: Raised in two rounds. `sendAgui` sets pendingInterrupt = null (~line 479) before postWithRetry. GH-191 now fails right away on 400/401/403/404/413/415/422, and after 3 tries on 429/503. When a resume POST fails, the interrupt is dropped: the user's next message silently starts a fresh run, and the interrupted task waits until it expires.
- fix: Keep the pending interrupt until postWithRetry returns an OK response. If it returns null, restore pendingInterrupt so the user can resend the resume after fixing the key or waiting out the 429.

### RT-006
- severity: low
- file: agent_sdk/console/static/chat.js
- description: In the A2A send path (`sendA2a`, `await readSse(...)` ~line 384), a stream drop has no catch. The rejection becomes an unhandled promise error, and the user never sees the 'stream dropped. The run may still finish on the server. It was not resent.' line the AG-UI path now shows. GH-191's SI note asks for the same no-replay handling on A2A.
- fix: Wrap the A2A `readSse` in try/catch. On a drop before `final:true`, show the same 'not resent' system line, set sawFinal-equivalent state so the 'closed without final' line is not duplicated, and never re-POST.

### RT-007
- severity: low
- file: agent_sdk/console/static/chat.js
- description: processStream's catch (~line 647) also catches errors thrown by the frame handlers themselves (for example a rendering bug in handleCustom or renderA2ui) and reports them as 'stream dropped. The run may still finish on the server', pointing a developer at the wrong cause. The processStream closure (~line 516) is left over from the old reconnect recursion and is called exactly once.
- fix: Inline processStream. Tell a reader failure (network or stream) apart from an error thrown inside onFrame, and report the latter as a rendering error (error name only).

### RT-008
- severity: low
- file: agent_sdk/console/static/retry.js
- description: `parseRetryAfter` (~line 11) falls back to Date.parse for anything not all digits. In V8, Date.parse('1.5') or Date.parse('-3') returns a 2001 timestamp, so a malformed or fractional Retry-After becomes a 0 ms delay and an immediate retry, not the backoff the AC calls for when the header is missing or invalid.
- fix: Use Date.parse only for values that look like an HTTP-date (for example match /GMT$/ or a weekday prefix, per RFC 9110 §10.2.3); return null otherwise so the backoff applies. Add parseRetryAfter('1.5') === null to the node driver test.

### RT-009
- severity: low
- file: agent_sdk/console/static/retry.js
- description: postWithRetry re-sends after a network failure on both the A2A message:stream path and the AG-UI run path, with the same messageId/runId. A fetch rejection can happen after the server already accepted the request and created the task (connection drops before response headers). The re-POST then starts a second task and runs tools twice — the duplicate-side-effect risk GH-191 set out to remove.
- fix: Limit retries to 429/503 responses, which the server rejects before creating a task. Or retry a network failure only once and tell the user it may have been sent twice. At minimum document the remaining risk in the code comment.

### RT-010
- severity: low
- file: agent_sdk/routes/oauth.py
- description: Raised in three rounds. (a) Docs drift: the `_redirect_security_headers` docstring (~lines 430-465) and the module docstring (~lines 14-24) still say form-action is widened only to the validated redirect_uri origin; neither mentions the `_KNOWN_REDIRECT_HOPS` step (~line 470), which appends fixed server-side sources including a wildcard host-source. A future CSP auditor will not learn this from the function contract. (b) `_KNOWN_REDIRECT_HOPS` is matched against `_validated_origin` output, which keeps an explicit default port. A redirect_uri like https://global.consent.azure-apim.net:443/redirect/<id> rebuilds as '...:443', misses the exact-match key, and is again blocked at the regional 302. It fails safe (no wider access), but the GH-198 fix silently does not apply.
- fix: Add a sentence/paragraph to both docstrings: an exact-match key in `_KNOWN_REDIRECT_HOPS` appends its fixed server-side sources, and no client text is used. Drop :443 for https when building the lookup key (normalise in `_validated_origin` or before the lookup, or add the :443 variant as a second exact key), with a test case. Lookalike origins must still not match.

### RT-011
- severity: low
- file: CHANGELOG.md
- description: Raised in two rounds. (a) The GH-192 entry says RUN_STARTED is followed by RUN_ERROR, but the route emits STATE_SNAPSHOT between them. (b) The GH-195 entry (~line 10) says the AG-UI interrupt emit 'now receives the AG-UI interrupt dict', but the code did not change (it already passed interrupts[0]); only the docstring changed, so the entry wrongly suggests a behaviour change. (c) The GH-191 entry (~line 17) leaves out that the A2A message:stream send path now retries 429/503 and network errors, where before it never retried — new behaviour on a path that can trigger tool side effects. (d) A stray blank line sits between the GH-189 and GH-193 entries under Changed.
- fix: Change the GH-192 text to 'RUN_STARTED, STATE_SNAPSHOT, then RUN_ERROR' (or 'RUN_STARTED ... RUN_ERROR'). Reword GH-195 to say the docstring now documents that the AG-UI interrupt emit gets the interrupt dict (with id). Add to GH-191 that the A2A send path now uses the same retry policy. Remove the blank line.

### RT-012
- severity: low
- file: agent_sdk/console/static/retry.js (GH-191 todo scope)
- description: agent_sdk/console/static/retry.js is a new untracked file that GH-191's Creates list does not name, so scope-based review and release staging can miss it.
- fix: Add retry.js to the GH-191 todo's Creates list and make sure the release commit stages it (`git add agent_sdk/console/static/retry.js`).
