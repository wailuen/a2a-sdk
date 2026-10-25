# w067 — deferred medium/low findings (unit:G2)

- Wave: w067
- Scope: unit:G2
- Date: 2026-10-25

Non-blocking — these did not block w067's archive. Address opportunistically or fold into a future wave.

Findings are deduped by file + description across all redteam rounds. Round-local IDs repeated across rounds, so each entry lists the original IDs it merges.

## Medium

### D-01 CHANGELOG: GH-259 filtering entry not under Breaking (RT-007 r1)
- File: CHANGELOG.md:47
- Quote: `- GH-259: \`acceptedOutputModes\` is now applied to artifacts (...)`
- Issue: GH-261 item 6 ruling not done. Bullet still under v0.23.0 "### Changed"; GH-257 Breaking bullet (line 36) still names removed `_mode_accepted`.
- Fix: move bullet under v0.23.0 "### 🔴 Breaking changes"; replace `_mode_accepted` with `media_type_match` (agent_sdk/common/media.py). Or record a ratified ruling to leave released entries alone.

### D-02 docs: MCP void-result deviation documents the wrong case (RT-008 r1)
- File: docs/protocols.md:182
- Quote: `Deviation (GH-266): a tool with no \`emits\` returns an empty void result;`
- Issue: the real deviation is a tool that declares `emits` (advertises outputSchema) and returns None gets isError:false with no structuredContent, against MCP 2025-06-18 MUST. Parity reason missing.
- Fix: "Deviation (GH-266): a tool that declares `emits` (so `tools/list` advertises `outputSchema`) and returns `None` gets `isError: false`, an empty text block and no `structuredContent`, despite the spec's MUST; this matches the A2A/AG-UI fold of a void result to success (§5.6 parity, RT-001/RT-002)."

### D-03 docs: A2A -32004 → 400 not named as a spec deviation (RT-002 r3)
- File: docs/protocols.md:33; agent_sdk/routes/a2a.py (_resume_or_error ~:606-612, message_stream ~:1050-1054)
- Issue: A2A v0.3.0 (harness/reference/a2a-protocol-0_3_0.md:98) maps -32004 → 501. The 400 for wrong-state messages departs from it with no "Deviation (GH-266)" note and no code comment.
- Fix: add a Deviation sentence (spec says 501; SDK answers 400 per ruling URL; 501 means method not implemented at all). Add a one-line comment at the status=400 call sites.
- Codify: when a ruling moves a wire status off the cited protocol table, document it as a named deviation.

### D-04 docs/CHANGELOG/tests: not-awaiting-input 400 also applies to message:stream (RT-013 r1, RT-011 r2, RT-003 r3)
- Files: docs/protocols.md:34-35; CHANGELOG.md:13 (GH-266 Breaking entry); tests/test_gh266_protocol.py
- Issue: message:stream resume branch (a2a.py ~:1057) also calls _resume_or_error and returns 400 / -32004. Docs say message:send only; no test for the stream site.
- Fix: say "message:send or message:stream to a task that is not awaiting input → 400" in docs and CHANGELOG. Add `test_not_awaiting_input_stream_is_400`: create a WORKING task via task_store.create, POST /v1/message:stream with its taskId, assert (400, -32004) and no event-stream content type.
- Codify: when a status is chosen per call site, list and test every route that reaches the shared helper.

### D-05 runner: dead TextPart fallback in apply_output_modes (RT-009 r1)
- File: agent_sdk/agent/runner.py:447
- Quote: `texts = [p.text for p in artifact.parts if isinstance(p, TextPart)]`
- Issue: GH-261 item 7 low unfixed. `texts` is always empty here. FilePart-only artifact filtered with ['text/plain'] yields TextPart(text="").
- Fix: delete the line; build fallback only from DataParts (dumps_strict(p.data)); if nothing serializable remains, raise -32005 AgentError. Add FilePart-only unit test.

### D-06 runner: artifact metadata.mimeType deleted, not rewritten; branch untested (RT-008 r2, RT-001 r3)
- File: agent_sdk/agent/runner.py:457-461
- Quote: `update["metadata"] = {k: v for k, v in meta.items() if k != "mimeType"}`
- Issue: GH-261 item 4 ruling says "rewritten to match the kept parts"; code drops it. _build_capabilities makes the branch unreachable from build_artifact, so the only route test (test_header_optin_with_json_mode_completes_with_json_datapart) passes vacuously. Deleting lines 457-461 leaves the suite green.
- Fix: set mimeType to the kept parts' media type (or delete only for mixed types). Add direct apply_output_modes unit test: artifact with mimeType=application/a2ui+json, parts [TextPart, a2ui DataPart], filter ['text/plain'] → mimeType text/plain. Also check a kept part with no mimeType leaves no stale value.
- Codify: a metadata-rewrite test must start from an artifact holding the stale value; a branch made unreachable upstream needs a direct unit test.

### D-07 runner: deferred-tool -32005 path untested (RT-010 r1)
- File: agent_sdk/agent/runner.py:1212
- Quote: `if isinstance(exc, AgentError) and exc.a2a_code == -32005:`
- Issue: GH-261 item 7 low open; no test drives a DeferredResult whose artifact apply_output_modes rejects.
- Fix: in tests/test_gh259_a2a_route.py add a deferred_kpi flow with header opt-in and modes that keep nothing (e.g. ['application/a2ui+json'] with a client catalog leaving no translation). Assert task FAILED, status.error.code -32005, no artifacts.

### D-08 a2a: FAILED tail message built by hand with duplicated literal (RT-011 r1)
- File: agent_sdk/routes/a2a.py:964
- Quote: `parts=[TextPart(text="invalid agent response")],`
- Issue: GH-261 item 7 low unfixed. _unserializable_tail repeats the literal instead of using set_task_status's failed-message builder.
- Fix: use the same helper or a shared module constant.

### D-09 a2a/runner: resume modes travel in ResumeEnvelope, not record — AC mismatch (RT-007 r2, RT-004 r3)
- Files: agent_sdk/routes/a2a.py:624; agent_sdk/agent/runner.py:1347-1349; agent_sdk/tasks/store.py:283-285
- Quote: `ResumeEnvelope(value, identity, list(resume_modes) if resume_modes else None),`
- Issue: AC says _resume_or_error sets record.accepted_output_modes before deliver_resume. Code sends modes in the envelope; worker applies them. test_resume_modes_travel_in_envelope_not_record pins it. Design is arguably better (copy-on-get stores, losing resumer cannot overwrite) but no ruling or AC edit records it; archive gate checks AC text.
- Fix: keep code and record the deviation + rationale on the GH-261 todo / ruling comment; or also set record.accepted_output_modes for the live record (restore if deliver_resume returns False).
- Codify: picking a design other than the AC's needs an AC change or recorded ruling; tests pinning it are not enough.

### D-10 a2a: X-A2A-Extensions echoes A2UI when modes rule it out (RT-010 r2)
- File: agent_sdk/routes/a2a.py:757 (message:send) and :1088 (message:stream)
- Quote: `_echo_extensions(request, response)`
- Issue: header + acceptedOutputModes ["application/json"] can never get A2UI parts, yet A2UI URI is echoed as activated, breaking the module's RT-005 rule.
- Fix: omit A2UI_EXTENSION_URI when record.a2ui_opted_in is False or when record.accepted_output_modes is set and rejects application/a2ui+json. Add test: no A2UI echo for header + ["application/json"].
- Codify: when the A2UI decision gains an input, update the echo to use the same decision.

### D-11 store: a2ui_opted_in runtime-only field not in TaskStore contract (RT-013 r2)
- File: agent_sdk/tasks/store.py:123
- Quote: `a2ui_opted_in: bool = False`
- Issue: resume mode check reads it via store.get(). A custom store rebuilding TaskRecord from durable storage returns False → spurious 415 for ["application/a2ui+json"] on an opted-in task.
- Fix: document on TaskStore.get() and the field comment that accepted_output_modes and a2ui_opted_in must survive get() for a live task (or persist a2ui_opted_in). Add a store conformance contract test.
- Codify: runtime-only TaskRecord fields read via store.get() are part of the TaskStore contract.

### D-12 tests: A2UI-off test cannot fail after GH-261 (RT-009 r2)
- File: tests/test_gh257_single_a2ui_gate.py:130
- Quote: `json=_msg(configuration={"acceptedOutputModes": ["application/a2ui+json"]}),`
- Issue: without the header, -32005 happens even on an A2UI-on app, so removing app.state.a2ui_enabled gate leaves the test green.
- Fix: send headers={"X-A2A-Extensions": A2UI_EXTENSION_URI}; keep no-header case as a separate assertion if wanted.
- Codify: when a gate gains a second condition, re-check each "gate off" test still fails only because of its gate.

## Low

### D-13 errors: WireError.http_status() and a2a_error disagree; self-contradicting comment (RT-012 r1, RT-014 r2, RT-006 r3)
- File: agent_sdk/models/errors.py:50-59, :134
- Quote: `return A2A_HTTP_STATUS.get(self.code, 500)`
- Issue: a2a_error (common/wire_errors._CLIENT_CODE_HTTP) maps -32600/-32602/-32700 → 400, -32601 → 404; WireError.http_status() returns 500. Comment at :54-56 says -32601 intentionally falls back to 500, contradicting the GH-266 note below it.
- Fix: move _CLIENT_CODE_HTTP into models/errors.py next to A2A_HTTP_STATUS; use it in both (or delete unused http_status()). Keep -32000 on 500. Rewrite comment to describe one table.

### D-14 tests: docstring still pairs terminal-task -32004 with 501 (RT-014 r1, RT-012 r2)
- File: tests/test_w017_gh51_multiturn.py:177
- Quote: `for this caller), never -32004 UnsupportedOperation/501 (RT-002/GH-144).`
- Issue: GH-266 AC grep for "501" must find no terminal re-addressing as 501; line not on the allowed list.
- Fix: "never -32004 UnsupportedOperation/400 (RT-002/GH-144, GH-266)".
- Codify: after a status-code change, run the AC sweep grep and fix comments/docstrings too (LRN-197).

### D-15 a2a: duplicate X-A2A-Extensions A2UI parse (RT-015 r1, RT-007 r3)
- File: agent_sdk/routes/a2a.py:383-385 (vs _a2ui_header at :429-431)
- Quote: `if A2UI_EXTENSION_URI not in [u.strip() for u in requested.split(",")]:`
- Fix: in _echo_a2ui_if_present use `if not _a2ui_header(request): return` (move helper above if needed).

### D-16 tests: __import__ hack, mid-module imports, weak losing-resume test (RT-016 r1, RT-015 r2, RT-008 r3)
- File: tests/test_gh259_a2a_route.py:376-377, :508, :530
- Quote: `for f in (__import__("tests.conftest", fromlist=["x"]).sse_frames(r.text))`; `assert sorted([r1.status_code, r2.status_code])[0] == 200`
- Issue: dynamic import fragile under other rootdir/import modes; GH-261 block adds noqa E402 mid-module imports; losing-resume test never asserts the loser was rejected; `before = record.accepted_output_modes` (:508) unused.
- Fix: add sse_frames to `from .conftest import wait_for_state`; move GH-261 imports (DeferredResult, ToolSet, Agent, example tools, KpiCard, MetricItem) to the header; assert loser is an error (404 -32001 or 400 -32004); delete unused `before`.

### D-17 tests: test_card_state_and_runtime_agree skips runtime half for emitting=False (RT-016 r2, RT-005 r3)
- File: tests/test_gh257_single_a2ui_gate.py:108
- Quote: `if not emitting:`
- Fix: drop the early return; for emitting=False, send a header-opted request with a ContentModel-returning tool without `emits` (or on-app with app.state.a2ui_enabled=False calling demo_kpis) and assert no A2UI part. Or rename to say card-only.

### D-18 wave AC: rename grep matches the new name (RT-017 r2)
- File: tests/test_gh257_single_a2ui_gate.py:79, :82; agent_sdk/app.py:1015
- Quote: `assert compute_a2ui_enabled(None, []) is False`
- Issue: AC grep `a2ui_enabled(None` is a substring of `compute_a2ui_enabled(None`, so a mechanical gate reports the rename incomplete.
- Fix: use word boundaries in the AC grep (`grep -rnw` or `\ba2ui_enabled(`).

All findings: sdkCandidate = true.

---

Autoloop cycle 3 (2026-10-25): mediums verified at v0.24.0; still-present ones filed as #268–#274 (testing #268, AG-UI/console #269, A2UI #270, A2A #271, auth #272, MCP #273, example/tests/registry #274). P-022 not filed (conflicts with #246 ruling). Lows not filed.
