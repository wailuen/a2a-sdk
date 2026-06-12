# agent-sdk-harness — Claude Code plugin (DESIGN §11)

The build-time harness for [`agent-sdk`](../DESIGN.md). It turns "I want a new
A2A/AG-UI/MCP agent" into a working, conformance-checked repo without hand-wiring
protocol surfaces or auth plumbing. Every skill enforces the SDK's security
invariants (SI-1…SI-7) and zero-tolerance redteam gates — not trusting the
author to remember them.

## What's in it

### Skills

| Skill | Category | Function |
|---|---|---|
| `/new-agent` | bootstrap | interview → preflight git access → render `template/` (or `gh repo create --template`) → generate `MASTER_KEY` → first run → seed `.claude/` + `workspace/` |
| `/setup` | bootstrap | bootstrap a cloned `agent-template` repo: interview → preflight SDK via `git ls-remote` → substitute `{{placeholders}}` → generate `MASTER_KEY` → write manifest → first run. Run once, no SDK repo required. |
| `/add-tool` | extend | pydantic input + `@tools.tool` fn + test + console `sample` → wires `emits` and `tier` |
| `/add-source` | extend | `SourceAdapter` subclass + `CredentialField`s + `allowed_hosts` + `health_check` + test |
| `/agent-verify` | verify | boot agent → `/agent-stack-check` → OAuth-chain curl probes → optional Playwright console smoke → one report |
| `/provision` | operations | zero-to-running: verify `.env` → boot → bootstrap token → seed credentials → health-check sources → live tool call |
| `/upgrade` | operations | read pyproject.toml SHA → fetch latest → `/changelog` → confirm → update pin → reinstall → pytest → `/agent-verify` |
| `/changelog` | operations | categorised SDK git changelog between two SHAs (BREAKING / Protocol / Security / Feature / Fix) |
| `/diagnose` | operations | classify runtime failure to L1-L7 → probe the exact layer → root cause + fix prescription |
| `/migrate` | operations | source analysis → migration PRD → `/new-agent --no-run` → `/wave` per wave → `/agent-verify` |
| `/sdk-issue` | operations | classify finding (SDK-level vs agent-domain) → file structured GitHub issue on `wailuen/a2a-sdk`; agent-domain findings redirected to `/codify` |
| `/scenario` | planning | generate JTBD usage scenarios → `workspace/scenarios/` |
| `/codify` | knowledge | capture a learning (bug/fix/pattern) → `workspace/learning/LRN-NNN-*.md` |
| `/analyze` | planning | create/update PRD, ADR → `workspace/prd/` / `workspace/adr/` |
| `/todos` | planning | plan-only: generate + redteam wave plan without executing; use when you want to review the plan before `/wave` |
| `/implement` | execution | fully-unattended executor — all waves via model-driven Agent calls (no Workflow fan-out) |
| `/wave` | execution | **primary entry point**: plan all waves from PRD + execute each via `wave-cycle.js` (todos-redteam → implement → unit/phase redteam → protocol audit → codify + C-NNN registration → archive); or `/wave w001` to resume a specific wave |
| `/redteam` | quality | adversarial review across 8 dimensions; fail-closed on SI-1…SI-7; auto-codify |
| `/debug` | quality | fresh-lens debug at round 3+; read cold → diagnose root cause → fix |

### Agents

| Agent | Location | Role |
|---|---|---|
| `sdk-advisor` | `agents/project/sdk-advisor.md` | SDK extension conventions and invariant reviewer (BUILD + REVIEW modes) |
| `python-implementer` | `agents/project/python-implementer.md` | SI-enforcing Python implementer; test-first discipline |
| `redteam` | `agents/core/redteam.md` | Adversarial reviewer; 8 dimensions; fail-closed SIs; auto-codify |
| `analyst` | `agents/core/analyst.md` | PRD/ADR manager; FR/NFR templates; append-only ADRs |
| `planner` | `agents/core/planner.md` | Vertical-slice planner; parallel-group invariant enforcement |
| `codify` | `agents/core/codify.md` | Learning capture; LRN records; de-duplicate aggressively |
| `debug` | `agents/core/debug.md` | Fresh-lens root-cause analysis; cold read → diagnose → fix at root; auto-invoked at r3+ |

### Workflows

| Workflow | Function |
|---|---|
| `wave-cycle.js` | Deterministic 8-phase fan-out: Parse → Todos Redteam → Implement → Unit Redteam → Phase Redteam → Protocol Audit → Codify → Archive |

### Reference

| File | Contents |
|---|---|
| `reference/sdk-security-invariants.md` | SI-1…SI-7 descriptions, grep checks, prevention clauses |

## Workspace

Every generated agent repo gets a `workspace/` directory seeded by `/new-agent`.
All working documentation — PRDs, ADRs, todos, learnings, components, and
scenarios — lives there, grouped so Claude Code can access it across sessions.

```
{agent}/
├── workspace/
│   ├── README.md           ← index linking all dirs
│   ├── prd/                ← FR/NFR docs (p[NNN]-*.md)
│   ├── adr/                ← Architecture Decision Records (a[NNN]-*.md)
│   ├── todos/              ← phased work items (w[NNN]-*.md / plan.md)
│   │   ├── plan.md
│   │   ├── active/
│   │   ├── completed/
│   │   ├── deferred/
│   │   └── superseded/
│   ├── learning/           ← LRN-NNN codified learnings
│   ├── components/         ← reusable component inventory (C-NNN)
│   └── scenarios/          ← JTBD usage scenarios (NNN-theme.md)
└── .claude/
    ├── settings.json       ← allowlist + secret denylist
    ├── skills/
    │   ├── add-tool/       ← extend
    │   ├── add-source/     ← extend
    │   ├── agent-verify/   ← verify
    │   ├── provision/      ← operations
    │   ├── upgrade/        ← operations
    │   ├── changelog/      ← operations
    │   ├── diagnose/       ← operations
    │   ├── migrate/        ← operations
    │   ├── sdk-issue/      ← operations
    │   ├── scenario/       ← planning
    │   ├── codify/         ← knowledge
    │   ├── analyze/        ← planning
    │   ├── todos/          ← planning
    │   ├── implement/      ← execution
    │   ├── wave/           ← execution
    │   ├── redteam/        ← quality
    │   └── debug/          ← quality
    ├── agents/
    │   ├── core/
    │   │   ├── redteam.md
    │   │   ├── analyst.md
    │   │   ├── planner.md
    │   │   ├── codify.md
    │   │   └── debug.md
    │   └── project/
    │       ├── sdk-advisor.md
    │       └── python-implementer.md
    ├── workflows/
    │   └── wave-cycle.js
    └── reference/
        └── sdk-security-invariants.md
```

The `harness/workspace/` directory in this repo is the **template**; it is copied
into each new agent repo by `/new-agent` Phase 4.

## How it's delivered

`/new-agent` is run once, from a context where this plugin is available (install
it as a Claude Code plugin, or run from the SDK repo). When it scaffolds a new
agent it **seeds that repo's `.claude/` and `workspace/`** with the in-repo
subset, so the full skill set runs from inside the agent repo with no extra
install. `new-agent` itself is not copied (you only run it once, from outside).

```
harness/                         # this plugin (repo-level, not shipped in the wheel)
├── .claude-plugin/plugin.json
├── settings.json                # template settings (secret denylist)
├── skills/                      # 19 skills
├── agents/
│   ├── core/                    # portable: redteam, analyst, planner, codify, debug
│   └── project/                 # domain: sdk-advisor, python-implementer
├── workflows/
│   └── wave-cycle.js            # 8-phase deterministic orchestration
├── reference/
│   └── sdk-security-invariants.md
└── workspace/                   # template workspace (seeded into each new agent)

.claude/                         # sdk-dev harness (for SDK contributors)
├── settings.json
└── skills/
    ├── sdk-test/                # full test gate (unit + mypy + example stack-check)
    └── sdk-release/             # cut release: version bump + changelog + tag + push

{agent}/.claude/                 # seeded by /new-agent into each generated repo
├── settings.json
├── skills/                      # 17 skills (not new-agent)
├── agents/
│   ├── core/                    # redteam, analyst, planner, codify, debug
│   └── project/                 # sdk-advisor, python-implementer
├── workflows/
│   └── wave-cycle.js
└── reference/
    └── sdk-security-invariants.md

{agent}/workspace/               # seeded by /new-agent
├── README.md
├── {prd,adr,learning,components,scenarios}/README.md
└── todos/
    ├── README.md
    ├── active/README.md
    ├── completed/README.md
    ├── deferred/README.md
    └── superseded/README.md
```

## Execution model

```
/analyze ──► PRD + ADRs in workspace/prd/ / workspace/adr/
   │          redteam confirms before writing
   │
   ▼
/wave ──────► Planning step (runs once; identical to /todos)
   │               ├── Read PRD + learnings + components registry
   │               ├── planner agent → plan.md + w[NNN]-*.md wave files
   │               ├── auto-redteam loop (zero critiques) + codify learnings
   │               └── confirm: "N waves. Proceed?"
   │
   ▼    (for each wave in plan order)
   ├── wave-cycle.js (Workflow, one per wave)
   │       ├── Parse              (extract groups, creates paths, LRN baseline)
   │       ├── Todos Redteam      (SI annotations, Reuses: C-NNN, new candidates — written back to wave file)
   │       ├── Implement          (python-implementer, parallel groups, test-first)
   │       ├── Unit Redteam       (zero-tolerance per group; debug at r3+ and stall)
   │       ├── Phase Redteam      (zero-tolerance full wave; debug at r3+ and stall)
   │       ├── Protocol Audit     (a2a/ag-ui/a2ui advisors + seam check)
   │       ├── Codify             (parallel LRN captures; sequential C-NNN registration)
   │       └── Archive            (move wave, tick plan.md, backfill FR Implementation: fields)
   │
   └── auto-continue to next wave ──► (loop until all waves done or 🔴 block)

/todos       (plan-only; same planning logic as /wave; use to review plan before executing)
/implement   (all remaining waves, fully unattended, model-driven Agent calls)
```

## SDK Security Invariants

Checked at every redteam gate (fail-closed). Full reference in
`reference/sdk-security-invariants.md`.

| ID | Invariant | Severity |
|----|-----------|----------|
| SI-1 | No raw `httpx`/`aiohttp`/`requests` in `src/tools/` | Critical |
| SI-2 | No secrets/user-inputs in errors or logs | Critical |
| SI-3 | URL path params through `url_segment()`/`safe_id()` | High |
| SI-4 | Credentials via `self.credential()` only | High |
| SI-5 | Auth on all A2A/MCP/AG-UI endpoints | Critical |
| SI-6 | Upstream vendor keys in credential store only | Critical |
| SI-7 | Non-empty `allowed_hosts` on every SourceAdapter | High |

## GitHub template repo

`template/` in this repo is published as `github.com/wailuen/agent-template`
and marked as a GitHub Template Repository. There are three ways to start a
new agent:

| Mode | Command | When to use |
|------|---------|-------------|
| Template clone | clone `wailuen/agent-template` + `/setup` | no SDK repo needed; full harness in the template |
| Local copy | `/new-agent <name>` | SDK repo is a local sibling |
| GitHub template | `/new-agent <name> --from-github` | want a GitHub-hosted repo from day one |

The `--from-github` path runs:
```bash
gh repo create <name> --template wailuen/agent-template --private --clone
```
then fills in all placeholders and generates `MASTER_KEY` into `.env`, exactly
as the local path does. The resulting repo is already on GitHub — the user just
needs to push once they're happy with the first commit.

`template/` ships with `.claude/` pre-seeded so that cloning the template
directly (Path A above) gives the full harness immediately — no SDK repo or
plugin install needed. Run `/setup` from inside the clone.

```
template/.claude/
├── settings.json
├── .harness-manifest.json      ← {{SDK_SHA}} placeholder; filled by /setup
├── skills/                     ← 18 skills: 17 seeded + /setup
├── agents/core/                ← redteam, analyst, planner, codify, debug
├── agents/project/             ← sdk-advisor, python-implementer
├── workflows/wave-cycle.js
└── reference/sdk-security-invariants.md
```

To keep the template up to date: any change to `template/` or `harness/` should
be reflected in `wailuen/agent-template` so new clones get the latest scaffold
and skill set.

## SDK-dev harness

The `.claude/` directory at the SDK root provides skills for **SDK contributors**
(people working on `agent-sdk` itself, not people using it to build agents):

| Skill | Function |
|-------|----------|
| `/sdk-test` | Full test gate: pytest (unit + integration) + mypy + alphageo example stack-check |
| `/sdk-release` | Cut a release: version bump + categorised changelog + commit + tag + push |

These skills live in `.claude/skills/` at the repo root and are loaded when
Claude Code is opened in the `a2a-sdk` directory.

## Dependencies (reused, not reimplemented)

`/agent-verify` and the Protocol Audit phase of `wave-cycle.js` delegate protocol
judgments to the agent-interop check kit. Those must be installed where the skill runs:

- `agent-stack-check` skill
- `a2a-advisor`, `a2ui-advisor`, `ag-ui-advisor`, `mcp-advisor` agents

If the kit is absent, `/agent-verify` still runs its own boot + OAuth-chain legs
and says clearly that the stack-check leg was skipped — it never reports green
it didn't actually verify.

## Authority rule

These skills generate and review **agent-repo code**; they never restate or
re-derive protocol rules. Protocol conformance is owned by the check kit; SDK
convention/invariant judgment is owned by `sdk-advisor`. Keep the skills thin:
if an SDK contract seems wrong, fix it in the SDK (and `DESIGN.md`), not in a skill.
