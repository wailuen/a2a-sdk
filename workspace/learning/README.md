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
| LRN-007 | Bootstrap endpoint is POST /admin/api/keys not POST /admin/bootstrap | harness | high | 2026-06-14 |
| LRN-008 | Source health check uses GET /admin/api/overview, not a per-source POST endpoint | harness | high | 2026-06-14 |
| LRN-009 | Anthropic model backend documented as functional but unimplemented in the SDK | docs | high | 2026-06-14 |
| LRN-010 | SDK bootstrap token is emitted to stderr, not stdout; boot capture must use 2>&1 | ops | high | 2026-06-14 |
| LRN-011 | Bootstrap token goes to stderr; agent-verify boot command must use 2>&1 | ops | high | 2026-06-14 |
| LRN-012 | wave-cycle.js A2UI audit prompt misstated Standard Profile type counts | harness | high | 2026-06-14 |
| LRN-013 | AC "integration note" wording targets the Integration section, not step bodies | harness | high | 2026-06-14 |
| LRN-014 | pytest -q tests/ bypasses addopts ignore exclusions — always use bare pytest -q | testing | high | 2026-06-14 |
| LRN-015 | MCP tools/call — emits coercion failure must return isError:True, never except:pass | protocol | high | 2026-06-14 |
| LRN-016 | SSRF IP-block logic must live in agent_sdk/common/http.py — never duplicated | security | high | 2026-06-14 |
| LRN-017 | wave-cycle.js — schema-gated gate agents required at redteam and proto-fix checkpoints | harness | high | 2026-06-14 |
| LRN-018 | MCP route bypasses per-type wire dispatch, emitting raw field dict instead of markdown string | protocol | high | 2026-06-15 |
| LRN-019 | Null gate response treated as pass (fail-open) | security | high | 2026-06-15 |
| LRN-020 | Null redteam response treated as clean pass in unit loop | testing | critical | 2026-06-15 |
| LRN-021 | Shared block flag emits wrong remediation instruction | ops | high | 2026-06-15 |
| LRN-022 | Null gate response silently permits archive (fail-open) | testing | critical | 2026-06-15 |
| LRN-023 | Null redteam response treated as clean (fail-open) | testing | critical | 2026-06-15 |
| LRN-024 | Proto-fix gate null treated as pass in wave-cycle | ops | high | 2026-06-15 |
| LRN-025 | Null agent response in archive commit guard silently passes as clean | protocol | high | 2026-06-15 |
| LRN-026 | Null proto-fix gate fails open — crashed gate must set protocolBlocked | testing | high | 2026-06-15 |
| LRN-027 | Hardcoded seam-audit route paths bypass dynamic allCreates derivation | testing | high | 2026-06-15 |
| LRN-028 | Redteam findingsCount can contradict findings array, bypassing zero-tolerance gate | testing | high | 2026-06-15 |
| LRN-029 | Null gate crash allows fail-open progression in fix loops | testing | high | 2026-06-15 |
| LRN-030 | Null redteam response silently treated as clean pass | testing | critical | 2026-06-15 |
| LRN-031 | Null pytest gate response treated as GREEN (fail-open) | testing | critical | 2026-06-15 |
| LRN-032 | Archive-blocked log message must distinguish test failure from protocol block | ops | critical | 2026-06-15 |
| LRN-033 | Wave-cycle missing re-gate after test-fix dispatch | testing | high | 2026-06-15 |
| LRN-034 | Unconditional seam audit fires on every protocol wave | ops | high | 2026-06-15 |
| LRN-035 | Test-fix agent result must be verified with a re-gate pytest pass | testing | high | 2026-06-15 |
| LRN-036 | Phase redteam null-response must not reset prevSigs | testing | high | 2026-06-17 |
| LRN-037 | Protocol test-fix path missing re-gate before recheck | testing | high | 2026-06-15 |
| LRN-038 | Unconditional seam audit dispatch on empty seam paths | testing | high | 2026-06-15 |
| LRN-039 | SC-F1 emits annotation validator must skip — not raise — when eval_str resolution fails | sdk | high | 2026-06-16 |
| LRN-040 | Deterministic THREAD_ID in acceptance-api.js causes concurrent-run contamination | testing | high | 2026-06-17 |
| LRN-041 | Protocol-fix loop missing re-gate before recheck | testing | high | 2026-06-15 |
| LRN-042 | buildScenarioPrompt silently drops followUpTurns via JS destructuring default | testing | high | 2026-06-17 |
| LRN-043 | MCP tier-1 tools missing openWorldHint annotation causes client over-restriction | protocol | high | 2026-06-17 |
| LRN-044 | ValidationError swallowed by catch-all loop — SI-2 requires explicit enrichment | security | critical | 2026-06-17 |
| LRN-045 | JSON parse failure must return -32700, not -32602 (invalid-params) | protocol | high | 2026-06-17 |
| LRN-046 | A2UI DataPart emitted unconditionally — requires X-A2A-Extensions opt-in gate | protocol | critical | 2026-06-17 |
