# SDK issue candidates — w070 (2026-11-01)

These critical/high findings from wave w070 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: The MCP elicitation schema converter (convert_schema) quietly drops limits it cannot carry. Examples: an enum on numbers, a string const, pattern, multipleOf, and exclusiveMinimum/exclusiveMaximum. It should return 'not convertible' instead. Because of this, validate_content accepts answers that the tool's own response_schema forbids, and those answers reach resume_handler. Fix: give each property type an allow-list of keywords and return None for any keyword outside it.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp_elicitation.py
- Status: still-open
- Rationale: This is an SDK protocol route (agent_sdk/routes/mcp_elicitation.py) that turns tool schemas into MCP elicitation schemas. Every agent that uses ToolInterrupt elicitation gets this check, so the bug is in the SDK, not in one agent's domain code.

## Candidate 2: When there is no resume_handler and the user accepts an elicitation, tools/call returns isError:false with text only and skips _finish_tool_result. Some tools declare emits, which makes tools/list advertise an outputSchema. For those tools this is a success result with no structuredContent. MCP 2025-06-18 forbids that, and LRN-469 requires isError in that case. Fix: send the accepted content for those tools through _finish_tool_result.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Status: still-open
- Rationale: This is the SDK's MCP tools/call route (agent_sdk/routes/mcp.py). It opens a second success path that skips the SDK's own outputSchema check, so it breaks MCP structured-output rules for any agent.

## Candidate 3: convert_schema checks only $ref, $defs and additionalProperties at the top level of the schema. It quietly drops every other top-level keyword, such as anyOf, oneOf, allOf, if/then/else, minProperties, dependentRequired and not. So validate_content accepts content, even {}, that the tool's response_schema forbids. Fix: allow only a fixed list of top-level keys (type, properties, required, additionalProperties, title, description, $schema) and return None for any other key.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp_elicitation.py
- Status: fixed-in-wave
- Rationale: This is in the SDK's MCP elicitation converter (agent_sdk/routes/mcp_elicitation.py), the same SDK code as the first finding. It is not agent-domain code. Note: this finding reuses the id RT-001; the id is copied unchanged as the task requires.
