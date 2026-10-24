# SDK issue candidates — w064 (2026-10-24)

These critical/high findings from wave w064 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: loads_strict has no nesting-depth cap of its own. It only catches RecursionError, which depends on the Python version (3.14 parses 50000-deep input without raising), and input nested 255 to about 1000 levels always gets through. A 300-deep message.metadata on POST /v1/message:send is stored, and then GET /v1/tasks returns HTTP 500 for that identity until the task expires: pydantic's 'Circular reference detected (depth exceeded)' ValueError comes from the model_dump in a2a.py _list_entry, which is outside its try. On 3.14, POST /mcp returns -32600 where the acceptance criteria require -32700. GH-235 is only partly fixed. Fix: add an explicit _MAX_DEPTH (64 or 128, below pydantic's 255) that raises a fixed-message JSONDecodeError, keep the RecursionError catch as a backstop, and add a regression test for send-then-list.
- Severity: high
- Component: security
- File: agent_sdk/common/json_strict.py
- Status: still-open
- Rationale: Core SDK ingress parser (C-040) shared by every protocol route. A cross-version denial of service, and the HTTP 500 on /v1/tasks is an SDK defect, not agent-domain code.

## Candidate 2: The GH-237 run_gate acceptance test uses a hand-written _FakeMcp with a made-up load_skill entry. The acceptance criteria call for a real app with mcp_skills="tool". The real tools/list path is never exercised, so changes to the real load_skill tool (name, schema, GH-236 annotations) would not be caught. This also breaks the no-mock rule for protocol surfaces. Fix: build a real Agent with skills_dir and mcp_skills="tool", mount build_app() over httpx.ASGITransport, and drive it with McpClient (as in test_gh209_testing_mcp.py).
- Severity: high
- Component: protocol/mcp
- File: tests/test_gh237_testing_clients.py
- Status: fixed-in-wave
- Rationale: Tests the SDK's own testing client (agent_sdk/testing/mcp.py run_gate) against the SDK's MCP skills surface. This is SDK test coverage, not an agent test.

## Candidate 3: A2uiCapabilities (exported from agent_sdk.a2ui) gained a public dataclass field negotiate_standard and a new keyword, keep_declared_catalogs, on from_metadata and gated. Neither is documented in DESIGN.md, docs, or under CHANGELOG Added. The new field also changes __eq__ and repr: gated(..., keep=True) != gated(...) for the same input. Fix: document both as public API, or make the field private with repr=False and compare=False.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/a2ui/translator.py
- Status: still-open
- Rationale: A change to the public API surface of the SDK's A2UI capability negotiation, including a change in equality behaviour, and it is undocumented outside the CHANGELOG too. This is more than wave CHANGELOG hygiene.

## Candidate 4: The acceptance criteria asked for U+2028, \x85 and \x9b to be added to HOSTILE_STANDALONE. They were not added. So the new assertion that these characters are absent from the rendered text is always true and can never fail. This is the same dead check GH-242 reported. Fix: add the characters to the hostile input, then confirm the tests fail if safe_id_text stops neutralising C1 characters or U+2028.
- Severity: high
- Component: security
- File: tests/test_gh212_id_safe_text.py
- Status: still-open
- Rationale: The regression test for the SDK's output-sanitisation code (safe_id_text / is_id cells) checks nothing for these characters, which leaves an injection-hardening gap untested.
