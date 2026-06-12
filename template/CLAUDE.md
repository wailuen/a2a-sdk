# {{AGENT_NAME}} — agent-sdk conventions (enforced)

This repo is a thin domain layer over `agent-sdk`. Domain code lives in
`src/`; protocol surfaces (A2A, AG-UI, A2UI, MCP, OAuth, console) are SDK
behavior and are not reachable from this repo by design.

## Security invariants (never violate)

- **No raw `httpx`/`requests` in tools.** All outbound HTTP goes through a
  `SourceAdapter` — the base-class client enforces `allowed_hosts` and owns
  retries/timeouts. A tool that needs a new host needs a new/updated
  adapter, not an ad-hoc client.
- **No secrets or user input values in errors or logs. Ever.** Raise
  `AgentError(category, message, source=...)` with a generic message; the
  SDK redacts and maps it onto each protocol. Never interpolate credential
  values, tokens, or request payloads into exception text.
- **Path/URL parameters go through SDK validators.** Use
  `agent_sdk.validation.url_segment(...)` before interpolating anything
  into a URL path; `safe_id(...)` for identifiers. Never f-string raw
  input into a URL.
- **Credentials are resolved, never read.** Inside an adapter use
  `self.credential("field_name")` — it resolves only from that source's
  namespace in the encrypted store. Never read credential env vars in
  tools, never cache plaintext.
- **Adapters own retries.** Tools call adapter methods once; retry/backoff
  policy is adapter code.

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
  against an isolated `Agent` instance. Never call Bedrock in tests.

## Verification

`/agent-verify` boots the agent and runs the protocol checks + curl
probes. Run it after adding tools, sources, or settings.
