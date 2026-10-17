wave: w056
group: G1
date: 2026-10-17

Non-blocking — these did not block w056's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from
each round is folded in. IDs below are renumbered after the merge. All findings are SDK-level
(sdkCandidate: true) except RT-009.

## Findings

### RT-001
- severity: medium
- file: harness/agents/mcp-advisor.md
- description: The MCP advisor checklist (harness/agents/mcp-advisor.md:90, mirrored in .claude/agents/mcp-advisor.md:90) and harness/skills/mcp-check/SKILL.md:77 still say 'require MCP-Protocol-Version post-init'. That is the old GH-77 rule. The wave's protocol-audit step and every later /mcp-check run will now flag GH-200's absent-header -> 200 behavior on POST /mcp as non-conformant, which invites someone to bring back the 400 the ruling says must not return. This is the same doc-drift pattern LRN-118 was written to stop.
- fix: Change the checklist line in harness/agents/mcp-advisor.md, .claude/agents/mcp-advisor.md and harness/skills/mcp-check/SKILL.md (plus the template mirror if one exists) to: 'validate MCP-Protocol-Version when present (400 if present but unsupported); if absent, use the version negotiated at initialize, else assume 2025-03-26 (do NOT 400 on absent; GH-200)'. Optionally widen LRN-118's Check so it also greps harness/agents/mcp-advisor.md and harness/skills/mcp-check/SKILL.md for 'require.*MCP-Protocol-Version'.
- codify: When a protocol ruling reverses a rule, update the advisor and check-skill checklists in the same change, or the next protocol audit will flag the fix as a regression.
- sdkCandidate: true

### RT-002
- severity: medium
- file: tests/test_gh117_mcp_transport_split_docs.py
- description: This doc-guard test still enforces the reversed GH-77 rule. The module docstring (line 5) says 'Streamable HTTP (POST /mcp, non-initialize) — absent header → 400'. test_design_md_streamable_http_absent_header_returns_400 (line 66) passes only by accident: the new DESIGN.md text contains 'reverses GH-77's absent→400' within 300 chars of 'Streamable HTTP'. The assertion message on test_design_md_no_longer_states_blanket_absent_rule says Streamable HTTP 'now 400s instead'. If a later doc edit drops that history phrase, the test fails and tells the contributor to put the 400 claim back. That contradicts the GH-200 ruling ('do not reinstate it').
- fix: Update the docstring to the GH-200 rule. Replace test_design_md_streamable_http_absent_header_returns_400 with an assertion that the Streamable HTTP clause mentions GH-200 and 'negotiated' (or the session-version fallback), and that no clause says Streamable HTTP '400s on absent'. Fix the stale assertion message in test_design_md_no_longer_states_blanket_absent_rule.
- codify: Doc-guard tests must be updated with the ruling they guard; a guard that passes on a sentence describing the reversal is a vacuous pass that steers toward the old rule.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: The comments on the GET and DELETE handlers are now wrong about mcp_post. The `mcp_get` comment (lines ~936-940) says 'unlike mcp_post, an absent header is accepted here, so "header required" would misdirect...'. After GH-200, mcp_post also accepts an absent header and no longer returns the 'header required' text. The matching `mcp_delete` comment (~1035-1039) has the same problem. This is the same doc-versus-behavior drift LRN-118 exists to catch, inside a file this group changed. (The sibling stale comments in tests/test_http_protocol.py are RT-005.)
- fix: Reword the mcp_get comment to say that all three verbs (POST, GET, DELETE) now accept an absent header (GH-200 for POST) and use the same 'unsupported MCP-Protocol-Version' text for a present but unrecognized value. Make the matching change to the mcp_delete comment.
- sdkCandidate: true

### RT-004
- severity: low
- file: agent_sdk/routes/mcp.py
- description: (Raised in three rounds; merged.) The Legacy SSE handler mcp_messages (POST /mcp/messages, mcp.py:1209-1214) still answers a present-but-unrecognized MCP-Protocol-Version with 400 {"error": "MCP-Protocol-Version header required"}. GH-200 and RT-005 renamed this wording to 'unsupported MCP-Protocol-Version' on POST /mcp, and GET/DELETE already use it. The legacy path is now the only one that tells a client which DID send the header that the header is missing (the RT-005 misdirection). The comment just above it (line 1206) was edited in this change and is about 138 characters long, far wider than the rest of the file.
- fix: Change the mcp_messages 400 body to {"error": "unsupported MCP-Protocol-Version"} to match the other MCP verbs. Add an assertion on the message in the legacy present-but-unrecognized test (tests/test_mcp_legacy_initialize.py or a sibling). Wrap the line-1206 comment.
- sdkCandidate: true

### RT-005
- severity: low
- file: tests/test_http_protocol.py
- description: Comments are stale after GH-200. Lines 243-246 say the absent-header case is a 'locked GH-77/w022 ruling — do not re-litigate'. Lines 279-282 (RT-005 docstring, line 281) refer to 'mcp_post's "header required" wording', but mcp_post no longer uses it. Both now misstate the POST /mcp behavior.
- fix: Reword to say GET/DELETE allow an absent header, and that POST /mcp also allows it as of GH-200 (session version, else 2025-03-26). Drop the 'mcp_post header required' reference.
- sdkCandidate: true

### RT-006
- severity: low
- file: tests/test_mcp_gh77_absent_version_header.py
- description: (Raised in two rounds; merged.) The tests do not cover all of the AC's session-check cases or the fallback edges. The AC says unknown, expired AND foreign session → 404 when the header is absent, but only an unknown id ('deadbeef') is tested. Untested: (a) a session id owned by another identity with no version header (the cross-identity guard GH-200's SI-5 note names); (b) an expired session with no version header; (c) an absent-header notification (202 path), which must carry the session's version in its response header; (d) a session whose initialize asked for an unsupported version, so the server stored 2025-11-25 and must echo it.
- fix: Add parametrized tests. (1) Initialize as identity A, then POST ping as identity B with A's Mcp-Session-Id and no MCP-Protocol-Version: expect 404, and check B never receives A's negotiated version. (2) Expired session (age the record in app.state.mcp_sessions past SESSION_TTL_SECONDS, or monkeypatch SESSION_TTL_SECONDS / time) with no header: expect 404. (3) notifications/initialized with no header on a live 2025-06-18 session: expect 202 with response header MCP-Protocol-Version: 2025-06-18. (4) Initialize with protocolVersion '2024-11-05', then an absent-header ping: expect header '2025-11-25'.
- sdkCandidate: true

### RT-007
- severity: low
- file: tests/test_mcp_gh77_absent_version_header.py
- description: `test_present_supported_version_header_echoed` sets up a session at 2025-06-18, then sends the header MCP-Protocol-Version: 2025-03-26 and asserts 200 with an echo of 2025-03-26. The todo's AC asks only that a present, supported header behave as before. But now that the server stores each session's negotiated version, this test also locks in accepting a header that does not match the session's version, and nothing in the todo or DESIGN.md §5.5 decides that question.
- fix: Use the session's own version in the header (2025-06-18) so the test checks only the 'present and supported, echoed' AC. If accepting a mismatched header is deliberate, add one sentence saying so to DESIGN.md §5.5 and keep a separately named test for it.
- sdkCandidate: true

### RT-008
- severity: low
- file: agent_sdk/routes/mcp.py
- description: The fallback version is written as the bare string "2025-03-26" in two places (mcp.py:875 in the absent-header branch and mcp.py:911 when the session record is stored). It is not tied to SUPPORTED_PROTOCOL_VERSIONS. The todo's SI-5 note says only values in SUPPORTED_PROTOCOL_VERSIONS are ever echoed. If 2025-03-26 is ever dropped from that tuple, this code would echo an unsupported version and no check would catch it. Related gap: the CHANGELOG GH-200 entry's 'Changed:' list leaves out REVIEWS.md and tests/test_gh117_mcp_transport_split_docs.py, which this group also changed.
- fix: Add a module constant, e.g. _ABSENT_HEADER_DEFAULT_VERSION = "2025-03-26", with an import-time assert that it is in SUPPORTED_PROTOCOL_VERSIONS (same pattern as the RTGA-004 ordering assert), and use it at both sites. Add REVIEWS.md and tests/test_gh117_mcp_transport_split_docs.py to the CHANGELOG GH-200 entry's Changed/Tests lists.
- sdkCandidate: true

### RT-009
- severity: low
- file: REVIEWS.md
- description: REVIEWS.md was changed (Round-1 MCP table row 11 and the LOW 'required on all post-init requests' row), but it is not in G1's declared Creates/Modifies list in workspace/todos/active/w056-gh-issues.md. The content is correct, and LRN-118's Prevention step asks for this update. Still, the plan and the landed diff do not match, so scope checks driven by the plan never review this file.
- fix: Add REVIEWS.md to the GH-200 todo's Modifies list, or record the out-of-list edit in the wave notes, so scope-driven review covers it.
- sdkCandidate: false
