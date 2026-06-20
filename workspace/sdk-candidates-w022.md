# SDK issue candidates — w022 (2026-06-15)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GH-76 AC is unmet: the A2UI_UPDATE custom-event schema in _CUSTOM_EVENT_SCHEMAS still declares "messages": {"type": "array"} with no items key, so the wave's own test tests/test_gh76_a2ui_update_items.py is RED — the full suite reports 1 failed, 767 passed. The fix was specified and a test-first test was landed, but the code change was never applied. The wave is not clean (Dimension 5: unmet AC / failing test shipped).
- Severity: critical
- Component: protocol/a2ui
- File: agent_sdk/routes/agent_card.py:53
- Rationale: The _CUSTOM_EVENT_SCHEMAS dict lives in the A2A agent-card route file and defines the A2UI_UPDATE wire schema emitted by the SDK. A missing 'items' key is a protocol-level schema defect that affects every agent built on the SDK, not domain logic. Component is protocol/a2ui because the broken schema governs A2UI custom-event delivery.

## Candidate 2: LRN-048 Check clause fails on the landed code. _create_task_record (lines 164-167) mutates the inbound client Message in place — msg.task_id = task.id and msg.context_id = task.context_id — then stores that mutated object directly as task.history = [msg]. _resume_or_error (line 197) does the same with msg.context_id before appending to history (line 203). LRN-048 (severity high) explicitly forbids mutating the inbound request Message after validation and forbids role='user' history entries carrying server-assigned ids; this conflates client-sent vs server-emitted Message semantics (A2A §3).
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py:165
- Rationale: The mutation of the inbound Message object and its storage in task.history is a structural defect in the A2A protocol route's task-record construction logic. It violates A2A §3 semantics (client-sent vs server-emitted Message roles) and the SDK's own LRN-048 invariant. Fixing it changes SDK-internal task-record construction, not agent domain logic.

## Candidate 3: GH-77's broadened 400-on-absent-header rule was copied into the legacy POST /mcp/messages handler WITHOUT the is_initialize carve-out, and the version check runs before the body is parsed, so a legacy HTTP+SSE client's initialize request (which carries no MCP-Protocol-Version header on first contact) now gets 400 and can never complete the legacy handshake. The Streamable HTTP path (mcp_post, line 480) correctly exempts is_initialize; the legacy path does not — mcp_messages has zero is_initialize references and rejects at line 681 (relative line 23) before parsing the body at line 690 (relative line 33).
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py:678-688
- Rationale: The missing is_initialize carve-out in the legacy MCP dispatch path is a protocol-route defect in agent_sdk/routes/mcp.py. It breaks legacy HTTP+SSE MCP handshakes at the SDK level for all agents; no agent-domain code is involved. Component is protocol/mcp.

## Candidate 4: GH-75 renamed the live A2A route to POST /v1/tasks/{id}:resubscribe (a2a.py:401) but the canonical reference table still maps tasks/resubscribe -> POST /v1/tasks/{id}:subscribe; the same stale entry exists in the peer copy template/.claude/reference/a2a-protocol-0_3_0.md:67. This causes the a2a-advisor agent and a2a-check skill to audit against the wrong wire path.
- Severity: high
- Component: harness/skill
- File: harness/reference/a2a-protocol-0_3_0.md:67
- Rationale: The harness/reference/ binding table is the ground-truth source cited by the a2a-advisor agent and the a2a-check skill. A stale route mapping here makes the conformance auditor flag correct code as wrong. The fix touches harness/reference/ and template/.claude/reference/ — both harness-layer artifacts, not agent domain files. Component is harness/skill because the primary consumer is the a2a-check skill and advisor.

## Candidate 5: mcp.py:73 sets _TITLE_MIN_VERSION = "2025-11-25" and the initialize handler emits serverInfo.title only when the negotiated version index is <= 0 (i.e., only at 2025-11-25), not at 2025-06-18 where the spec added title. The deviation is intentional (GH-43 empirical rejection) and spec-valid (omitting an optional field is allowed), but the gating comment must be kept accurate and the lower gate should be re-evaluated when GH-43 can be re-tested.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py:73
- Rationale: The serverInfo.title version-gating logic is entirely inside the MCP protocol route in agent_sdk/routes/mcp.py. The finding is a documented deviation from MCP spec §2 with no required code change, but it is an SDK-level protocol concern tracked against the MCP component. No agent-domain code is involved.

## Candidate 6: oauth.py line 518: the OAuth 2.1 MCP spec §11 states clients MUST send the resource param in both auth AND token requests. The server accepts token requests without it, reading the audience from code metadata instead. The three-part binding (validate-at-issue, persist-in-metadata, check-at-use) is satisfied, but a token request with a mismatched resource param would not be rejected, leaving a theoretical RFC 8707 conformance gap at the token endpoint.
- Severity: high
- Component: protocol/oauth
- File: agent_sdk/routes/oauth.py:518
- Rationale: The resource-param enforcement gap is in the OAuth route (agent_sdk/routes/oauth.py), a pure SDK-level protocol surface. It concerns RFC 8707 audience binding at the token endpoint — a cross-cutting security/protocol concern shared by all agents using the SDK's built-in OAuth server. Component is protocol/oauth.

## Candidate 7: AG-UI POST /ag-ui/run performs no Content-Type validation. A2A (_parse_send, line 115) and MCP (mcp_post, line 443) both reject non-application/json bodies with 415. The AG-UI route silently accepts any Content-Type and attempts JSON parse, returning an opaque RUN_ERROR on failure rather than a proper 415 response. A browser client sending the wrong media type gets no corrective signal.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: The missing Content-Type guard is in the AG-UI protocol route (agent_sdk/routes/ag_ui.py). It is an SDK-level protocol uniformity defect — all other protocol surfaces enforce 415; ag-ui/run does not. The fix is a single guard in the SDK route, not in any agent domain code. Component is protocol/ag-ui.

## Candidate 8: agent_card.py build_agent_card() calls registry.all() (line 139) which includes both tier-1 and tier-2 tools. The MCP tools/list handler calls registry.tier1() (mcp.py line 298) and rejects tier-2 tools with method-not-found (-32601, line 356-358). An MCP client that discovers the agent via the card, reads a tier-2 skill, and attempts to call it will receive a confusing 'tool not found' error with no prior indication. The x-sdk.tier annotation is SDK-internal and not part of the A2A spec.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/agent_card.py:139
- Rationale: The agent card is the A2A discovery artifact (/.well-known/agent.json). The mismatch between what the card advertises (registry.all()) and what MCP exposes (registry.tier1()) is a cross-protocol seam defect in SDK-level route files (agent_card.py and mcp.py). No agent domain code is involved. Component is protocol/a2a because the card is the A2A discovery surface where the gap originates.
