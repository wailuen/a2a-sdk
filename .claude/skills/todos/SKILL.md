---
name: todos
category: core
description: "Plan-only: generate and redteam a vertical-slice wave plan from the PRD, without executing. /wave (no args) subsumes this for the normal flow — use /todos when you want to review or edit the plan before running /wave."
---

# /todos — Plan-Only Mode

Generate and redteam a vertical-slice wave plan from the PRD. Does not
execute anything — use `/wave` (no args) to plan **and** execute in one
command.

Use `/todos` when you want to inspect or edit the plan before committing to
execution, or when you need to regenerate a superseded plan independently.

## Usage

```
/todos [action]
```

Actions:
- `(no args)` — generate the full plan from PRD + ADR + learnings
- `status` — progress dashboard across all waves
- `next` — show the next actionable wave

## Plan structure

```
workspace/todos/
  plan.md           # Master plan: waves, deps, parallel groups
  active/           # Wave files being implemented
    w000-scaffold.md
    w001-core.md
  completed/        # Passed redteam (archived by /wave or /implement)
  deferred/         # Postponed with reason header
  superseded/       # Replaced by newer plans
```

## Steps — Generate

1. Read `workspace/prd/README.md`, `workspace/adr/README.md`.
2. Read `workspace/learning/README.md` — incorporate Prevention clauses as
   plan constraints.
3. Read `.claude/reference/sdk-security-invariants.md` — for any todo whose
   code path touches an SI, the planner emits a `SI:` field + matching AC so
   `/redteam` does not have to fail closed reactively.
4. Read `workspace/components/README.md` — reference existing components by
   ID via `Reuses:` instead of re-planning equivalent capability.
5. Read any existing `workspace/todos/` files to avoid duplication. If a
   previous `plan.md` exists, move it to `superseded/` with a date suffix.
6. Launch the `planner` agent (Opus) — produces `plan.md` + wave files under
   `active/`.
7. **Auto-redteam loop until zero critiques** (all severities). See `/redteam`.
   Codify novel learnings from the plan-review round.
8. Report: wave count, slice count, parallel groups.

## Steps — Status

1. Read `workspace/todos/plan.md` and all files under `active/`, `completed/`,
   `deferred/`.
2. Report: per-wave completion %, blocked items, next actionable wave.

## Rules

- Every todo traces to a FR-N or ADR-N.
- Correctness-bearing todos carry a `Tests:` field and a test-first AC.
- Security-invariant paths carry a `SI:` field.
- **The auto-redteam loop is mandatory** — plans ship only at zero critiques
  (all severities).
- Superseded plans are never deleted — moved to `superseded/` for history.
- **Parallel-group invariant** — `‖ group:X` is an affirmative claim that
  every todo in the group can launch simultaneously. The planner enforces this
  at generation time; the redteam loop verifies it; `/implement` validates it
  again before launch.
