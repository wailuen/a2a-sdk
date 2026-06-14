# w007 — GitHub issues #9–#12

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: 0.4.5.

---

- [ ] `GH-11` wave-cycle.js: split MCP surface from A2A, add dedicated mcp-advisor task ‖ group:G
  - Creates: (modifies `harness/workflows/wave-cycle.js`)
  - Reads: `harness/workflows/wave-cycle.js`
  - Severity: high
  - Root cause: A2A_SURFACE at line 23 includes `src/routes/mcp` and `src/routes/oauth`. When MCP-touching files appear in a wave, runA2A fires and dispatches a single a2a-advisor covering both A2A + MCP — one-advisor collapse that drops MCP-specific checks (Streamable-HTTP, OAuth 2.1 discovery, PKCE, initialize echo, tools/list shape).
  - AC: MCP_SURFACE constant = ['src/routes/mcp', 'src/routes/oauth'] added; those paths removed from A2A_SURFACE; runMCP boolean derived from allCreates matching MCP_SURFACE; when runMCP is true a dedicated `mcp-advisor` agentType is dispatched in parallel with a2a-advisor; mcp-advisor recheck block added to protoCritical fix path; protocol audit log line includes `MCP=` indicator.
  - GH: https://github.com/wailuen/a2a-sdk/issues/11

- [ ] `GH-10` harness: fix provision/setup for multi-backend LLM key seeding and correct API path ‖ group:G
  - Creates: (modifies `harness/skills/provision/SKILL.md`, `harness/skills/setup/SKILL.md`)
  - Reads: `harness/skills/provision/SKILL.md`, `harness/skills/setup/SKILL.md`, `agent_sdk/routes/admin.py`
  - Severity: high
  - Root cause: (1) provision/SKILL.md step 9 calls `POST /admin/credentials/<source>/<field>` — wrong method (should be PUT) and wrong path (missing `/api/`). (2) No idempotency gate before re-prompting the user. (3) setup/SKILL.md Phase 0 documents only Bedrock env vars; OpenAI and Azure OpenAI vars absent. (4) setup/SKILL.md Phase 3 instructs writing LLM API keys to .env — SI-6 violation; only non-secret routing vars go in .env; LLM keys go into __model__ namespace via `PUT /admin/api/credentials/__model__/<key_field>`.
  - AC: provision/SKILL.md step 9 uses `PUT /admin/api/credentials/<source>/<field>` and checks `"set": true` before re-prompting; setup/SKILL.md Phase 0 enumerates all four backends (Bedrock, OpenAI, Azure OpenAI) with exact env var names; setup/SKILL.md Phase 3 restricts .env writes to non-secret routing vars and adds a step to seed the LLM key via the credential store after bootstrapping.
  - GH: https://github.com/wailuen/a2a-sdk/issues/10

- [ ] `GH-9` harness: add SDK-issue classification pipeline to redteam, agent-verify, wave-cycle ‖ group:G
  - Creates: (modifies `harness/agents/core/redteam.md`, `harness/skills/agent-verify/SKILL.md`, `harness/workflows/wave-cycle.js`)
  - Reads: `harness/agents/core/redteam.md`, `harness/skills/agent-verify/SKILL.md`, `harness/workflows/wave-cycle.js`, `harness/skills/sdk-issue/SKILL.md`
  - Severity: medium
  - Root cause: redteam.md RT_SCHEMA has no `sdkCandidate` field; agent-verify has no SDK-candidates section and references stale "kit not installed" wording for --no-stack-check; wave-cycle.js Codify phase writes no workspace/sdk-candidates.md, so /sdk-issue has no auto-generated input from completed waves.
  - AC: redteam.md RT_SCHEMA includes optional `sdkCandidate: true` boolean; Output Format section requires SDK candidates to get a `/sdk-issue` callout; agent-verify Steps section adds a classification step + SDK candidates footer in report template; `--no-stack-check` rationale updated to "unavailable for this environment"; wave-cycle.js Codify phase adds a classification agent that writes workspace/sdk-candidates.md with all sdkCandidate findings, and its output is surfaced in the wave summary.
  - GH: https://github.com/wailuen/a2a-sdk/issues/9

- [ ] `GH-12` harness: accuracy fixes — /new-agent ref, advisor names, content-type count, SI-4 anti-patterns ‖ group:G
  - Creates: (modifies `harness/skills/upgrade/SKILL.md`, `harness/skills/wave/SKILL.md`, `harness/agents/project/sdk-advisor.md`, `harness/reference/sdk-security-invariants.md`)
  - Reads: `harness/skills/upgrade/SKILL.md`, `harness/skills/wave/SKILL.md`, `harness/agents/project/sdk-advisor.md`, `harness/reference/sdk-security-invariants.md`
  - Severity: low
  - Root cause: (1) upgrade/SKILL.md line 261 refers to `/new-agent` as the harness-manifest seeding mechanism. (2) wave/SKILL.md line 71 vaguely says "A2A/MCP/AG-UI/A2UI advisors" without naming the actual agentType strings. (3) sdk-advisor.md line 33 Agent constructor example omits `artifacts_dir`; line 65 says "14 FROZEN Standard Profile types" without the full 18-type picture (14 FROZEN + 4 RESERVED). (4) sdk-security-invariants.md SI-4 section lacks a walkthrough and anti-pattern examples; SI-6 Prevention references stale `scripts/set_upstream_credential.py`.
  - AC: upgrade/SKILL.md says "SDK provisioning tool" (not `/new-agent`) in the integration note; wave/SKILL.md names each advisor by agentType (`a2a-advisor`, `mcp-advisor`, `ag-ui-advisor`, `a2ui-advisor`); sdk-advisor.md constructor example includes `artifacts_dir` and count says "18 Standard Profile types (14 FROZEN + 4 RESERVED)"; sdk-security-invariants.md SI-4 section has a walkthrough paragraph + two anti-pattern examples; SI-6 Prevention replaces the stale scripts/ ref with the current admin console / `python -m agent_sdk provision` path.
  - GH: https://github.com/wailuen/a2a-sdk/issues/12
