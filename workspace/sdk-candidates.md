# SDK issue candidates — w066 (2026-10-25)

These critical/high findings from wave w066 are classified as
SDK-level. Status is re-checked against the final tree: fixed-in-wave candidates were
already fixed by this wave; run `/sdk-issue-scan` on the still-open ones to file them on
`wailuen/a2a-sdk`. One confirmation per filing — nothing is filed automatically.

## Candidate 1: Two AG-UI tests still expect the old whole-result fallback for NaN/inf in tool results and tool-call args. GH-251 changed _tool_json in agent_sdk/routes/ag_ui.py to replace each bad value with null ('{"x":null}'), so the file reports 2 failures and the SDK test gate is red.
- Severity: high
- Component: protocol/ag-ui
- File: tests/test_gh235_nested_json_and_resume.py
- Status: fixed-in-wave
- Rationale: SDK test of the AG-UI route serializer; the SDK gate fails on the current tree, independent of any agent.

## Candidate 2: is_json_content_type writes its own copy of the media-type cleanup (lowercase, drop parameters) instead of calling normalize_media_type from agent_sdk/common/media.py (C-079). Two copies of the ingress rule can drift apart.
- Severity: high
- Component: security
- File: agent_sdk/common/body.py
- Status: fixed-in-wave
- Rationale: SDK internal ingress content-type check shared by protocol routes; duplicated normalization is an SDK code defect.

## Candidate 3: _summary_at_depth does not skip fields marked exclude=True, and _wire_required treats any default or default_factory as always written. A field like Field(default_factory=list, exclude=True) is shown as required in the catalog prompt, but wire() never writes it. This is a regression against the GH-258 rule.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/a2ui/catalog.py
- Status: still-open
- Rationale: A2UI catalog prompt generation in the SDK; affects every agent that declares a content model with an excluded field.

## Candidate 4: The GH-256 A2UI activation, resume and header-gate tests still run against fake MockTransport cards. The one build_app() test uses an app whose card never advertises A2UI and checks only status and ids, so A2UI header and capability activation is never proven against a real card.
- Severity: high
- Component: protocol/a2a
- File: tests/test_gh237_testing_clients.py
- Status: fixed-in-wave
- Rationale: Covers the SDK's agent_sdk.testing A2A client against the SDK's own build_app(); the gap is in SDK test coverage of the protocol client.

## Candidate 5: The only real-app A2UI activation test passes a pre-built ChatDriver, so the turns.py code that builds the driver from the card's catalogs never runs. Its catalog check cannot fail, because the real card lists only the standard catalog that ChatDriver always adds.
- Severity: high
- Component: protocol/a2ui
- File: tests/test_gh237_testing_clients.py
- Status: still-open
- Rationale: SDK testing client's A2UI catalog negotiation is untested against a real card with a domain catalog.

## Candidate 6: GH-256 adds three new MockTransport fakes, including the header-only-when-advertised test, although real build_app() apps exist that do and do not advertise A2UI. This breaks the rule that SDK testing-client tests run against build_app() over ASGI (LRN-496/LRN-509).
- Severity: high
- Component: protocol/a2a
- File: tests/test_gh237_testing_clients.py
- Status: fixed-in-wave
- Rationale: SDK testing-client test quality; fake transports hide mismatches with the SDK's real A2A routes.

## Candidate 7: GH-251 changes the output of the exported stable helper safe_block_text. It now strips U+200C and U+200D, which breaks Persian spelling and emoji family sequences in block text, and the change has no Breaking entry or migration note.
- Severity: high
- Component: security
- File: agent_sdk/common/redact.py
- Status: still-open
- Rationale: Stable-core SDK redaction helper exported from agent_sdk/__init__.py; output change affects all agents' prose rendering.

## Candidate 8: tests/test_gh237_testing_clients.py has 9 MockTransport uses; this wave added two (_card_client and the unsupported-version test). The stream handling for kind=="message" events and stopping at final is never run against a real server.
- Severity: high
- Component: protocol/a2a
- File: tests/test_gh237_testing_clients.py
- Status: still-open
- Rationale: SDK A2A testing-client stream handling is unverified against the SDK's real /v1/message:stream route.
