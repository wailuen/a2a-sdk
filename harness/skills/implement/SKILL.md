---
name: implement
category: core
description: "Execute todos autonomously end-to-end — parallel specialist agents, smoke tests, zero-tolerance redteam loop per unit and phase, codify learnings, archive. Uses Opus."
---

# /implement — Parallel Execution Engine

Execute implementation todos by dispatching specialist agents in parallel,
then validate. **Run the full plan to completion in one invocation.**

## Usage

```
/implement [phase]
```

Examples:
- `/implement` — run all remaining incomplete waves to completion
- `/implement w001` — run that wave only (through full validate → archive)
- `/implement w001 w002` — run the listed waves in dependency order

## Autonomous mode (default)

Run every remaining wave to completion. Archive a wave, load the next,
continue. Surface progress only at milestones (wave archived, redteam round
complete, blocker hit) — no mid-step narration.

**Stop conditions** (only): `workspace/todos/active/` empty; hard external
blocker (missing credential, uninstallable tool, deferred-by-design todo);
user interrupt.

## Team of specialists

Discover project agents from `.claude/agents/project/`. Match work type:
- `python-implementer` — `src/` Python source and `tests/`
- `sdk-advisor` — SDK contract questions and review
- `analyst` — spec edits, PRD/ADR updates
- `redteam` — adversarial review
- `codify` — capture learnings
- `debug` — fresh-lens root-cause analysis for stalled fix loops
- `Explore` — read-only search

## Launch unit

Smallest thing that lands at once: a solo todo, or all todos sharing a
`‖ group:X` label (one shared redteam checkpoint). Every launch unit closes
redteam at zero findings before the next unit launches.

## Steps

1. **Select wave**: from args or next incomplete in `workspace/todos/plan.md`.
2. **Check deps**: all `Depends:` items must exist in `workspace/todos/completed/`.
3. **Read wave file**: extract todos and groups.
4. **Plan execution**: group by `‖ group` label; validate the parallel-group
   invariant before launching (no transitive `Depends:` between same-group todos).
5. **Iterate launch units in dependency order**. For each unit:
   a. **Execute** — single todo → one specialist; parallel wave → multiple
      `Agent` calls in one message. Each agent gets the todo body, ACs, file
      paths, context pointers, and `workspace/components/README.md` (so it
      reuses registered components). Explicit `Reuses: C-NNN` IDs are surfaced
      in the prompt.
   b. **Test-first** — for correctness-bearing todos: the specialist writes the
      failing test FIRST (confirm RED), then the code (confirm GREEN), then
      refactors. Unit is not done until the test exists and was demonstrably RED.
   c. **Encode SI regression tests** — when a todo touches a path covered by
      SI-1…SI-7, prefer a test that pins the invariant (e.g. a tool that calls
      httpx directly raises at test time) over relying on review alone.
   d. **Smoke test** — run `pytest -q tests/` scoped to changed files.
   e. **Unit-scoped break-fix loop (zero-tolerance)**:
      1. Launch `redteam` (Opus); scope = unit's `Creates:` paths + callers.
      2. Zero findings → advance. Otherwise continue.
      3. No-progress check: same finding signatures as prior round → escalate.
      4. Dispatch fix specialists in parallel (one per file bucket).
      5. Accumulate critical/high findings for the phase-end codify pass
         (LRN assignment happens after the unit and phase loops complete).
      6. After more than 3 rounds without zero (round 4+, or stall detected): dispatch `debug`
         for root-cause analysis. After 5 rounds: move todo to
         `workspace/todos/deferred/` with round history; continue next unit.
   f. **Register new shared components** if the unit landed `Creates: shared` —
      append a row to `workspace/components/README.md`.
   g. **Mark todo `[x]`** in the wave file.
6. **Phase-scoped break-fix loop (zero-tolerance)** — same cycle as 5e but
   scope = all `Creates:` across the whole wave. Debug fires after >3 failed rounds (round 4+, not 5)
   and on stall. Round budget: 8 before halting.
7. **Protocol Audit** — if `Creates:` paths touch any protocol surface
   (`src/routes/a2a`, `src/routes/mcp`, `src/routes/oauth`,
   `src/routes/agent_card`, `src/models/a2a`, `src/routes/ag_ui`, `src/a2ui/`,
   `src/models/content_types`), run parallel conformance advisors
   (`a2a-advisor`, `ag-ui-advisor`, `a2ui-advisor`) + seam check. Critical
   protocol findings: one fix round + recheck — if still critical, archive is
   blocked; write a deferred note to `workspace/todos/deferred/<wave>-protocol-blocked.md`
   and continue to the next wave (the blocked wave stays in `active/`).
8. **Codify** — deduplicate accumulated critical/high findings across all fix rounds
   and protocol audit. For each unique finding with a `codify:` line, assign the next
   LRN number and write `workspace/learning/LRN-NNN-<slug>.md`. Rewrite
   `workspace/learning/README.md`. Register any new C-NNN component candidates in
   `workspace/components/README.md`.
9. **Archive** — `mv active/<wave>.md completed/`; update `plan.md` (`[x]` +
   ✅ date); backfill FR `Implementation:` fields in `workspace/prd/`.
10. **Continue** — if more incomplete waves remain whose deps are met, loop to 1.
11. **Final report** — phases archived, total findings closed, LRN entries
    captured, deferrals + reasons.

## Rules

- **Autonomous**: never stop between waves for user input.
- **Parallel by default**: independent work fans out via `Agent`.
- **Zero-tolerance**: close every checkpoint before advancing.
- **All source under `src/`; all tests under `tests/`.**
- **Test-first for correctness-bearing code.**
- **Reuse > rebuild**: every specialist prompt includes `workspace/components/README.md`.
- **No file-conflict launches** — same-group todos must not share `Creates:`.
- **Update FR `Implementation:` fields** when a todo lands code satisfying an FR.
- **Deferred todos** → `workspace/todos/deferred/` with a reason header.
