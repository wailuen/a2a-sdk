# SDK issue candidates — w057 (2026-10-17)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: RT-001: The per-identity session cap runs in the wrong order. In the MCP initialize branch (mcp.py ~903-912), the new session is inserted first. Then _prune_sessions runs the global _MAX_SESSIONS LRU eviction (popitem(last=False)). Only after that is the caller's own oldest session trimmed. When the global map is full, an identity already at its 4-session cap that initializes again evicts a different identity's least-recently-used session, then trims its own. Probe: with _MAX_SESSIONS=6, a victim holding 2 sessions and an attacker holding 4, three re-initializes by the attacker left the victim with 1 session. The map ended at 5, below the cap, so the foreign eviction was not needed. Fix: add a helper such as _evict_identity_lru(sessions, owner, cap) that pops the owner's oldest sessions while len(owned) >= cap. Run it before the insert. Then insert, then call _prune_sessions. Add a regression test in tests/test_gh201_mcp_session_sharing.py that asserts all of the other identity's sessions survive.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: SDK protocol route code (agent_sdk/routes/mcp.py), not agent-domain code. It is a cross-tenant availability and security problem: one identity can evict another identity's MCP sessions. It breaks the GH-201 SI-5 rule that no step may evict a session owned by a different identity, and the 'global LRU behaves as before' acceptance check. It also differs from the IdpFlowStore._evict_for reference pattern, which evicts the caller's own entry before inserting.
