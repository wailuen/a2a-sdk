# AlphaGeo Climate Risk Agent — agent-sdk conventions (enforced)

This repo is a thin domain layer over `agent-sdk`. Domain code lives in
`src/`; protocol surfaces (A2A, AG-UI, A2UI, MCP, OAuth, console) are SDK
behavior and are not reachable from this repo by design.

## Security invariants (never violate)

- **No raw `httpx`/`requests` in tools.** All outbound HTTP goes through
  `AlphaGeoSource` (or another `SourceAdapter`) — the base-class client
  enforces `allowed_hosts` and owns retries/timeouts.
- **No secrets or user input values in errors or logs. Ever.** Raise
  `AgentError(category, message, source=...)` with a generic message.
  Never interpolate credential values, tokens, or request payloads into
  exception text.
- **Path/URL parameters go through SDK validators.** Use
  `agent_sdk.validation.url_segment(...)` before interpolating anything
  into a URL path; `safe_id(...)` for identifiers.
- **Credentials are resolved, never read.** Use `self.credential("api_key")`
  inside `AlphaGeoSource` — it resolves from the `alphageo` namespace in
  the encrypted store, NOT from env vars. The upstream AlphaGeo key must
  NEVER appear in `.env`, argv, or logs (see `docs/adr/0001-credential-architecture.md`).
- **Adapters own retries.** Tools call adapter methods once; retry/backoff
  policy lives in the adapter.

## Two-key model (ADR 0001 — locked)

| Key | Owner | Location |
|-----|-------|----------|
| Client → Agent | caller | bearer header; hash stored in `__api_keys__` namespace |
| Agent → AlphaGeo | operator | `EncryptedSqliteStore` at `alphageo/api_key`; per-call `X-Agent-Credentials` override |
| Model (Azure) | operator | `.env` `SecretStr` — NOT in credential store |

## SDK conventions

- Tools: `@tools.tool(tier=..., emits=..., sample=...)` on an async fn.
  One positional pydantic input model; adapters injected as keyword-only
  params. Docstring = tool description exposed over MCP + A2A.
- `emits=ClimateRiskReport` drives the A2UI `ClimateRiskReport` card, the
  AG-UI `AGENT_ARTIFACT` payload, and the MCP `outputSchema`. Missing
  `--catalog urn:alphageo:climate:v1` in the client capability claim
  silently falls back to the `TextPart` only — not an error.
- Registration: `toolsets=[...]`, `agent.register_source(...)` in
  `src/main.py`. Forgotten wire-ups fail at `build_app()`, not at call time.
- Settings: `src/config.py` extends `BaseAgentSettings`; `make_settings()`
  factory. `AGENT_SDK_` prefix is reserved.
- Tests: `agent_sdk.testing` (`FakeModelClient`, `reply`, `tool_call`).
  Never call Azure OpenAI or AlphaGeo in unit tests.

## Live testing

```bash
# Seed the AlphaGeo upstream key (once per DATA_DIR):
python scripts/set_upstream_credential.py

# Single-query live turn (AG-UI):
python -m agent_sdk test-chat \
    --app src.main:app \
    --catalog urn:alphageo:climate:v1 \
    "What is the climate risk for NYC in 2050 under SSP585?"

# Interactive REPL:
python -m agent_sdk test-chat --app src.main:app --catalog urn:alphageo:climate:v1
```

## Workspace

All working documentation lives under `workspace/`:

| Directory | Contents |
|-----------|----------|
| `workspace/prd/` | FR/NFR requirements |
| `workspace/adr/` | Architecture Decision Records |
| `workspace/todos/` | Phased work items |
| `workspace/learning/` | LRN-NNN codified learnings |
| `workspace/components/` | Reusable component inventory |
| `workspace/scenarios/` | JTBD usage scenarios (10 live-tested) |

## Verification

`/agent-verify` boots the agent and runs protocol checks + curl probes.
Run it after adding tools, sources, or settings. Always redteam with the
relevant specialist before proceeding to the next task.
