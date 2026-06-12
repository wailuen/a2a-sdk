# Scenario catalog

JTBD usage scenarios for agents built with agent-sdk.
Run `/scenario` to generate new scenarios for a specific agent.

| File | Range | Domains | Status |
|------|-------|---------|--------|
| *(see each agent's `workspace/scenarios/` for agent-specific scenarios)* | | | |

## Format

Each scenario file (`NNN-theme.md`) contains entries in this shape:

```markdown
### SCN-NNN — Title
**Domain:** letter — name
**Persona:** who is asking
**Capability:** buildable | partial | gap
**Tools:** tool_name(params)  *(one line per discrete tool call)*

**Turn 1 (initial)**
> verbatim user prompt

**Turn 2 (reactive follow-up)**
> follow-up based on actual turn-1 response

**A2UI surface:** what card/component is emitted
**PRD signal:** what requirement or gap this surfaces
**Resolution:** *(gap/partial only)* what needs to be built
```

## Naming

`NNN-[theme].md` — e.g. `001-climate-risk.md`

Sequence numbers are per-agent, not global.
