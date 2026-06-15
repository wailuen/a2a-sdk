# {{AGENT_NAME}} — agent-sdk conventions (enforced)

This repo is a thin domain layer over `agent-sdk`. Domain code lives in
`src/`; protocol surfaces (A2A, AG-UI, A2UI, MCP, OAuth, console) are SDK
behavior and are not reachable from this repo by design.

## Execution style

Think like Andrej Karpathy: be the simplest thing that could possibly work.
No premature abstractions. No defensive code for scenarios that can't happen.
No features the PRD doesn't mention. When in doubt, read the code.

**Agent registry (invoke by name):**

| Agent | When to invoke |
|---|---|
| `redteam` | After every implementation batch — zero-tolerance fix loop |
| `analyst` | When drafting or reviewing PRDs and ADRs |
| `planner` | When breaking work into todos (`/todos`) |
| `codify` | After any non-obvious root cause — capture the LRN |
| `sdk-advisor` | Questions about SDK conventions, extension points, invariants |
| `python-implementer` | Writing or fixing Python source files |
| `a2a-advisor` | A2A v0.3.0 conformance questions, design, and remediation |
| `mcp-advisor` | MCP server build advice and Claude.ai connector conformance |
| `a2ui-advisor` | A2UI protocol + Standard Profile v1 spec and conformance |
| `ag-ui-advisor` | AG-UI event catalog, SSE transport, GenUI mode wiring |

**Workflow skills (development loop):**

| Skill | When to use |
|---|---|
| `/provision` | First-time agent setup — installs deps, seeds workspace |
| `/setup` | Assign port, set env vars |
| `/todos` | Break work into a typed wave plan |
| `/wave` | Execute one wave end-to-end (implement → redteam → protocol audit → archive) |
| `/implement` | Implement a single todo with tests |
| `/redteam` | Adversarial review against spec (runs inside `/wave` automatically) |
| `/agent-verify` | Boot agent + full-stack conformance + OAuth-chain probes |
| `/acceptance` | Run JTBD scenario acceptance suite |
| `/add-tool` | Scaffold a new tool + adapter |
| `/add-source` | Scaffold a new SourceAdapter |
| `/add-artifact` | Migrate a hardcoded persona to `src/artifacts/system.md` |
| `/upgrade` | Sync harness files to a new SDK version |
| `/analyze` | Produce a gap analysis for a new capability |
| `/codify` | Capture a root cause as a permanent LRN |
| `/debug` | Root-cause a failing test or tool error |
| `/diagnose` | Triage unexpected agent behaviour |
| `/migrate` | Cross-wave refactor planning |
| `/scenario` | Draft a new JTBD acceptance scenario |
| `/changelog` | Generate release notes for a version bump |
| `/sdk-issue` | File a confirmed SDK bug or enhancement as a GitHub issue |
| `/sdk-issue-scan` | Batch-file SDK-level findings from a wave or redteam; reads `workspace/sdk-candidates.md` |

**Compliance skills (protocol conformance audits):**

| Skill | When to use |
|---|---|
| `/agent-stack-check` | Full-stack interop audit — MCP + A2A + AG-UI + A2UI in one pass |
| `/a2a-check` | A2A v0.3.0 conformance sweep (server + consumer roles) |
| `/mcp-check` | MCP server + Claude.ai connector conformance |
| `/ag-ui-check` | AG-UI event and transport conformance |
| `/a2ui-check` | A2UI protocol v0.9.1 + Standard Profile v1 conformance |

**Core disciplines:**

- **Test-first for correctness-bearing code.** Write the failing test first
  (RED), then the code (GREEN), then refactor. A todo that skips RED is incomplete.
- **Zero-tolerance redteam gates.** No finding survives a wave. Fix → re-redteam
  → repeat until clean.
- **Learning-as-code.** Every non-obvious root cause becomes an LRN record in
  `workspace/learning/`. The planner and redteam read these on every run.
- **Vertical slices, not layers.** Each wave delivers a working slice end-to-end;
  no horizontal layers that are done but untestable.

## Security invariants (never violate)

These are checked by `redteam` at every gate (fail-closed). Absence of evidence
of compliance = finding.

| ID | Invariant | Severity |
|----|-----------|----------|
| **SI-1** | No raw `httpx`/`aiohttp`/`requests` in `src/tools/`. All outbound HTTP through a `SourceAdapter` — the base-class client enforces `allowed_hosts` and owns retries. | Critical |
| **SI-2** | No secrets or user-input values in errors or logs. Raise `AgentError(category, "generic message", source=...)`. Never interpolate credential values, tokens, or request payloads into exception text. | Critical |
| **SI-3** | Path/URL parameters go through SDK validators. Use `agent_sdk.validation.url_segment(...)` before interpolating into a URL path; `safe_id(...)` for identifiers. Never f-string raw input into a URL. | High |
| **SI-4** | Credentials are resolved, never read. Use `self.credential("field_name")` — resolves only from that adapter's namespace in the encrypted store. Never `os.environ` in tools or adapters. | High |
| **SI-5** | All A2A/MCP/AG-UI endpoints require auth. Every router uses `Depends(require_identity)` except `/.well-known/` and `/health`. | Critical |
| **SI-6** | Upstream vendor keys in credential store only. Never in `.env`, CLI args, or logs. | Critical |
| **SI-7** | Every `SourceAdapter` subclass has non-empty `allowed_hosts`. No wildcard. | High |

Full grep checks in `.claude/reference/sdk-security-invariants.md`.

## SDK conventions

- Tools: `@tools.tool(tier=..., emits=..., sample=...)` on an async fn;
  one positional pydantic input model; adapters as keyword-only params
  annotated with the adapter class (exact-class match injects them).
  Docstring = tool description. Tier 1 = query (A2A + MCP),
  tier 2 = composite (A2A only).
- `emits=` must be a registered Profile/domain content type — it drives
  A2UI cards, AG-UI `AGENT_ARTIFACT` payloads and the MCP `outputSchema`.
  `build_app()` rejects unknown types at boot.
- Registration is explicit (`toolsets=[...]`, `agent.register_source(...)`)
  — nothing registers via import side effects. A forgotten wire-up fails
  at `build_app()`, never at call time.
- Interrupts: raise `ToolInterrupt(reason, message, response_schema=...,
  resume_handler=...)`. Never block a tool waiting for user input.
- Skills: markdown files under `src/skills/` with `name`/`description`
  frontmatter; the loop exposes them via the `load_skill` tool. Keep each
  skill self-contained; the catalog line comes from `description`.
- Settings: extend `BaseAgentSettings` in `src/config.py`; expose a
  `make_settings()` factory (no import-time instantiation). The
  `AGENT_SDK_` env prefix is reserved by the SDK.
- Tests: use `agent_sdk.testing` (`FakeModelClient`, `reply`, `tool_call`)
  against an isolated `Agent` instance. Never call the live model backend in tests.

## Credential model

| Key | Where it lives | How to access it | Auth to |
|-----|---------------|-----------------|---------|
| SDK API key | Minted in admin console (`/admin`) | Sent by callers as `Authorization: Bearer` — you never read this | This agent |
| Upstream/vendor key | Encrypted credential store (AES-256-GCM, keyed by MASTER_KEY) | `self.credential("field_name")` inside a `SourceAdapter` | Upstream APIs (CRM, financial data, Graph, etc.) |
| LLM API key | Encrypted credential store (`__model__` namespace) | SDK reads it at boot from `/admin → Model Backend`; never in `.env` | LLM backend |
| Model backend config | `.env` — non-secret operational vars only (`BEDROCK_MODEL_ARN`, `OPENAI_MODEL`, `AZURE_OPENAI_ENDPOINT`, etc.) | `Settings` fields; no secrets here | routing only |
| Azure Storage connection string | `.env` — operational infra config (treat as secret; use managed identity in prod) | `AZURE_STORAGE_CONNECTION_STRING` env var (read by SDK auto-detection, not by adapter code) | Azure Table Storage |

> **Note:** `AZURE_STORAGE_CONNECTION_STRING` is the one exception to the "no secrets in .env" rule — it is infrastructure plumbing, not an upstream API key. Prefer managed identity (`AZURE_STORAGE_ACCOUNT_NAME` only, no key) in production ACA deployments.

**Common mistakes (all caught by `/redteam` — fail-closed):**

- ❌ `os.environ["MY_API_KEY"]` in a tool or adapter → SI-4 violation. Use `self.credential("my_api_key")`.
- ❌ `MY_VENDOR_KEY=...` in `.env` → SI-6 violation. Set it once via `/admin → Credentials`.
- ❌ `OPENAI_API_KEY=sk-...` in `.env` → SI-6 violation. Seed it once via `/provision` or `/admin → Model Backend`.
- ❌ `azure_openai_api_key: SecretStr` in `Settings` → SI-6 violation. The key goes in the credential store, not settings.
- ❌ `settings.some_api_key` in a `SourceAdapter` → SI-4 violation. Settings fields are for *operational* config (URLs, timeouts, feature flags), not credentials.

Never put upstream keys in `.env`. Never log either key.

## Credential ADR discipline (enforced by hook)

Every credential seeded during development must be recorded in the workspace ADR.
This is enforced by a `PostToolUse` hook in `.claude/settings.json` that fires
whenever a credential is written via the admin API.

**Rule:** After ANY of the following, immediately update
`workspace/adr/ADR-001-<env>-credentials.md`:
- `PUT /admin/api/credentials/<namespace>/<field>` (source, model, bedrock)
- `/provision` (writes ADR-001 automatically in Phase 3d)
- Manual credential rotation via the admin console

**What to record:** namespace + field name + set status. **Never the value.**

```markdown
| alphageo  | api_key           | ✓ |
| __model__ | openai_api_key    | ✓ |
```

`workspace/adr/ADR-001-*-credentials.md` is gitignored (same as ADR-000).
If the file does not exist, create it from the template in `/provision` Phase 3d.

## Workspace layout

```
workspace/
├── README.md           ← index
├── prd/                ← FR/NFR docs  (p[NNN]-*.md)
├── adr/                ← ADRs         (a[NNN]-*.md)
├── todos/              ← waves        (w[NNN]-*.md, plan.md)
│   ├── active/
│   ├── completed/
│   ├── deferred/
│   └── superseded/
├── learning/           ← LRN records  (LRN-NNN-*.md)
├── components/         ← C-NNN inventory
└── scenarios/          ← JTBD scenarios
```

## Verification

Run after adding tools, sources, or settings:

```bash
# Boot check
DEV_MODE=true uvicorn src.main:app --port 8000 --workers 1

# Protocol smoke (boots agent, runs full-stack conformance + OAuth-chain probes)
/agent-verify

# Conformance-only (no boot — static + optional live)
/agent-stack-check

# Full wave
/wave w001
```

`.claude/reference/sdk-security-invariants.md` has grep checks for each SI.
