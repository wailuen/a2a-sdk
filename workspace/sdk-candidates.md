# SDK issue candidates — w015 (2026-06-15)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: MarketBriefing structuredContent emits raw field dict instead of markdown string. In _handle_tools_call, artifact.wire() is called for all ContentModel subclasses including MarketBriefing, but DESIGN §4.3 mandates that MarketBriefing wire data must be the to_markdown() string. The A2UI translator correctly guards isinstance(artifact, MarketBriefing) before calling to_markdown(), but mcp.py has no such guard. Additionally, the outputSchema advertised in tools/list is a dict schema, contradicting the string-typed structuredContent that DESIGN requires.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: This is a bug in the SDK's MCP protocol route (agent_sdk/routes/mcp.py), an SDK internal. The fix touches SDK source only — no agent-specific tool code or domain adapter. The MCP route is explicitly listed under 'protocol routes (agent_sdk/routes/)' in the SDK-level scope.

## Candidate 2: Null gate response treated as pass (fail-open) at all four gate checkpoints in the template wave-cycle workflow: unitGate (line 538), phaseGate (line 630), protoFixGate (line 799), and preArchiveGate (line 1015) all use 'if (gate && gate.exitCode !== 0)'. When the gate agent returns null the condition is false and execution continues silently, violating LRN-017 RT-001 fail-closed invariant. The harness version correctly handles null with explicit null-checks and break/block.
- Severity: critical
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: This is a template scaffold defect in template/.claude/workflows/wave-cycle.js, which is part of the SDK's template scaffold. All agent projects derived from the template inherit the fail-open bug. Fixing the template is an SDK responsibility. Component is harness/template per the classification map.

## Candidate 3: Null redteam response in the unit redteam loop treated as clean (line 468: 'if (!rt || rt.findingsCount === 0) { break }'). A null agent response means the redteam agent crashed — the code cannot distinguish a clean pass from a crashed reviewer. The harness version (RT-004) correctly handles null by logging a warning, resetting prevSigs, and continuing so debug can engage next round instead of declaring the group clean.
- Severity: critical
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: Template scaffold defect inherited by all downstream agent projects. Null-vs-clean conflation in the unit redteam loop is a workflow correctness issue in the SDK-owned template scaffold, not agent domain code.

## Candidate 4: Null redteam response in the phase redteam loop also treated as clean (line 571: 'if (!rt || rt.findingsCount === 0) { break }'). Same RT-004 violation as the unit loop but in the phase redteam loop. A crashing phase redteam agent causes the wave to skip to Protocol Audit as if the full phase passed cleanly.
- Severity: critical
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: Same class of template scaffold defect as WC-002 (unit loop), applied to the phase redteam loop. SDK-owned template scaffold; not agent-specific.

## Candidate 5: After a gate RED in both unit redteam (lines 538-547) and phase redteam (lines 630-639), a fix agent is dispatched but no re-gate follows. The loop continues to the next round without confirming the fix succeeded. LRN-017 RT-002 mandates a re-gate after every test-fix agent. The harness version adds unitReGate and phaseReGate checks with deferred-note on second failure.
- Severity: high
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: Missing re-gate-after-fix discipline in the template scaffold workflow. This is a structural gap in the SDK-owned template that all downstream agent projects inherit. The fix is confined to template/.claude/workflows/wave-cycle.js.

## Candidate 6: The seam audit runs unconditionally for every protocol wave regardless of whether any route files appear in the creates list (line 739 pushes to advisorTasks with no guard). This wastes an agent call on non-route waves and produces vacuous results. The harness version (RT-005) derives seamPaths from allCreates using SEAM_ROUTE_MARKERS and skips the seam audit when seamPaths.length === 0.
- Severity: high
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: Unconditional seam-audit dispatch is a template scaffold efficiency and correctness gap. The missing SEAM_ROUTE_MARKERS guard exists in the harness but was not ported to the template. SDK-level template scaffold responsibility.

## Candidate 7: Null protoFixGate response is treated as a pass (line 799: 'if (protoFixGate && protoFixGate.exitCode !== 0)'). When the gate agent crashes after a protocol fix, the recheck dispatch proceeds even though the test suite state is unknown. The harness version explicitly checks 'if (!protoFixGate)' and sets both testsRed=true and protocolBlocked=true, blocking archive.
- Severity: high
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: This is WC-007, a template-only fail-open null check on the protoFixGate. Same RT-001 class as the four gate checkpoints. Template scaffold scope, SDK-owned.

## Candidate 8: Null archiveIntent response (GH-40 commit guard) silently passes as clean in both the harness and template wave-cycle workflows. When the archive-commit-check agent returns null, the condition 'if (archiveIntent && archiveIntent.offendingPaths && ...)' is false so the else branch fires and logs 'Commit check passed — all Creates: files are committed'. This is a false positive: the gate agent failed but archive proceeds with no block. All other null-agent responses carry explicit RT-001 handling; this one does not.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/wave-cycle.js
- Rationale: This defect is present in both harness/workflows/wave-cycle.js and template/.claude/workflows/wave-cycle.js. Because the harness is the source of truth that the template is derived from, the primary component is harness/workflow. Fixing the harness and re-syncing the template is the correct remediation path.

## Candidate 9: Persistent null redteam agent responses bypass the budget cap and can cause unbounded looping in both the unit redteam loop (max 5 rounds) and phase redteam loop (max 8 rounds). The null-rt path resets prevSigs and continues, but the budget-exit check ('if (uRound >= 5)' / 'if (pRound >= 8)') appears AFTER the continue statement. A redteam agent that repeatedly returns null will loop indefinitely at runtime cost until an external timeout fires.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/wave-cycle.js
- Rationale: Affects both harness/workflows/wave-cycle.js and template/.claude/workflows/wave-cycle.js. The harness is the source of truth, so the component is harness/workflow. The unbounded loop risk is a harness correctness issue that the template inherits.

## Candidate 10: Phase redteam null-response handler resets 'prevSigs = new Set()' (line 657), defeating stall detection in both harness and template files. The unit redteam null handler explicitly preserves prevSigs with a detailed comment explaining why: clearing prevSigs means a null round followed by a round with the same findings as the prior real round will not trigger sigsEqual. The phase loop silently violates the same invariant without comment.
- Severity: high
- Component: harness/workflow
- File: harness/workflows/wave-cycle.js
- Rationale: Present identically in harness/workflows/wave-cycle.js (line 657) and template/.claude/workflows/wave-cycle.js (line 656). Harness is the source of truth — component is harness/workflow. The prevSigs preservation rule is a harness-level stall-detection invariant.

## Candidate 11: Missing findingsCount cross-validation in both Unit Redteam and Phase Redteam loops in the template. The harness guards against an agent returning findingsCount=0 while findings.length > 0 (which would break clean despite real findings). The template is missing both checks, meaning an agent that misreports findingsCount=0 with a non-empty array would silently pass the zero-tolerance gate in all projects derived from the template.
- Severity: high
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: Template-only gap: the findingsCount cross-validation block present in harness/workflows/wave-cycle.js (lines 510-513 and 680-683) was not ported to the template scaffold. SDK-owned template scaffold responsibility.

## Candidate 12: Missing re-gate after proto:fix test-fix in the template. When the proto:fix gate returns RED and a test-fix agent is dispatched, the template proceeds directly to the protocol recheck without verifying the test-fix succeeded. The harness adds a gate:proto:fix:recheck agent call and blocks the recheck (setting protocolBlocked=true) if tests remain red. Agent projects using the template can silently proceed to a protocol recheck with a red test suite.
- Severity: high
- Component: harness/template
- File: template/.claude/workflows/wave-cycle.js
- Rationale: Template-only gap: the proto:fix re-gate discipline present in harness/workflows/wave-cycle.js (lines 989-1010) was not ported to the template scaffold. SDK-owned template scaffold responsibility, same class as WC-004 (unit/phase re-gate).
