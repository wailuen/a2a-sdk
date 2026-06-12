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
| `/new-agent` | bootstrap | interview → preflight git access → render `template/` → generate `MASTER_KEY` → first run + console walkthrough → seed the repo's `.claude/` + `workspace/` |
| `/add-tool` | extend | pydantic input + `@tools.tool` fn + test + console `sample` → wires `emits` and `tier` |
| `/add-source` | extend | `SourceAdapter` subclass + `CredentialField`s + `allowed_hosts` + `health_check` + test |
| `/agent-verify` | verify | boot agent → `/agent-stack-check` → OAuth-chain curl probes → optional Playwright console smoke → one report |
| `/scenario` | planning | generate JTBD usage scenarios → `workspace/scenarios/` |
| `/codify` | knowledge | capture a learning (bug/fix/pattern) → `workspace/learning/LRN-NNN-*.md` |
| `/analyze` | planning | create/update PRD, ADR, todos → `workspace/prd/` / `workspace/adr/` |
| `/todos` | planning | vertical-slice implementation plan with auto-redteam → `workspace/todos/` |
| `/implement` | execution | model-driven autonomous executor — runs all waves in dependency order without user gating |
| `/wave` | execution | single-wave executor via `wave-cycle.js` Workflow → implement → redteam → protocol audit → codify → archive |
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
| `wave-cycle.js` | Deterministic 7-phase fan-out: Parse → Implement → Unit Redteam → Phase Redteam → Protocol Audit → Codify → Archive |

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
    │   │   └── codify.md
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
├── skills/                      # 12 skills
├── agents/
│   ├── core/                    # portable: redteam, analyst, planner, codify, debug
│   └── project/                 # domain: sdk-advisor, python-implementer
├── workflows/
│   └── wave-cycle.js            # 7-phase deterministic orchestration
├── reference/
│   └── sdk-security-invariants.md
└── workspace/                   # template workspace (seeded into each new agent)

{agent}/.claude/                 # seeded by /new-agent into each generated repo
├── settings.json
├── skills/                      # 11 skills (not new-agent)
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
/todos ──► generates plan.md + w[NNN]-*.md wave files
   │
   ▼
/wave w001 ──► wave-cycle.js (Workflow)
   │               ├── Parse
   │               ├── Implement  (python-implementer, parallel groups)
   │               ├── Unit Redteam  (redteam, zero-tolerance; debug fires at r3+ and on stall)
   │               ├── Phase Redteam  (redteam, zero-tolerance; debug fires at r3+ and on stall)
   │               ├── Protocol Audit  (a2a/ag-ui/a2ui advisors + seam check)
   │               ├── Codify  (LRN captures, learning/README update)
   │               └── Archive  (move wave, tick plan.md, backfill FRs)
   │
   ▼
review → /wave w002 → ...
   │
   ▼
/implement  (all remaining waves, unattended)
```

## SDK Security Invariants

Checked at every redteam gate (fail-closed). Full reference in
`reference/sdk-security-invariants.md`.

| ID | Invariant | Severity |
|----|-----------|----------|
| SI-1 | No raw HTTP in `src/tools/` | Critical |
| SI-2 | No secrets/user-inputs in errors or logs | Critical |
| SI-3 | URL path params through `url_segment()`/`safe_id()` | High |
| SI-4 | Credentials via `self.credential()` only | High |
| SI-5 | Auth on all A2A/MCP/AG-UI endpoints | Critical |
| SI-6 | Upstream vendor keys in credential store only | Critical |
| SI-7 | Non-empty `allowed_hosts` on every SourceAdapter | High |

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
