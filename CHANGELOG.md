# Changelog

All notable changes to `agent-sdk`. SemVer applies to the stable core
(DESIGN.md §4.0); provisional surfaces (`agent_sdk.testing`, console
internals, `contrib/`) may change in minors with notice here.

## [0.2.0] — unreleased

### Added

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
