# SDK issue candidates — w032 (2026-07-14)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: RT-001: GH-110's guard_origin module (agent_sdk/common/origin.py) was extracted mid-wave but shipped git-untracked and absent from the w032 todo's Creates: list, even though a2a.py, ag_ui.py, and mcp.py all import it at module load. If the archive/commit step only stages declared paths, the shipped package raises ImportError at boot on every protocol surface (A2A, AG-UI, MCP) — a total deploy failure. Companion new test files and the LRN-115 learning doc are likewise untracked and undeclared.
- Severity: high
- Component: harness/workflow
- File: agent_sdk/common/origin.py
- Rationale: The defect is in the wave/todo archival process itself (a shared module extracted mid-wave not added to any todo's Creates: list, and the archive commit not staging new untracked paths before tagging) rather than in protocol runtime behavior — this is a harness/workflow gap (todos-redteam / wave-cycle archive step), squarely inside harness/workflows scope, that risks shipping an unimportable package.

## Candidate 2: agent_sdk/routes/mcp.py's _handle_tools_call invokes every resolved tool via entry.invoke(), which explicitly raises TypeError for any tool where decl.is_generator is True (long_running=True / async-generator tools), instead of branching to entry.invoke_gen() the way agent_sdk/agent/loop.py's dispatcher does. The TypeError is swallowed by a blanket except-Exception and surfaced as a generic 'tool execution failed' isError, even though such tools are explicitly supported (tests/test_gh87_deferred_task.py) and advertised as normal callable Tier-1 tools via tools/list. This breaks the module's own documented 'Tier 1 surface parity' guarantee: identical tools work over A2A/AG-UI but always fail over MCP.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: Direct bug in SDK-owned protocol route code (routes/mcp.py's tools/call handler) that fails to replicate the is_generator dispatch branch already present in the SDK's own agent/loop.py, causing a real MCP protocol-surface parity violation — core SDK/protocol-routes territory, not agent-domain tool logic.

## Candidate 3: agent_sdk/a2ui/catalog.py's get_system_prompt_section() is the one function among its four siblings (supported_catalogs, data_types_for_catalog, a2ui_extension) that does not accept/thread an allowed_components parameter through the existing _filtered_types() helper, so it always teaches the LLM the full 14-type Standard Profile catalog regardless of settings.a2ui_allowed_components. The sole call site (agent_sdk/app.py:546, build_app()) calls it with zero arguments and never passes the allowlist, even though the same setting is threaded into _validate_emits() and the agent-card extension a few lines away. Net effect: an agent configured to restrict the catalog (SC-D2) still has its system prompt teach full schemas/few-shot JSON for disallowed component types, and since _validate_emits() only gates tool-declared emits= targets (not the LLM's free-form JSON), nothing stops the model from spontaneously emitting a disallowed component that reaches a core/extended-tier client.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/a2ui/catalog.py
- Rationale: Bug in the SDK's own A2UI catalog module and its wiring in agent_sdk/app.py's build_app() — a gap in one of four enforcement points for the SC-D2 allowlist restriction that the SDK defines and documents (config.py's a2ui_allowed_components). This is core SDK/A2UI-catalog scope, not agent-specific code.

## Candidate 4: DESIGN.md §5.5 states a single blanket rule for MCP-Protocol-Version negotiation ('absent → assume 2025-03-26') that is stale post-GH-77: agent_sdk/routes/mcp.py's Streamable HTTP path (POST /mcp) now rejects an absent header with HTTP 400 on non-initialize requests, and only the Legacy SSE path (POST /mcp/messages) actually assumes 2025-03-26 when absent. mcp.py's own module docstring was corrected for this split in commit bbfe353, but DESIGN.md §5.5 and REVIEWS.md's Round-1 disposition table were never updated, so the canonical spec doc now contradicts the shipped, tested behavior (tests/test_mcp_gh77_absent_version_header.py) — risking a future contributor 'fixing' mcp_post() to match the stale doc and regressing GH-77.
- Severity: high
- Component: protocol/mcp
- File: DESIGN.md
- Rationale: DESIGN.md is the SDK's canonical protocol-surface spec and agent_sdk/routes/mcp.py is SDK route code; the drift between them is an SDK-level doc/code consistency defect in core protocol documentation (§5.5), not an agent-domain concern — it affects every agent built on the SDK and any future contributor or agent-stack-check pass that treats DESIGN.md as ground truth.
