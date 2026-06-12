# agent-sdk-harness — Claude Code plugin (DESIGN §11)

The build-time harness for [`agent-sdk`](../DESIGN.md). It turns "I want a new
A2A/AG-UI/MCP agent" into a working, conformance-checked repo without hand-wiring
protocol surfaces or auth plumbing. Every skill enforces the SDK's security
invariants (no raw HTTP in tools, no secrets in errors/logs, validated path
params) instead of trusting the author to remember them.

## What's in it

| Component | Type | Function |
|---|---|---|
| `/new-agent` | skill | interview → preflight git access → render `template/` → generate `MASTER_KEY` → first run + console walkthrough → seed the repo's `.claude/` + `workspace/` |
| `/add-tool` | skill | pydantic input + `@tools.tool` fn + test + console `sample` → wires `emits` and `tier` |
| `/add-source` | skill | `SourceAdapter` subclass + `CredentialField`s + `allowed_hosts` + `health_check` + test |
| `/agent-verify` | skill | boot agent → `/agent-stack-check` → OAuth-chain curl probes → optional Playwright console smoke → one report |
| `/scenario` | skill | generate JTBD usage scenarios → `workspace/scenarios/` |
| `/codify` | skill | capture a learning (bug/fix/pattern) → `workspace/learning/` |
| `/analyze` | skill | create/update PRD, ADR, todos → `workspace/prd/` / `workspace/adr/` |
| `sdk-advisor` | agent | reasons about SDK extension points, conventions, and invariants; reviews agent code; never fixes silently |

The rendered agent's `CLAUDE.md` (the §11 invariants file) ships in
[`../template/CLAUDE.md`](../template/CLAUDE.md) and is dropped into every new
repo by `/new-agent`.

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
│   ├── todos/              ← phased work items (w[NNN]-*.md)
│   ├── learning/           ← LRN-NNN codified learnings
│   ├── components/         ← reusable component inventory (C-NNN)
│   └── scenarios/          ← JTBD usage scenarios (NNN-theme.md)
└── .claude/
    ├── skills/{add-tool,add-source,agent-verify,scenario,codify,analyze}/
    └── agents/sdk-advisor.md
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
├── skills/{new-agent,add-tool,add-source,agent-verify,scenario,codify,analyze}/SKILL.md
├── agents/sdk-advisor.md
└── workspace/                   # template workspace (seeded into each new agent)

{agent}/.claude/                 # seeded by /new-agent into each generated repo
├── skills/{add-tool,add-source,agent-verify,scenario,codify,analyze}/SKILL.md
└── agents/sdk-advisor.md

{agent}/workspace/               # seeded by /new-agent
├── README.md
└── {prd,adr,todos,learning,components,scenarios}/README.md
```

## Dependencies (reused, not reimplemented)

`/agent-verify` is an **orchestrator** — it delegates protocol judgments to the
agent-interop check kit and only adds the probes that kit doesn't own. Those must
be installed where `/agent-verify` runs:

- `agent-stack-check` skill (the umbrella conformance auditor)
- the four protocol advisors: `a2a-advisor`, `a2ui-advisor`, `ag-ui-advisor`, `mcp-advisor`
- the four per-protocol check skills: `/a2a-check`, `/a2ui-check`, `/ag-ui-check`, `/mcp-check`

If the kit is absent, `/agent-verify` still runs its own boot + OAuth-chain +
console legs and says clearly that the stack-check leg was skipped — it never
reports a green that it didn't actually verify.

## Authority rule

These skills generate and review **agent-repo code**; they never restate or
re-derive protocol rules. Protocol conformance is owned by the check kit; SDK
convention/invariant judgment is owned by `sdk-advisor`. Keep the skills thin: if
an SDK contract seems wrong, fix it in the SDK (and `DESIGN.md`), not in a skill.
