---
name: wave
category: core
description: "Primary development entry point after /analyze. Without a wave ID: reads PRD → plans ALL waves (planner agent + auto-redteam loop) → confirms → executes each in sequence via wave-cycle.js (todos-redteam → implement → unit/phase redteam → protocol audit → codify + C-NNN registration → archive). With a wave ID: execute that specific wave only (resumption). status: progress dashboard."
---

# /wave — Plan and Execute

The primary development command after `/analyze`. Without a wave ID it reads
the PRD, plans all waves, redteams the plan, and executes each wave in sequence.
Each wave runs a full 8-phase cycle — including a Todos Redteam pass before
any implementation, zero-tolerance fix loops, and auto-codify at the end.

## Usage

```
/wave [w<NNN> | status | --plan-only]
```

- `(no args)` — plan all waves from PRD (if no plan yet), then execute each in sequence
- `w001` — execute that specific wave only (resumption after a block or manual override)
- `status` — progress dashboard: active / completed / deferred counts + dates
- `--plan-only` — generate + redteam the wave plan, do not execute (same output as `/todos`)

---

## Mode A — Full run (`/wave` with no args)

### Planning step (runs once; plan generation (steps 6–9) skipped if plan.md + active/ waves already exist and user confirms "use")

1. Read `workspace/prd/README.md` and `workspace/adr/README.md`.
2. Read `workspace/learning/README.md` — incorporate `Prevention:` clauses as
   plan constraints. Any SI-1…SI-7 path touched by a todo must carry a `SI:` field.
3. Read `.claude/reference/sdk-security-invariants.md`.
4. Read `workspace/components/README.md` — reference existing C-NNN components by
   ID via `Reuses:` instead of re-planning equivalent capability.
5. Check `workspace/todos/` for an existing plan. If one exists, show the summary
   and ask: "Existing plan found (N waves). Use it, or replace? [use/replace]"
   - `use` → skip to the Execution step.
   - `replace` → move current plan to `superseded/` with a date suffix, then continue.
6. Invoke the `planner` agent — produces `workspace/todos/plan.md` and wave files
   under `workspace/todos/active/`. **Planner instruction: maximize parallel execution.**
   Assign todos with no file conflict (non-overlapping `Creates:` paths and no
   cross-todo `Depends:`) to the same `‖ group:` label so `wave-cycle.js` runs them
   concurrently. Only separate into distinct groups when a `Depends:` chain exists
   between them. Prefer one tier of many parallel todos over many sequential tiers.
7. **Auto-redteam loop until zero critiques (all severities):**
   - Run `redteam` scoped to the plan files.
   - If findings: invoke `planner` to fix; re-redteam. Cap at 3 rounds; log any
     remaining issues and continue (planning issues do not block execution).
   - Codify any novel learnings surfaced in this plan-review pass.
8. Show plan summary: wave count, scopes, SI-flagged todos, registry reuses, dep order.
9. **Confirm with user**: "N waves planned. Proceed? [y/n]"

### Execution step — per wave in plan order

For each wave whose `Depends:` items are all in `completed/`:

1. **Check deps** — if any `Depends:` item is still in `active/` or `deferred/`,
   stop and report which dep is blocking.
2. **Launch `wave-cycle.js`**:
   ```js
   Workflow({
     scriptPath: ".claude/workflows/wave-cycle.js",
     args: { waveFile: "<absolute path to active wave file>", today: "<YYYY-MM-DD>" }
   })
   ```
   The workflow runs 8 phases for this wave:
   - **Parse** — reads wave file; extracts groups, creates paths, inter-group dependency map (`groupDeps`), and LRN baseline.
   - **Todos Redteam** — annotates todos with `SI:` fields and `Reuses: C-NNN` before
     implementation; flags new component candidates for registration.
   - **Implement** — tier-based parallel execution: groups with no inter-group deps run
     concurrently; dependent groups wait for their tier's completion. Todos within each
     group also run in parallel. Test-first, SI-enforcing.
   - **Unit Redteam** — zero-tolerance per group (debug fires after >3 failed rounds (r4+) and on stall).
   - **Phase Redteam** — zero-tolerance full wave (debug fires after >3 failed rounds (r4+) and on stall).
   - **Protocol Audit** — `a2a-advisor`, `mcp-advisor`, `ag-ui-advisor`, `a2ui-advisor` + seam check (protocol surfaces only).
   - **Codify** — SDK issue scan (sequential) → parallel LRN capture for critical/high
     findings → README index update → sequential C-NNN registration for new component
     candidates.
   - **Archive** — wave file moved to `completed/`; `plan.md` and FR `Implementation:`
     fields updated.
3. After the workflow returns, log progress:
   - ✅ archived → continue to the next wave automatically.
   - ⚠️ deferred items remain → continue (items are in `deferred/`; re-run after fixing).
   - 🔴 protocol-blocked → stop and report. Fix protocol findings, run `/agent-verify`,
     then `/wave w<NNN>` to resume that wave.
   - If `sdkCandidates > 0`, log: "SDK candidates: N written to `workspace/sdk-candidates.md`" and "Run /sdk-issue-scan to file them as GitHub issues on wailuen/a2a-sdk".
4. After all waves complete, print final summary: waves archived, total LRNs, C-NNN
   entries added, SDK candidates total, any remaining deferrals.

---

## Mode B — Single wave (`/wave w<NNN>`)

Execute one specific wave. Used for:
- Resuming after a 🔴 protocol block once fixes are applied.
- Running a manually created or edited wave file.
- Jumping ahead when dependencies are already satisfied.

Steps:
1. Resolve `workspace/todos/active/w<NNN>-*.md`.
2. **Hard stop** if any `Depends:` item is not in `completed/` — report which dep is missing.
3. Launch `wave-cycle.js` as in Mode A step 2.
4. Display the wave summary and suggest next step: `/wave` (continue next wave) or `/wave status`.

---

## Mode C — Status (`/wave status`)

1. Read `workspace/todos/plan.md`.
2. List all files under `active/`, `completed/`, `deferred/`.
3. Report per-wave: checkbox state, ✅ archived date, deferred reason if applicable.

---

## SDK Security Invariants — checked inside the Workflow (fail-closed)

| ID | Invariant | Severity |
|----|-----------|----------|
| SI-1 | No raw HTTP in `src/tools/` | Critical |
| SI-2 | Exception text never leaks credentials/tokens/inputs | Critical |
| SI-3 | URL path variables through `url_segment()`/`safe_id()` | High |
| SI-4 | Credentials via `self.credential()` only | High |
| SI-5 | All endpoints require auth | Critical |
| SI-6 | Upstream vendor keys in credential store only | Critical |
| SI-7 | Every adapter has non-empty `allowed_hosts` | High |

## Integration

- **`/analyze`** generates the PRD that `/wave` reads in the planning step.
- **`/todos`** is the standalone "plan-only" path — identical planning + redteam
  logic, but no execution. Use it when you want to review or edit the plan before
  running `/wave`.
- **`/implement`** runs all waves autonomously via model-driven `Agent` calls
  (trades Workflow-visible fan-out for fully-unattended end-to-end execution).
- **`/redteam`** can be run standalone at any point between waves.
