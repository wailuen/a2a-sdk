# agent-sdk

Build production-grade A2A / AG-UI / A2UI agents with an OAuth-protected MCP
surface by writing **only domain code** — tools, source adapters, persona, and
config (~10 files). Every protocol surface and auth layer is SDK behavior.

```python
from agent_sdk import Agent, ToolSet

tools = ToolSet()

@tools.tool(tier=1, emits=ClimateRiskReport)
async def get_risk_report(inp: RiskInput, *, geo: GeoAdapter) -> ClimateRiskReport:
    """Fetch a climate-risk report for a location."""
    return await geo.fetch_risk(inp.location, inp.scenario)

agent = Agent(settings=make_settings(), persona=PERSONA, toolsets=[tools])
app = agent.build_app()   # FastAPI — A2A + AG-UI + A2UI + MCP + OAuth + console
```

---

## Fastest path — Claude Code harness

The harness is a set of Claude Code skills that take you from an idea to a
running, conformance-verified agent. You write the domain logic; the harness
enforces security invariants, runs zero-tolerance redteam gates, and walks
every ceremony that the SDK can't automate.

### 1 — Prerequisites

| Tool | Required version | Notes |
|------|-----------------|-------|
| Python | ≥ 3.12 | SDK hard requirement |
| uv | latest | fast venv + install |
| Claude Code | latest | runs the harness skills |
| gh CLI | latest | for `--from-github` option |
| SSH key | loaded in `ssh-agent` | accesses this private SDK repo |

### 2 — Load the harness

Clone this repo alongside your future agent repos. Claude Code auto-detects
the plugin when you open the `a2a-sdk` directory:

```bash
git clone git@github.com:wailuen/a2a-sdk.git
cd a2a-sdk
# open in Claude Code — the harness plugin loads from harness/.claude-plugin/plugin.json
```

### 3 — Scaffold a new agent

Run `/new-agent` in Claude Code. It interviews you, preflights your SSH
access to this repo, renders the template, generates a strong `MASTER_KEY`
into `.env`, seeds the new repo's `.claude/` with all 17 harness skills, and
walks the first boot.

```text
/new-agent my-agent
```

Optional flags:

```text
/new-agent my-agent --from-github    # creates wailuen/my-agent on GitHub first
/new-agent my-agent --no-run         # scaffold only (used internally by /migrate)
```

**Path A — template clone (no SDK repo needed):**
Clone [`wailuen/agent-template`](https://github.com/wailuen/agent-template) (or
click **Use this template** on GitHub), open in Claude Code, and run `/setup`.
The `.claude/` is pre-seeded; `/setup` interviews you, resolves the SDK SHA via
`git ls-remote`, substitutes all `{{placeholders}}`, generates `MASTER_KEY` into
`.env`, and walks first boot — no local SDK repo required. After that the full
development lifecycle is available: `/analyze` → `/todos` → `/wave`.

### 4 — Provision credentials

Once the scaffold is ready (or after cloning an existing agent):

```text
/provision
```

This walks: `.env` check → venv install → bootstrap token → first admin API
key → credential seeding for each source adapter → source health-checks →
optional live tool call. No secrets are echoed or written to files beyond
`.env` and the encrypted credential store.

### 5 — Develop

Define the agent's domain with `/analyze`, then let `/wave` plan and build everything:

```text
/analyze    # create a PRD (FRs + NFRs) and ADRs; redteam confirms before writing
/wave       # plan all waves from PRD, then execute each end-to-end
```

`/wave` without a wave ID is the primary entry point — it plans and executes in one command:

```text
Plan step (once):  Read PRD → planner agent → plan.md + wave files → auto-redteam loop → confirm
Per-wave cycle:    Todos Redteam (SI annotations, C-NNN reuse) →
                   Implement (parallel groups, test-first) →
                   Unit Redteam (zero-tolerance; debug at r3+) →
                   Phase Redteam (zero-tolerance; debug at r3+) →
                   Protocol Audit (A2A/AG-UI/A2UI/MCP conformance) →
                   Codify (LRNs + C-NNN registration) →
                   Archive → auto-continue to next wave
```

Every redteam gate is zero-tolerance — no finding leaves a wave. The debug agent fires
automatically at round 3+ when findings stall. At every junction where there's a
learning, it's codified automatically.

Add tools and source adapters with:

```text
/add-tool     # pydantic input model + @tool fn + test + console sample
/add-source   # SourceAdapter subclass + CredentialFields + health_check + test
```

Use `/todos` to review or edit the wave plan before running `/wave`.

### 6 — Verify

```text
/agent-verify
```

Boots the agent, runs `/agent-stack-check` (A2A + AG-UI + A2UI + MCP), and
runs OAuth-chain curl probes. Reports PASS or a severity-ranked issue list.
Run after every `/wave` and before every commit.

### 7 — Upgrade the SDK

When this repo has new commits:

```text
/upgrade            # shows /changelog → confirm → updates pin → reinstalls → /agent-verify
/changelog a1b2 c3d4   # preview categorised diff between two SHAs only
```

`/upgrade` is rollback-safe: if the reinstall fails, it reverts `pyproject.toml`
and restores the previous venv state before stopping.

---

## Skill reference

Skills live in the seeded `.claude/skills/` of every generated agent repo.

| Skill | Category | What it does |
|-------|----------|-------------|
| `/add-tool` | extend | pydantic input + `@tool` fn + test + `sample` |
| `/add-source` | extend | `SourceAdapter` + `CredentialField`s + `health_check` + test |
| `/agent-verify` | verify | boot → `agent-stack-check` → OAuth-chain probes → one report |
| `/provision` | ops | zero-to-running: `.env` → boot → bootstrap → seed credentials → health-check |
| `/upgrade` | ops | read SHA → `/changelog` → confirm → update pin → reinstall → verify |
| `/changelog` | ops | categorised SDK diff between two SHAs (BREAKING / Protocol / Security / Feature) |
| `/diagnose` | ops | classify runtime failure L1–L7 → concrete probe → root-cause prescription |
| `/migrate` | ops | source analysis → migration PRD → `/wave` per wave → `/agent-verify` |
| `/sdk-issue` | ops | classify finding → if SDK-level, file structured GitHub issue on `wailuen/a2a-sdk`; agent-domain findings redirected to `/codify` |
| `/analyze` | planning | create/update PRD or ADR |
| `/todos` | planning | vertical-slice wave plan from PRD |
| `/scenario` | planning | generate JTBD usage scenarios |
| `/wave` | execution | single wave via `wave-cycle.js` |
| `/implement` | execution | all waves unattended |
| `/redteam` | quality | adversarial review, 8 dimensions, SI-1…SI-7 fail-closed |
| `/debug` | quality | fresh-lens root-cause, cold read → diagnose → fix |
| `/codify` | knowledge | capture a learning → `workspace/learning/LRN-NNN-*.md` |

> `/new-agent` is in the harness plugin only (not seeded — it runs once, from
> the `a2a-sdk` Claude Code context). All other skills including `/upgrade`,
> `/changelog`, `/provision`, `/diagnose`, `/migrate`, and `/sdk-issue` are
> seeded into every generated agent repo.

---

## Day-2 operations

### Diagnose a broken agent

```text
/diagnose boot            # agent won't start
/diagnose 401             # all requests return 401
/diagnose tool geocode    # one tool is erroring
/diagnose source alphageo # a source adapter is failing
```

The skill classifies failures to one of 7 layers (Config / SDK boot / Domain
wiring / Credentials / Protocol surface / Upstream / Test), probes the
specific layer with targeted commands, and prescribes the exact file and
change needed. Advisory only — never edits.

### Migrate an existing agent onto the SDK

```text
/migrate ../old-agent --agent-name my-agent
```

Reads the source, builds a mapping table (tools → `@tool`, HTTP clients →
`SourceAdapter`, secrets in `.env` → credential store), generates a migration
PRD, scaffolds the new repo, and executes every wave with zero-tolerance
redteam. SI violations found in the source become migration requirements —
the migrated agent ships clean.

Use `--dry-run` to get the PRD and wave plan without touching disk.

---

## Security invariants

Enforced at every redteam gate (fail-closed). Full grep checks in
`.claude/reference/sdk-security-invariants.md`.

| ID | Invariant | Severity |
|----|-----------|----------|
| SI-1 | No raw `httpx` / `aiohttp` / `requests` in `src/tools/` — all outbound HTTP through a `SourceAdapter` | Critical |
| SI-2 | No secrets or user-input values in errors or logs — raise `AgentError` with a generic message | Critical |
| SI-3 | Path/URL params through `url_segment()` / `safe_id()` — never f-string raw input into a URL | High |
| SI-4 | Credentials via `self.credential()` only — never `os.environ` in tools or adapters | High |
| SI-5 | Auth on all A2A / MCP / AG-UI endpoints — every route uses `Depends(require_identity)` | Critical |
| SI-6 | Upstream vendor keys in credential store only — never in `.env`, argv, or logs | Critical |
| SI-7 | Non-empty `allowed_hosts` on every `SourceAdapter` — no wildcard | High |

---

## What the SDK handles

You write tools, adapters, and config. The SDK owns everything else:

| Surface | SDK behavior |
|---------|-------------|
| **A2A v0.3.0** | HTTP+JSON + SSE tasks, streaming, interrupt/resume, identity-bound access, full error table |
| **AG-UI** | `POST /ag-ui/run` SSE, frozen CUSTOM event contracts |
| **A2UI v0.9.1** | Standard Profile v1 content types → self-cleaning cards over A2A DataParts and AG-UI CUSTOM events |
| **MCP 2025-06-18** | Streamable HTTP, PKCE, DCR, token rotation, two-value audience, exact CORS |
| **OAuth 2.1** | Full server-side chain: metadata, DCR, authorize, token, rotate, revoke |
| **Agentic loop** | Bedrock Converse (default) or any `ModelClient`, tool tiers, deadlines, token budgets, interrupts, skills |
| **Operations** | Encrypted credential store, API key lifecycle, first-run bootstrap, rate limiting, admin console, self-checks |

---

## Manual install (without the harness)

```toml
# pyproject.toml — pin by SHA (tags are mutable; SHAs aren't)
dependencies = [
    "agent-sdk @ git+ssh://git@github.com/wailuen/a2a-sdk.git@<sha>",  # vX.Y.Z
]
```

```bash
python3.12 -m venv .venv
VIRTUAL_ENV=.venv uv pip install -e ".[dev]"
cp .env.example .env   # fill MASTER_KEY, BEDROCK_REGION, BEDROCK_MODEL_ARN
DEV_MODE=true .venv/bin/uvicorn src.main:app --port 8000 --workers 1
# first boot prints a single-use bootstrap token — paste into http://localhost:8000/admin
```

See [docs/getting-started.md](docs/getting-started.md) for the manual
assembly walkthrough.

---

## SDK contributor workflow

For contributors working on the SDK itself (not on agents built with it),
open `a2a-sdk` in Claude Code and use the sdk-dev skills:

```text
/sdk-test              # pytest + mypy + alphageo example stack-check
/sdk-release 1.3.0     # version bump + changelog + tag + push
```

`/sdk-test` cross-checks that the example's venv is running the SDK under
test (not a pip-cached version). `/sdk-release` detects the first release
(no prior tags), bumps the right version field for your build backend, and
pushes `HEAD` — not hardcoded `main`.

---

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/getting-started.md](docs/getting-started.md) | Manual install + assembly walkthrough |
| [docs/tools.md](docs/tools.md) | Tool tiers, `emits`, `sample`, interrupt/resume |
| [docs/sources.md](docs/sources.md) | `SourceAdapter`, `CredentialField`, `allowed_hosts`, `health_check` |
| [docs/content-types.md](docs/content-types.md) | A2UI content types, domain catalogs, `to_plain_text()` fallback |
| [docs/protocols.md](docs/protocols.md) | A2A, AG-UI, A2UI, MCP endpoint reference |
| [docs/security.md](docs/security.md) | SI-1…SI-7, credential model, OAuth chain |
| [docs/console.md](docs/console.md) | Admin + test console |
| [docs/deployment.md](docs/deployment.md) | One process, one origin, reverse-proxy rules |
| [docs/testing.md](docs/testing.md) | `FakeModelClient`, `reply`, `tool_call`, `respx` patterns |
| [DESIGN.md](DESIGN.md) | Full architecture |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [harness/README.md](harness/README.md) | Harness reference: all skills, agents, workflow detail |
| [examples/alphageo/](examples/alphageo/) | Worked example: AlphaGeo climate-risk analyst |

---

**Deployment invariant:** one process, one origin per agent. `PUBLIC_URL`
drives every advertised URL. See [DESIGN.md §2](DESIGN.md) and
[docs/deployment.md](docs/deployment.md).
