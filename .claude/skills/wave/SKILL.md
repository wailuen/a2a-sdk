---
name: wave
category: core
description: "Primary development entry point after /analyze. Without a wave ID: reads PRD → plans ALL waves (planner agent + auto-redteam loop) → confirms → executes each in sequence via wave-cycle.js (todos-redteam → implement → unit/phase redteam → protocol audit → codify + C-NNN registration → archive). With a wave ID: execute that specific wave only (resumption). status: progress dashboard."
---

# /wave — Plan and Execute

The primary development command after `/analyze`. Without a wave ID it reads
the PRD, plans all waves, redteams the plan, and executes each wave in sequence.
Each wave runs a full 8-phase cycle — including a Todos Redteam pass before
any implementation, fix loops gated on a critical/high severity floor
(medium/low are recorded, not blocking), and auto-codify at the end.

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
   under `workspace/todos/active/`.
7. **Auto-redteam loop until zero critiques (all severities):**
   - Run `redteam` scoped to the plan files.
   - If findings: rounds 1–3, invoke `planner` to fix; from round 4 on, invoke
     `debug` instead for a fresh-lens root-cause fix of the plan. Re-redteam after
     every fix. The plan passes only at zero findings.
   - If round 8 still has findings, stop and show the user the open findings —
     do not start execution on a plan with open findings.
   - Codify any novel learnings surfaced in this plan-review pass.
8. Show plan summary: wave count, scopes, SI-flagged todos, registry reuses, dep order.
9. **Confirm with user**: "N waves planned. Proceed? [y/n]"

### Execution step — per wave in plan order

For each wave whose `Depends:` items are all in `completed/`:

1. **Check deps** — if any `Depends:` item is still in `active/` or `deferred/`,
   stop and report which dep is blocking.
2. **Launch `sdk-wave.js`** (the SDK-context executor):
   ```js
   Workflow({
     scriptPath: ".claude/workflows/sdk-wave.js",
     args: { waveFile: "<absolute path to active wave file>", today: "<YYYY-MM-DD>" }
   })
   ```
   `args.agentBudget` (optional, default `150`) overrides the hard agent-call
   ceiling described in the Phase Redteam bullet below — e.g.
   `args: { waveFile, today, agentBudget: 300 }`.
   `args.autoFileSdkIssues` (optional boolean, default `false`) turns on auto-filing at
   codify: each SDK candidate is re-checked against the final tree and tagged
   `Status: fixed-in-wave | still-open` in `workspace/sdk-candidates.md`; only `still-open`
   ones are filed on `wailuen/a2a-sdk` (deduped, at most 10, credential-redacted, `-R` on
   every `gh` call, title and body from classified fields only). The issue URL is written
   back to the file. If `gh` is missing or unauthenticated the candidates stay in the file
   and the wave still finishes. Default `false` files nothing; use `/sdk-issue-scan`.

   The workflow runs 8 phases for this wave:
   - **Parse** — reads wave file; extracts groups, creates paths, `groupDeps` map, and LRN baseline.
   - **Todos Redteam** — `redteam` agent annotates todos with `SI:` fields and `Reuses: C-NNN`
     before implementation; flags new component candidates for registration.
   - **Implement** — tier-based parallel execution via `groupDeps`; `python-implementer` agent
     per todo; test-first (RED→GREEN→refactor).
   - **Unit Redteam** — `redteam` per group; loop exits when zero critical/high findings
     remain (severity floor, GH-132) — medium/low are recorded once to
     `workspace/todos/deferred/<wave>-group-<label>-medium-low.md` and do not block.
     `python-implementer` fixes rounds 1–3; at round 4 (the only round above the
     fix-fan-out threshold before the round-5 deferred exit) or on stall, `debug`
     REPLACES the fix fan-out (not alongside it) for that round. Max 5 rounds, then
     the group is deferred.
   - **Phase Redteam** — same severity-floor/debug-replaces-fix-fan-out contract at
     full-wave scope (medium/low → `workspace/todos/deferred/<wave>-phase-medium-low.md`);
     max 8 rounds, then deferred. A hard agent-call ceiling backstops the whole wave
     against runaway loops: `150` for the handful of Parse-phase calls, then recomputed
     once the group count is known to `max(150, 45 × groups + 80)` (e.g. 260 for a
     4-group wave) so the ceiling scales with the wave's own shape. `args.agentBudget`
     in the `Workflow(...)` args (see step 2 above) is an explicit override that always
     wins over both.
   - **Protocol Audit** — `a2a-advisor`, `mcp-advisor`, `ag-ui-advisor`, `a2ui-advisor` + seam
     check (triggered only for touched protocol surfaces in `agent_sdk/routes/`).
   - **Codify** — `codify` agent captures LRNs for critical/high findings; SDK issue scan writes
     `workspace/sdk-candidates.md` for `/sdk-issue-scan`.
   - **Archive** — pre-archive pytest gate → move wave file to `completed/`; update `plan.md`.
     Note: no commit-intent guard (commits happen via `/sdk-release`, not during the wave).
3. After the workflow returns, log progress:
   - ✅ archived → continue to the next wave automatically.
   - ⚠️ deferred items remain → continue (items are in `deferred/`; re-run after fixing).
   - 🔴 protocol-blocked → stop and report. Fix protocol findings, run `/sdk-test`,
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
3. **Launch `sdk-wave.js`** (the SDK-context executor) — same invocation shape as Mode A
   step 2:
   ```js
   Workflow({
     scriptPath: ".claude/workflows/sdk-wave.js",
     args: { waveFile: "<absolute path to the resolved wave file>", today: "<YYYY-MM-DD>" }
   })
   ```
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
| SI-1 | No raw HTTP in `agent_sdk/` tools — all HTTP through `SourceAdapter` | Critical |
| SI-2 | Exception text never leaks credentials/tokens/inputs | Critical |
| SI-3 | URL path variables through `url_segment()`/`safe_id()` | High |
| SI-4 | Credentials via `self.credential()` only | High |
| SI-5 | All endpoints require auth (`require_identity`) | Critical |
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

## HUMAN GATE marker

A todo that needs a human decision before it runs carries an explicit marker line
`- HUMAN GATE: <reason>`. The wave runner holds that todo's group (it is not
dispatched, its dependents are pruned, and archive is blocked) until the todo also has
a release line `- Release: https://github.com/<org>/<repo>/issues/<n>` citing the
GitHub issue that records the approval. Record the approval in the issue first, then
add the line. Free text such as `Status: NOT DONE` does not gate.
