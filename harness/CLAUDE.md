# agent-sdk harness — Claude Code conventions

The canonical agent conventions file is **`template/CLAUDE.md`** (one level up, at
`../template/CLAUDE.md` relative to this directory). That file is the single source
of truth for the SI table, credential model, SDK conventions, and workflow disciplines.

`harness/CLAUDE.md` (this file) intentionally contains no duplicated content.
The `/upgrade` skill's `harness-sync` step regenerates `template/CLAUDE.md` from
the SDK when invariants change — do not hand-edit the SI table or credential model
here; change them in `template/CLAUDE.md` and let `/upgrade` propagate.

## Harness-specific rules

- Harness skills live in `harness/skills/`; they are seeded into agent repos by
  `/new-agent` but are **not** modified by those repos.
- `harness/workspace/` is the workspace template; changes here propagate to new
  agents only — existing agent repos are unaffected.
- `harness/agents/` holds the agent definitions (redteam, analyst, planner, codify,
  debug, sdk-advisor, python-implementer). Edit them here; `/upgrade` re-seeds them.
- `harness/reference/sdk-security-invariants.md` is the grep-check reference for
  SI-1…SI-7. It must stay in sync with the SI table in `template/CLAUDE.md`.
