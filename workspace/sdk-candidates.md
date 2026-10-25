# SDK issue candidates — w068 (2026-10-25)

These critical/high findings from wave w068 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: The AG-UI test driver (ChatDriver._run_agui) still crashes with a raw traceback on three badly shaped frames: an AGENT_ARTIFACT value that is not a dict (AttributeError), interrupts that are not a list (KeyError 0 at chat.py:415), and a RUN_ERROR message that is not a string (TypeError later in turns.py:304 join). The GH ruling says no exception may escape run_turn or ChatDriver. These shapes should be treated as malformed-stream, with a test for each.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/testing/chat.py
- Status: fixed-in-wave
- Rationale: SDK testing client (agent_sdk/testing) that reads the AG-UI wire stream; a crash here affects every agent author who uses run_turn/ChatDriver.

## Candidate 2: In the A2A test client (_a2a_attempt), a task id, contextId or status.state that is not a string gets past the shape guards. It is stored in at.ids, then write_text() raises TypeError, so run_turn crashes instead of reporting 'malformed-stream'. Check these values are strings at turns.py:227-242 and add tests.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/testing/turns.py
- Status: still-open
- Rationale: SDK testing client reading the A2A wire stream; breaks the ruling that no raw exception escapes run_turn.

## Candidate 3: _Wire._wire_rule applies wire_keeps_null and wire_omitted by Python field name, not by the wire alias. For an aliased field the kept-null key is written under the snake_case name and the omitted key is never removed, while the catalog advertises the alias. The catalog and the wire then disagree. Resolve each name to its output key using info.by_alias and add an aliased-field test.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Status: fixed-in-wave
- Rationale: Base content_types serializer that every domain card inherits; affects A2UI catalog/wire agreement.

## Candidate 4: GH-270 adds two new reserved names (_wire_rule, _wire_reshape) to the public _Wire base. A domain card that already had its own _wire_reshape helper now fails on every wire()/model_dump(). A card that declares its own model_serializer silently replaces _wire_rule and drops its kept-null fields with no warning. The base needs guards in __pydantic_init_subclass__ plus tests, and the break must be called out.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Status: still-open
- Rationale: Change to the SDK content_types base model that silently breaks downstream domain cards.

## Candidate 5: DESIGN.md section 5.5 still says Streamable HTTP rejects only an unknown MCP-Protocol-Version with 400. It does not describe the new GH-273 rule: a valid header that differs from the session's negotiated version now gets 400, and early exits echo the session's version. The design doc no longer matches mcp_post.
- Severity: high
- Component: protocol/mcp
- File: DESIGN.md
- Status: still-open
- Rationale: Authoritative SDK design doc for MCP transport behaviour is out of date with the protocol route code.

## Candidate 6: The GH-274 rewrite of the example agent's resume handler ignores the top-level resume status. An AG-UI resume with status 'cancelled' and payload.decision 'approved' now publishes the note, so a cancelled confirmation runs the side effect. Use contrib.action_gate.parse_decision (reject wins) and add a cancelled+approved test.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/example/agent.py
- Status: fixed-in-wave
- Rationale: SDK example agent that adopters copy; wrong handling of the AG-UI interrupt-resume 'cancelled' status lets a cancelled action go ahead.
