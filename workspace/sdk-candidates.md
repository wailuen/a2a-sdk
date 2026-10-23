# SDK issue candidates — w061 (2026-10-23)

These critical/high findings from wave w061 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: Deferred tool with multi-type emits: when the result matches none of the declared types, A2A correctly falls back to text only, but the runner still publishes the artifact loop event with the raw result. The AG-UI mapper turns that into AGENT_ARTIFACT plus two A2UI_UPDATE card events, so AG-UI shows a card while A2A does not. This breaks cross-surface parity and the deferred-path rule of no A2UI card on a no-match. Fix: publish the artifact frame with no loop event (publish(artifact_frame, None)) on no-match, and add AG-UI deferred-path tests to tests/test_gh225_multi_type_emits.py.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/agent/runner.py
- Status: fixed-in-wave
- Rationale: Bug in SDK internals (agent_sdk/agent/runner.py deferred delivery) that surfaces on the AG-UI protocol route; not agent-specific code.

## Candidate 2: MCP tools/call does not enforce the advertised outputSchema. (a) A tool with emits=(A,B) returning an unrelated model C gets isError:false with no structuredContent, even though tools/list advertised an outputSchema. (b) A tool with emits=A returning unrelated C gets structuredContent that does not conform to A's schema, because coercion only runs for non-model results. Fix: when an outputSchema is advertised, require the result to match a declared emits type, else try coercion from model_dump(), else return the existing isError:true coercion-failed result; add a test that validates structuredContent against the tools/list outputSchema.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Status: still-open
- Rationale: Protocol conformance bug in the SDK's MCP route (agent_sdk/routes/mcp.py, lines ~819-833), a MUST in the MCP spec; affects every agent built on the SDK.
