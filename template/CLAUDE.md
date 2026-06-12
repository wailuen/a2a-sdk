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

## Credential model (two-key)

| Key | Path | Auth to |
|-----|------|---------|
| SDK API key | Minted in admin console, sent as `Authorization: Bearer` by callers | This agent |
| Upstream key | Encrypted credential store (`self.credential("...")`) | Upstream APIs |
| Model backend | `.env` as `SecretStr` (Bedrock: IAM — no key needed; Azure/OpenAI: env var) | LLM backend |

Never put upstream keys in `.env`. Never log either key.

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

# Protocol smoke
/agent-verify

# Full wave
/wave w001
```

`.claude/reference/sdk-security-invariants.md` has grep checks for each SI.
