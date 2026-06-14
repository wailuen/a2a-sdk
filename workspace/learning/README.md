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
| LRN-007 | Bootstrap endpoint is POST /admin/api/keys not POST /admin/bootstrap | harness | high | Cross-check every skill's bootstrap call against agent_sdk/routes/admin.py and setup/SKILL.md; endpoint is POST /admin/api/keys with X-Bootstrap-Token header. |
| LRN-008 | Source health check uses GET /admin/api/overview, not a per-source POST endpoint | harness | high | 2026-06-14 |
| LRN-009 | Anthropic model backend documented as functional but unimplemented in the SDK | docs | high | Only document model backends with a live _build_model_client code path; mark reserved/unimplemented backends explicitly. |
| LRN-010 | SDK bootstrap token is emitted to stderr, not stdout; boot capture must use 2>&1 | ops | high | 2026-06-14 |
| LRN-013 | AC "integration note" wording targets the Integration section, not step bodies | high | When an AC says "integration note", verify the ## Integration section explicitly — updating only the step body is not sufficient. |
| LRN-011 | Bootstrap token goes to stderr; agent-verify boot command must use 2>&1 | ops | high | 2026-06-14 |
| LRN-012 | wave-cycle.js A2UI audit prompt misstated Standard Profile type counts as Core 7 + Extended 11 instead of Core 6 + Extended 8 | harness | high | Keep DESIGN.md §5.4, content_types.py, and wave-cycle.js line 586 in sync as a single logical unit whenever the Standard Profile type list changes. |
