# Changelog

All notable changes to `agent-sdk`. SemVer applies to the stable core
(DESIGN.md §4.0); provisional surfaces (`agent_sdk.testing`, console
internals, `contrib/`) may change in minors with notice here.

## [0.4.0] — 2026-06-14

### Added

- **Azure Table Storage persistence backends** — `AzureTableCredentialStore`,
  `AzureTableCommitmentStore`, `AzureTableSubscriptionStore` replace SQLite for multi-replica
  Azure Container Apps deployments. Auto-detected from `AZURE_STORAGE_CONNECTION_STRING`
  (connection string) or `AZURE_STORAGE_ACCOUNT_NAME` (managed identity). AES-256-GCM
  encryption envelope preserved end-to-end. ETag optimistic concurrency preserves
  at-most-once commitment firing across replicas. Install with `pip install agent-sdk[azure]`.

- **`migrate-store` CLI** — `python -m agent_sdk migrate-store [--data-dir ./data]
  [--dry-run] [--force]` migrates existing SQLite credential, commitment, and subscription
  data to Azure Table Storage.

- **`NS_MODEL` namespace + model-backend credential store** — LLM API keys
  (OpenAI, Azure OpenAI, Anthropic) are now stored in the encrypted credential
  store under the reserved `__model__` namespace, never in `.env`. The admin
  console gains a "Model Backend" section (`GET/PUT /admin/api/credentials/__model__/*`)
  with fields for `openai_api_key`, `azure_openai_api_key`, and `anthropic_api_key`.
  `NS_MODEL` exported from `agent_sdk`.

- **OpenAI / Azure OpenAI as built-in model backends** — set `OPENAI_MODEL`
  (or `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT`) in `.env` (non-secret
  operational vars) and seed the API key once via `/admin → Model Backend`. No
  `model_client=` plumbing in `main.py` required; `Agent.build_app()` resolves
  the key from the credential store automatically.

### Changed

- **`BaseAgentSettings`** — gains three new optional fields for Azure Storage auto-detection:
  `AZURE_STORAGE_CONNECTION_STRING` (`SecretStr | None`), `AZURE_STORAGE_ACCOUNT_NAME`
  (`str | None`), `AZURE_STORAGE_TABLE_PREFIX` (`str`, default `"agent"`). Also gains five
  non-secret fields for OpenAI/Azure backends: `OPENAI_MODEL`, `OPENAI_BASE_URL`,
  `AZURE_OPENAI_ENDPOINT`, `AZURE_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`. Removed
  guidance to put API keys in `.env` via `SecretStr` subclass fields — that is now an
  SI-6 violation.
- **`Agent._build_model_client()`** — accepts `credential_store` and resolves OpenAI
  key from `__model__/openai_api_key` (or `azure_openai_api_key`) automatically.
  Bedrock path unchanged.

---

## [0.3.0] — 2026-06-13

### Changed

- **Credential store clarity** — `SourceAdapter.credential()` docstring now
  explains the full lifecycle (admin console → encrypted store → decrypt on
  call). `BaseAgentSettings` comments clarify that `MASTER_KEY` encrypts the
  store (not an upstream API key) and that Bedrock uses IAM (no key in `.env`).
  `.env.example` gains a prominent box listing what belongs and what does not.
  `CLAUDE.md` credential model table adds a "How to access it" column plus
  four labeled anti-pattern examples. SI-4 reference adds a step-by-step
  store lifecycle and common anti-patterns; SI-6 reference lists what does
  belong in `.env` to contrast with upstream keys.

---

## [0.2.0] — 2026-06-13

### Added

- **`ArtifactLoader`** — prompts live in `src/artifacts/*.md` as Jinja2
  templates (StrictUndefined, frontmatter-aware, compiled once at init).
  `Agent` gains `artifacts_dir=` and `artifact_vars=`; `persona=` remains
  supported for backward compat. `ArtifactLoader` exported from
  `agent_sdk`. Template and AlphaGeo example migrated.
  Harness gains `/add-artifact` opt-in migration skill.

- **`/acceptance` skill** — autonomous acceptance gate, the final step in
  the agent development lifecycle (after `/provision` + `/agent-verify`).
  Generates 30+ seed scenario files across 7 dimensions (happy path per
  tool, multi-turn depth, edge cases, A2UI content type coverage, skill
  activation, interrupt/resume, error/degraded upstream), then drives live
  multi-turn AG-UI conversations against the provisioned agent and
  judge-scores every turn 1–10 for content coherency. Self-healing fix
  loop (max 5 rounds) classifies each failure (`code-bug`,
  `content-type-gap`, `persona-gap`, `upstream-issue`, `bad-scenario`),
  dispatches targeted fix agents, restarts the server, and re-tests only
  the failing scenarios — autonomously, without human intervention.
  Does not exit until all scenarios score ≥ 7 or the round budget is
  exhausted. Persona-gap escalations are non-blocking.
  `--ux` path runs the same scenarios sequentially in a single Playwright
  browser session against the admin test console, adding a rendering
  fidelity score (1–10) that exercises the full intended purpose of every
  A2UI Standard Profile component type emitted (click, sort, filter, form
  submit, hover tooltip, deleteSurface lifecycle, console error check).
  Both scores must be ≥ 7 per turn for a UX pass. OBO agents require a
  one-time manual browser login; everything after is autonomous.
  Results written to `workspace/scenarios/results/run-NNN.json` with
  per-scenario score history across runs.

- **`acceptance-api.js` workflow** — parallel fan-out runner invoked by
  `/acceptance`. Each scenario agent drives a 3–5 turn conversation via
  `ChatDriver` over `POST /ag-ui/run` (SSE), persisting message state
  across turns in `/tmp/`, scoring each reply, generating contextual
  follow-ups from the actual agent response, and classifying failures.
  Returns `SCENARIO_RESULT_SCHEMA`-validated structured objects.

- **`/provision --env [dev|prod]`** — new environment flag controls which
  ADR credentials file is written. After minting the first admin API key,
  `/provision` now writes `workspace/adr/ADR-000-<env>-credentials.md`
  (gitignored) so skills like `/acceptance` can authenticate autonomously
  on future runs without re-bootstrapping. On 409 (already bootstrapped),
  checks for an existing ADR-000 before halting. Auto-adds the credentials
  glob to `.gitignore` if absent.

- **`A2AError`** exported from `agent_sdk.testing` — typed exception
  carrying `code` and `message`; raised by `ChatDriver` on A2A error
  responses and interrupt states. Now part of `testing.__all__`.

- **Chat console markdown rendering** — agent replies in the test console
  are rendered as Markdown (bold, italic, inline/fenced code, headings,
  lists, blockquotes). `streamingBubble` re-renders incrementally so
  formatting resolves live while the model is typing, not only at end of
  stream. No external deps; all model output via DOM text nodes (XSS-safe,
  strict CSP compliant).

- **Chat console responsive full-height layout** — transcript and SSE
  trace panels fill the full viewport height with composer pinned at the
  bottom. Responsive breakpoints: ≤900 px single-column stacked panels,
  ≤600 px trace panel hidden.

### Fixed

- **A2A / AG-UI / A2UI / MCP full-stack conformance** — 17 findings from
  `/agent-stack-check` + 8 iterative `/redteam` cycles resolved to zero
  Critical/High across all four protocol layers and six seams:
  - Body size caps (1 MB) on `message/send` and `ag-ui/run` (MCP-consistent).
  - DNS-rebinding guard in `SourceAdapter._on_request`; reads `dev_mode`
    Pydantic attribute (was incorrectly `DEV_MODE` env-var name).
  - SI-7 build-time check: `SourceAdapter.__init__` requires non-empty
    `allowed_hosts` or `_no_http = True` opt-out for non-HTTP adapters.
  - `CommitmentsSource._no_http = True` to pass the SI-7 check.
  - Bootstrap token written to `stderr` (was `stdout` — leaked to captured
    output).
  - Log handler changed to `stderr` to prevent log lines in captured output.
  - SI-2: unknown tool name in loop sanitized before log interpolation
    (truncate to 64 chars, replace control chars).
  - AG-UI `AGENT_ARTIFACT` wire uses camelCase `{dataType, toolName, data}`
    (was snake_case; AG-UI camelCase invariant).
  - AG-UI `A2UI_UPDATE` envelope wraps message array: `{messages: [...]}`.
  - Agent card removes `urn:agui:run:v1` from `capabilities.extensions[]`;
    AG-UI is advertised via `x-agui.endpoint` only (wrong slot per A2UI F2).
  - `forwarding.bind()` called in `ag_ui_run` before creating the worker
    task so credentials are bound in the correct context.
  - `serverInfo` in MCP `initialize` response includes `title` field
    (MCP 2025-06-18).
  - `register_content_type` enforces global component-name uniqueness.
  - Console `chat.js` AGENT_ARTIFACT consumer reads camelCase keys
    (`dataType`, `toolName`).
  - `a2uiClientCapabilities` in console includes `version`, `catalogs`,
    `tier` on both A2A and AG-UI paths.

- **`ChatDriver` A2A consumer conformance** (D7 hard-MUST floor):
  - Card discovery: fetches and caches `/.well-known/agent-card.json`
    before first request; selects transport from `preferredTransport`.
  - Message/Task discrimination: checks `result.get("kind") == "message"`
    before accessing `task["id"]`.
  - `X-A2A-Extensions` header sent on `message:send`; response echo read
    to confirm activation (`_a2ui_active` flag).
  - Interrupt states (`input-required`, `auth-required`) fire `"interrupt"`
    emit and raise `A2AError` instead of polling to timeout.
  - `extract_a2ui` dispatches on `DataPart.metadata.mimeType`
    (`"application/a2ui+json"`) at the part level, not artifact level.
  - `A2UI_MIME` sourced from `A2UI_MIME_TYPE` constant in
    `models/content_types` (removes local duplicate).

---

## [0.1.0] — 2026-06-13

Initial release.

### Added
- `Agent` / `build_app()`: single FastAPI app exposing A2A v0.3.0
  (HTTP+JSON), AG-UI (SSE), A2UI v0.9.1 Standard Profile v1 artifacts,
  MCP (2025-06-18, Streamable HTTP) behind OAuth 2.1, the agent card, and
  the admin console.
- `ToolSet` / `@tool` with tiers (1 = query: A2A+MCP, 2 = composite: A2A
  only), `emits=` content types, console `sample=`, adapter injection via
  keyword-only annotations, `ToolInterrupt` for input-/auth-required
  pauses with typed resume handlers.
- `SourceAdapter` base: allowed-hosts enforcement on every hop, redirect
  pinning, retry-once policy, namespaced credential resolution from the
  AES-256-GCM encrypted store.
- Loop policies: max turns, tiered tool timeouts, wall-clock deadline
  (suspended during interrupts), cumulative token budget across resumes,
  task-local result cache.
- Auth: API keys (single-use bootstrap token on zero-key startup), OAuth
  2.1 AS for `/mcp` (S256 PKCE, refresh rotation with family revocation,
  two-value audience), kind-tagged identities with per-surface assertions,
  rate limiting with trusted-proxy-aware client IPs.
- Standard Profile v1: 14 frozen content types; domain-card extension API
  (`ContentModel` subclass + own `catalog_id` + `register_content_type`).
- `agent_sdk.testing`: `FakeModelClient`, `reply`, `tool_call`,
  `ChatDriver` (multi-turn AG-UI/A2A driver for integration tests and
  `python -m agent_sdk test-chat`).
- Admin console (vanilla JS, strict CSP) at `/admin`: keys, credentials,
  tool try-out, self-check.
- Repo-level `template/` (the ~10-file agent footprint) and `docs/`.
- Claude Code harness plugin (`harness/`) with 18 seeded skills covering
  the full agent development lifecycle: scaffold → implement →
  zero-tolerance redteam → conformance → acceptance → ops.
- AlphaGeo climate-risk agent (`examples/alphageo/`) as the worked
  reference implementation and SDK CI target.
- `contrib/` (EXPERIMENTAL): `action_gate`, `obo`, `commitments`,
  `webhooks` — validated by the m365 reference agent port.
