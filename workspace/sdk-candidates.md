# SDK issue candidates — w056 (2026-10-17)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: REVIEWS.md lines 74 and 147 still say a Streamable HTTP non-initialize POST with no MCP-Protocol-Version header returns 400. GH-200 reversed that rule: such a request should use the session's negotiated version, or 2025-03-26 if there is none. A present but unrecognized header still returns 400. GET/DELETE with no header are allowed. Legacy SSE with no header assumes 2025-03-26. This breaks LRN-118's Check and its Prevention rule, which says DESIGN.md and REVIEWS.md must be updated in the same commit.
- Severity: high
- Component: protocol/mcp
- File: REVIEWS.md
- Rationale: The finding is about the SDK's own MCP protocol docs for the agent_sdk/routes/mcp.py header handling. It is not agent-specific code. The fix belongs in the SDK repo, and the w056 todo's doc acceptance check only named DESIGN.md.

## Candidate 2: test_design_md_streamable_http_absent_header_returns_400 (line 66) still enforces the GH-77 rule that GH-200 reversed. The module docstring (line 5) and the assertion message at line 90 say the same thing. The test only passes because the new DESIGN.md history note ('GH-200 reverses GH-77's absent→400') puts '400' inside the checked text window. If someone tidies that note away, the test fails and pushes them to write the old rule back in. The fix is to rename it to test_design_md_streamable_http_absent_header_uses_session_version, assert 'GH-200', 'negotiated', '2025-03-26' and 'present-but-unrecognized → 400', and add a negative check against '400s on absent'.
- Severity: high
- Component: protocol/mcp
- File: tests/test_gh117_mcp_transport_split_docs.py
- Rationale: This is an SDK doc-guard test for MCP protocol behavior, not an agent test. It locks in a reversed protocol rule and conflicts with the GH-200 ruling and LRN-118's updated Check.
