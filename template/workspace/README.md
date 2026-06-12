# SDK harness — workspace

Working documentation for the agent-sdk harness plugin and its generated
agents. This directory is the template workspace seeded into every new agent
repo by `/new-agent` (SDK context) or `/setup` (template-clone path).

| Directory | Contents |
|-----------|----------|
| [`prd/`](prd/README.md) | Product requirements (FR/NFR) |
| [`adr/`](adr/README.md) | Architecture Decision Records |
| [`todos/`](todos/README.md) | Phased work items |
| [`learning/`](learning/README.md) | Codified learnings from bugs and red-team findings |
| [`components/`](components/README.md) | Reusable component inventory |
| [`scenarios/`](scenarios/README.md) | JTBD usage scenarios and live test results |

## Skills

| Skill | Purpose |
|-------|---------|
| `/new-agent` | Scaffold a new agent from the template |
| `/add-tool` | Add a tool to an existing agent |
| `/add-source` | Add a source adapter |
| `/agent-verify` | Conformance and OAuth-chain check |
| `/scenario` | Generate structured JTBD scenarios → `workspace/scenarios/` |
| `/codify` | Capture a learning → `workspace/learning/` |
| `/analyze` | Create/update PRD and ADR docs → `workspace/prd/` / `workspace/adr/` |
