# SDK issue candidates — w062 (2026-10-23)

These critical/high findings from wave w062 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: Strict schema mode removes a required-but-nullable input field with no default (e.g. `query: str | None`) from `required`. Pydantic still requires the key, so a strict MCP client that omits it, as the advertised inputSchema allows, gets a ToolInputValidationError. The advertised contract and the enforced one disagree, and docs/deployment.md:110 repeats the false claim.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/common/schema.py
- Status: still-open
- Rationale: Defect in SDK-internal schema rewriting (agent_sdk/common/schema.py) that shapes every tool's MCP inputSchema in strict mode; affects all agents built on the SDK.

## Candidate 2: The anyOf-null collapse runs at every schema node, so list items and dict values (e.g. list[Optional[str]], dict[str, Optional[int]]) lose null. exclude_none keeps None inside lists and dicts, so structuredContent like [None, "a"] fails the tool's own strict outputSchema, which breaks the MCP 2025-06-18 rule that structured results must conform to outputSchema.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/common/schema.py
- Status: still-open
- Rationale: SDK schema flattening used for MCP outputSchema; a protocol conformance defect affecting any agent tool with nullable list/dict members.

## Candidate 3: Strict mode turns every property-level anyOf:[X,null] into plain X, including required nullable output fields that a model_serializer re-emits as null. The built-in TimeSeriesDataPoint.value is re-emitted as `value: null`, so TimeSeriesChart structuredContent with a data gap fails its strict outputSchema ("None is not of type 'number'").
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/common/schema.py
- Status: still-open
- Rationale: Breaks MCP outputSchema conformance for a core built-in Standard Profile content type; the fault is in SDK schema code, not agent code.

## Candidate 4: In strict outputSchema, an `X | None` field with no default stays in `required`, but structuredContent is built with exclude_none=True, which drops the key when it is None. The tool's own result then fails its advertised outputSchema ("'x' is a required property"), and strict clients like Copilot Studio reject the call. The code comment saying serializers re-emit null is only true for TimeSeriesDataPoint.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/common/schema.py
- Status: fixed-in-wave
- Rationale: SDK-level mismatch between schema generation and the SDK's own structuredContent serializer; affects any domain emits model with a required nullable field.

## Candidate 5: Strict mode checks nullability on the raw property before resolving its $ref. A nullable type alias (TypeAliasType('MaybeInt', Optional[int])) becomes a $ref, so the field stays in `required` and collapses to plain integer. A None value is then dropped by exclude_none and structuredContent fails its own outputSchema.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/common/schema.py
- Status: fixed-in-wave
- Rationale: SDK schema rewrite defect producing non-conformant MCP outputSchema; previously deferred G1 item still open.

## Candidate 6: The GH-230 ruling asked for an allowlist of all pydantic built-in error codes plus the SDK's own codes. The code only allows the 24 codes that have a phrase, so built-in codes like too_long, int_from_float and date parsing errors now render a generic 'input failed validation' message. The model loses the guidance it needs to fix its call, and the CHANGELOG does not mention this downgrade.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Status: fixed-in-wave
- Rationale: SDK agent loop error-rendering behaviour that diverges from a ratified ruling; affects tool-call self-correction for every agent.

## Candidate 7: The GH-230 no-log-leak checks (lines 223, 256, 289) use root caplog. build_app() calls configure_logging(), which turns off propagation on the agent_sdk logger, so root caplog never sees SDK log records and the assertions pass without checking anything. The SI-2 requirement that the marker is absent from logs is not proven.
- Severity: critical
- Component: security
- File: tests/test_gh230_safe_value_error.py
- Status: fixed-in-wave
- Rationale: SDK test suite for a security invariant (no secret/value leak to logs) is vacuous; this is SDK-repo test coverage, not an agent test.

## Candidate 8: The GH-205 no-log-leak checks for prompts/get and tools/call load_skill (lines 243, 253) use root caplog. When this test builds the first app in the process, configure_logging() turns off agent_sdk propagation, so root caplog is empty and the assertions check nothing. A probe confirmed a known warning was not captured. Same LRN-106 failure mode; still open from the deferred G1 todo.
- Severity: high
- Component: security
- File: tests/test_gh205_mcp_skills.py
- Status: still-open
- Rationale: SDK-repo security test (SI-2 skill-name log leak on MCP routes) silently passes empty; SDK-level test-coverage gap, not agent code.
