---
name: migrate
category: core
description: "One-shot migration of an existing agent (not built on agent-sdk) to agent-sdk — analyses the source, produces a migration PRD, generates todos, and executes with /wave + zero-tolerance redteam to a clean, conformance-verified result."
---

# /migrate — Migrate an existing agent to agent-sdk

Lift an existing agent into `agent-sdk` without losing domain logic. The skill
reads the source agent's code, maps it to SDK extension points, generates a
migration PRD, plans the work as waves, and drives `/wave` to a zero-critique,
protocol-verified result.

## Usage

```
/migrate <source-path> [--agent-name <name>] [--dry-run]
```

- `source-path` — path to the existing agent's root directory (can be a sibling)
- `--agent-name` — kebab-case name for the new SDK agent (prompted if omitted)
- `--dry-run` — produce the migration PRD and wave plan only; do not scaffold or implement

## Phase 0 — Source analysis

1. Read the source agent's directory structure. Identify:
   - **Tools / capabilities** — functions exposed to the LLM. Map each to an
     `@tool` + pydantic input model.
   - **Data sources** — external HTTP APIs, databases, or file stores. Map each
     to a `SourceAdapter` subclass with `allowed_hosts` and `CredentialField`s.
   - **Auth model** — how callers authenticate today (API key / OAuth / none).
   - **Streaming** — does the agent stream responses? (→ AG-UI / A2A streaming)
   - **Content types / UI surfaces** — structured output shapes (→ A2UI content types)
   - **Skills / persona** — free-text prompts or skills exposed to users.
   - **Credentials** — where secrets are stored today (env vars, config files, vaults).
   - **Test coverage** — existing tests that express the contract.
   - **Protocol compliance gaps** — anything the source agent does that violates
     A2A v0.3.0 / AG-UI / MCP (e.g. incorrect error codes, missing `WWW-Authenticate`,
     wrong SSE shapes). These become migration correctness requirements.

2. Produce a **source inventory table**:

| Item | Source location | SDK mapping |
|------|----------------|-------------|
| Tool: `get_risk_report` | `tools/climate.py:get_risk` | `@tool` in `src/tools/climate.py` |
| Source: `AlphaGeo API` | `clients/alphageo.py` | `SourceAdapter` in `src/sources/alphageo.py` |
| Auth: API key header | `middleware/auth.py` | SDK `require_identity` (no migration needed) |
| Credential: `ALPHAGEO_KEY` in `.env` | `.env` | `CredentialField` in the adapter |
| Content: `ClimateRiskDict` | `models/output.py` | `ContentModel` subclass |
| Skill: `climate-risk.md` | `skills/` | Copy to `src/skills/` with frontmatter |

## Phase 1 — Migration PRD

3. Run `/analyze create prd` from the **harness context** (the SDK harness
   `workspace/prd/`, not the source agent's directory — the new agent workspace
   doesn't exist until Phase 2). The PRD file will be copied to the new agent's
   `workspace/prd/` after scaffolding in step 4. The PRD captures:
   - **FR-1…FR-N**: one FR per tool (preserve behaviour + add SI compliance)
   - **FR-N+1…**: one FR per source adapter (preserve calls + add `allowed_hosts`,
     credential store, health check)
   - **FR-N+M**: content type registrations
   - **NFR-1**: all protocol surfaces must pass `/agent-verify` post-migration
   - **NFR-2**: all existing tool contracts preserved (no behaviour regression)
   - **NFR-3**: secrets moved from env vars to credential store (SI-4, SI-6)

## Phase 2 — Scaffold

4. **Guard:** confirm the target directory (`<parent>/<agent-name>`) does not
   already exist. If it does, stop: "Migration creates a new directory alongside
   the source — in-place migration (overwriting the source) is not supported."

5. Run `/new-agent --no-run` with the target name. This produces the SDK scaffold
   with blank stubs. `--no-run` skips the first-boot walkthrough (credentials
   aren't seeded yet). Note: `/new-agent` Phase 1 will run a git preflight
   (`ssh -T` or `git ls-remote`) — this is expected and takes 5-10 s. Apply the
   same SSH remediation as for `/upgrade` if it fails.
   After scaffolding, copy the migration PRD from step 3 into the new agent's
   `workspace/prd/`.

6. Copy over reusable non-SDK files verbatim (skill markdown files, static data,
   test fixtures that don't depend on the old framework).

## Phase 3 — Plan + implement

7. Run `/todos` with the PRD from the new agent's workspace. The planner produces waves ordered by dependency:
   - **w000** — scaffold + persona + config (no domain logic)
   - **w001** — source adapters (one per wave group, parallel)
   - **w002** — content type registrations
   - **w003** — tools (one per wave group, parallel; each tool references its adapter)
   - **w004** — skill markdown files
   - **w005** — tests migrated from source (adapted for `FakeModelClient`)
   - **w006** — protocol compliance fixes (anything the source got wrong)

8. Run `/wave` for each wave in order. Each wave:
   - Implements the domain logic (ported from source, not rewritten from scratch)
   - Zero-tolerance redteam with SI-1…SI-7 enforcement
   - Protocol audit on w006
   - **LRNs** are captured automatically by the wave-cycle.js Codify phase. Each SI
     violation fixed during migration and each non-obvious porting decision should
     generate an LRN. The Phase 5 report's `LRNs captured` count is the sum of
     Codify-phase LRNs across all waves.

9. **Behaviour regression gate** (after all waves):
   For each original tool, compare the SDK tool's output schema and docstring
   against the source. Any narrowed output or changed semantics is a **high** finding.
   If the source had tests, port them using this pattern:
   - Replace any direct LLM/model call assertions with `FakeModelClient` stubs.
   - Keep HTTP-level mocks (e.g. `respx`, `responses`) for SourceAdapter calls —
     these remain valid.
   - Replace framework-level request/response fixtures with
     `httpx.AsyncClient(app=app, base_url='http://test')` where `app` is the
     SDK-built FastAPI app.
   - Any test that asserts on the old framework's internal call signatures must be
     rewritten (not just ported) — flag these explicitly.

## Phase 4 — Verification

10. Run `/provision` to seed credentials.
11. Run `/agent-verify` — the full OAuth-chain + conformance umbrella.
    A clean pass confirms the migrated agent is conformant.
12. Run `/scenario --live` for the top 3 scenarios from the source's README or
    existing test cases. Confirm real responses match expected behaviour.

## Phase 5 — Report

```
## Migration report — <source> → <target>
Source:         <source-path>
Target:         <target-path>  (agent-sdk @ <sha7>)

Source inventory:
  Tools:        <N>
  Sources:      <M>
  Content types: <K>
  Skills:       <J>

Waves completed: <N>
Redteam rounds:  <N total across all waves>
Protocol audit:  PASS | BLOCKED
/agent-verify:   PASS | FAIL

Behaviour delta (regressions found):
  <none | list of changed tool contracts>

SI violations fixed during migration:
  <none | SI-N: description (was in source, fixed in SDK)>

LRNs captured: <N>

Next:
  /scenario --live   (validate domain scenarios)
  git commit          (no commit made by this skill)
  git push
```

## Rules

- **Port, don't rewrite.** Domain logic is moved verbatim where possible.
  The SDK handles protocol wiring — the migration is not a redesign.
- **Every SI violation in the source becomes a migration FR**, not a post-migration
  cleanup task. The migrated agent ships clean.
- **No behaviour regression is acceptable.** A tool that returns different data
  shapes is a breaking change for existing callers. Flag it explicitly.
- **Secrets never transit the chat.** Credential values from the source `.env`
  are re-seeded interactively via `/provision`, not copied or echoed.
- `--dry-run` produces the PRD and wave plan but makes no file changes and does
  not scaffold. Use it to estimate scope before committing.
