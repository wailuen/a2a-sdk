# Learnings

Codified bugs, gotchas, and validated patterns from SDK development and downstream agent operation.

| ID | Title | Category | Severity | Date |
|----|-------|----------|----------|------|
| LRN-001 | Protocol wire tests must verify HTTP headers, not just response bodies | testing | high | 2026-06-14 |
| LRN-002 | Pre-release redteam must run at full scope, not wave scope | ops | high | 2026-06-14 |
| LRN-003 | WWW-Authenticate must include resource_metadata on all protected routes | protocol | medium | 2026-06-14 |
| LRN-004 | CORS preflight must include Access-Control-Expose-Headers | protocol | medium | 2026-06-14 |
| LRN-005 | MCP version header must match negotiated body version on initialize | protocol | high | 2026-06-14 |
| LRN-006 | ContentModel A2A artifacts must always emit DataPart | protocol | high | 2026-06-14 |
