# SDK issue candidates — w065 (2026-10-24)

These critical/high findings from wave w065 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: The shipped module agent_sdk/testing/mcp.py imports jsonschema at the top. But jsonschema is only in the [dev] extra, not in the runtime dependencies, and the agent template does not install it. So in every downstream agent, `python -m agent_sdk.testing.mcp` (acceptance Phase 1.5) and `from agent_sdk.testing import McpClient` fail with ModuleNotFoundError.
- Severity: high
- Component: sdk/build
- File: agent_sdk/testing/mcp.py
- Status: still-open
- Rationale: SDK packaging and runtime dependency defect in a shipped agent_sdk module. It breaks every agent built from the template.

## Candidate 2: The run_gate outputSchema tests use a hand-written fake client, and the MCP-Protocol-Version header test uses httpx.MockTransport with a leaked tempfile key file. Neither test reaches a real build_app() over ASGI, so a disagreement between the gate and the server stays hidden. Real-app paths exist for both failure modes.
- Severity: high
- Component: protocol/mcp
- File: tests/test_gh237_testing_clients.py
- Status: fixed-in-wave
- Rationale: Missing test coverage for the SDK's own MCP testing client and gate against the real MCP route. This is an SDK test, not an agent test.

## Candidate 3: The AG-UI resume status check runs only inside _run(). The pre-admission _resume_interrupt_id() looks up the interrupt without checking status first. So a bad-status resume on a task at the per-task stream cap gets 429 instead of RUN_ERROR, and the docs claim 'checked before any interrupt lookup' is false.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Status: still-open
- Rationale: AG-UI route behavior defect in SDK protocol code. The GH-247 acceptance criterion is not met.

## Candidate 4: TOOL_CALL_RESULT content switched from json.dumps(default=str) to bare dumps_strict. Tool results holding a date, Decimal or UUID now reach the AG-UI wire as 'tool result not serializable'. These results worked in v0.21.0, and the CHANGELOG has no notice of the change. The fix is to keep the lenient coercion (to_jsonable_python with fallback=str) and add the strict check on top.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Status: fixed-in-wave
- Rationale: Silent backward-compatibility regression in the SDK AG-UI route that affects normal tool result shapes.

## Candidate 5: GH-247 now rejects any AG-UI resume status other than resolved or cancelled. But the documented ChatDriver example still calls agui_resume(..., status="approved"), and docs/tools.md still says the approved/rejected shorthand is accepted. A downstream agent that copies either doc gets RUN_ERROR 'invalid resume entry'.
- Severity: high
- Component: protocol/ag-ui
- File: docs/testing.md
- Status: fixed-in-wave
- Rationale: The SDK's public docs teach agent developers an AG-UI resume shape that the protocol route now rejects.

## Candidate 6: The A2A route hard-codes a 32-hex check on pageToken. TaskStore documents the next-page token as opaque, and Agent(task_store=...) accepts custom stores. So a custom store with offset or cursor tokens gets 400 -32602 on page 2. The fix is to delegate validation to the store, for example with an overridable is_valid_page_token().
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Status: fixed-in-wave
- Rationale: This breaks the public TaskStore extension point in the SDK's A2A route, and the CHANGELOG does not list it as breaking.

## Candidate 7: The unauthenticated OAuth POST /register (and _parse_form, used by the token and consent endpoints) still buffers the whole request body before checking _MAX_BODY_BYTES. Any caller can force an unbounded memory buffer. These spots should use read_capped_body (C-077), as GH-246 did elsewhere.
- Severity: high
- Component: security
- File: agent_sdk/routes/oauth.py
- Status: fixed-in-wave
- Rationale: Memory-exhaustion risk (denial of service) on an unauthenticated SDK OAuth endpoint. It duplicates the GH-246 defect.

## Candidate 8: GH-246 removed the id-is-None -> 202 fallback. A client JSON-RPC error response with id null or no id is no longer recognised as a response. It now gets HTTP 200 with a -32600 body on POST /mcp and is queued on /mcp/messages. MCP Streamable HTTP 2025-06-18 requires 202 with an empty body for a POSTed response. The fix is to treat any message with no method and with result or error as a response.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Status: fixed-in-wave
- Rationale: New MCP and JSON-RPC protocol conformance break in the SDK MCP route.

## Candidate 9: The absence assertion for U+202E (a right-to-left override character) passes without testing anything. HOSTILE_STANDALONE and the 'b' cell never contain U+202E. So the GH-250 criterion is unmet, and the route-level drop of invisible format characters from ids is untested. The standalone loop also lacks U+202E and checks one character twice.
- Severity: high
- Component: security
- File: tests/test_gh212_id_safe_text.py
- Status: still-open
- Rationale: Missing coverage for the SDK's security sanitisation helpers (safe_id_text and safe_cell_text) against hidden direction-control characters.

## Candidate 10: The /v1/* 500 handler sits on Starlette ServerErrorMiddleware, which re-raises after it responds. So uvicorn still logs the full traceback and str(exc) for every /v1/* 500, which can include user values or upstream text. The 'log type only' claim (SI-2) is false, and no caplog test checks the log. The fix is a non-re-raising ASGI catch or a log filter, plus a caplog test.
- Severity: high
- Component: security
- File: agent_sdk/app.py
- Status: fixed-in-wave
- Rationale: Information leak into server logs from SDK core app error handling. The GH-248 criterion is not met.
