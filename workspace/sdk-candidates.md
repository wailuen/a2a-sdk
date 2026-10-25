# SDK issue candidates — w067 (2026-10-25)

These critical/high findings from wave w067 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: A resume hands new acceptedOutputModes (and reads a2ui_opted_in) by changing the record returned from store.get(). A store that returns a copy from get() loses the change, so a correct A2UI resume can get 415. Two back-to-back resumes can also race: the losing request still overwrites the winner's accepted_output_modes before it gets -32001. That breaks the ResumeEnvelope rule that a losing resumer changes nothing. The fix is to carry the modes inside the deliver_resume envelope and let the worker set them on its live record.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Status: fixed-in-wave
- Rationale: Resume handoff in the SDK's A2A route and TaskStore contract; affects every agent and any custom copy-on-get store.

## Candidate 2: The AG-UI A2UI-off tests drive a `plain` tool that returns a dict, so an A2UI_UPDATE frame could never appear anyway. A mutation that forced a2ui_enabled=True on the AG-UI path still passed. The off-gate on AG-UI is not actually tested; tests must use an emitting ContentModel tool and assert no A2UI_UPDATE CUSTOM frame.
- Severity: high
- Component: protocol/ag-ui
- File: tests/test_gh257_single_a2ui_gate.py
- Status: fixed-in-wave
- Rationale: SDK test suite coverage of the A2UI gate on the AG-UI route, not agent-domain code.

## Candidate 3: Learning Check clauses in LRN-197 and LRN-047 still require the old 501/-32004 status for a terminal-task resume, which the GH-266 ruling changed to 400. Every later redteam runs these checks, so they will fail on correct code and push the next wave to revert GH-266.
- Severity: high
- Component: harness/workflow
- File: workspace/learning/LRN-197-error-code-doc-sweep-gap.md
- Status: fixed-in-wave
- Rationale: Stale learning checks feed the harness redteam loop and can cause a ruled wire status to be reverted.

## Candidate 4: The apply_output_modes fallback keeps a dead TextPart line (that list is always empty at that point). A FilePart-only artifact still gets an empty TextPart(text="") instead of a -32005 error. The GH-261 item 7 low is not done.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/agent/runner.py
- Status: fixed-in-wave
- Rationale: SDK artifact output-mode filtering shared by all agents on the A2A path.

## Candidate 5: The deferred-tool path where apply_output_modes raises -32005 inside _run_deferred_background has no test. The new deferred tests only reach the success path. A test is needed where a long_running tool's result is fully filtered out and the task fails with -32005 and no artifacts.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py
- Status: still-open
- Rationale: SDK deferred/background tool execution branch, untested in the SDK suite.

## Candidate 6: The FAILED tail status in _unserializable_tail is still built by hand, and the text 'invalid agent response' is written twice (TextPart and WireError). GH-259 says failed-task status.message must come from one builder (set_task_status), so these copies can drift.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Status: fixed-in-wave
- Rationale: SDK A2A route failure-status construction.

## Candidate 7: The documented MCP deviation names the wrong case. A tool with no `emits` has no outputSchema, so an empty result is not a deviation. The real deviation is a tool that declares `emits` (advertises outputSchema) and returns None, which answers isError:false with no structuredContent despite MCP 2025-06-18's MUST. GH-266 item 1 AC is not met.
- Severity: high
- Component: protocol/mcp
- File: docs/protocols.md
- Status: fixed-in-wave
- Rationale: SDK protocol documentation of an MCP spec deviation in routes/mcp.py.

## Candidate 8: The new `wire_omitted` ClassVar is read only by the catalog. ColumnDef._omit_is_id_when_false and DocumentItem._wire_contract_keys still hard-code the key names, so there are two hand-synced copies that can drift. CHANGELOG and DESIGN.md claim the serializers read the ClassVar, which is false.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Status: fixed-in-wave
- Rationale: SDK content_types models and A2UI catalog field contracts.

## Candidate 9: test_consent_post_rerender_keeps_bare_challenge never reaches the consent re-render: client_id 'nope' is unregistered (returns 400 with no WWW-Authenticate) and the form field should be 'api_key', not 'admin_key'. The `wa is None or ...` assert passes without testing anything, so the consent-POST challenge site is untested.
- Severity: high
- Component: protocol/oauth
- File: tests/test_gh260_rate_limit.py
- Status: fixed-in-wave
- Rationale: SDK OAuth consent route challenge behaviour is not covered by the SDK test suite.

## Candidate 10: test_bootstrap_401_keeps_bare_challenge posts to a route that does not exist (404), and its only assert sits inside `if r.status_code == 401`, so it never runs. The real bootstrap 401 site (POST /admin/api/keys with a bad X-Bootstrap-Token) is untested.
- Severity: high
- Component: security
- File: tests/test_gh260_rate_limit.py
- Status: fixed-in-wave
- Rationale: SDK admin bootstrap auth challenge path lacks real test coverage.

## Candidate 11: The rewrite deleted the shipped GH-260 regression tests test_bearerless_mcp_never_429 and test_non_oauth_429_unchanged with no replacement. Nothing now pins that a missing bearer never gets 429, or that a non-/oauth/ 429 keeps its {"detail": "rate limit exceeded"} body.
- Severity: high
- Component: security
- File: tests/test_gh260_rate_limit.py
- Status: still-open
- Rationale: Loss of SDK rate-limit and auth regression coverage for a released fix.
