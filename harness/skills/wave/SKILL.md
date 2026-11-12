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
   under `workspace/todos/active/`. **Planner instruction: maximize parallel execution.**
   Assign todos with no file conflict (non-overlapping `Creates:` paths and no
   cross-todo `Depends:`) to the same `‖ group:` label so `wave-cycle.js` runs them
   concurrently. Only separate into distinct groups when a `Depends:` chain exists
   between them. Prefer one tier of many parallel todos over many sequential tiers.
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
2. **Launch `wave-cycle.js`**:
   ```js
   Workflow({
     scriptPath: ".claude/workflows/wave-cycle.js",
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
   - **Parse** — reads wave file; extracts groups, creates paths, inter-group dependency map (`groupDeps`), and LRN baseline.
   - **Todos Redteam** — annotates todos with `SI:` fields and `Reuses: C-NNN` before
     implementation; flags new component candidates for registration.
   - **Implement** — tier-based parallel execution: groups with no inter-group deps run
     concurrently; dependent groups wait for their tier's completion. Todos within each
     group also run in parallel. Test-first, SI-enforcing.
   - **Unit Redteam** — per-group fix loop; loop exits when zero critical/high findings
     remain (severity floor, GH-132) — medium/low are recorded once to
     `workspace/todos/deferred/<wave>-group-<label>-medium-low.md` and do not block.
     Fix fan-out runs rounds 1–3; at round 4 (the only round above the fix-fan-out
     threshold before the round-5 deferred exit) or on stall, `debug` REPLACES the
     fix fan-out (not alongside it) for that round. Max 5 rounds, then the group is
     deferred.
   - **Phase Redteam** — same severity-floor/debug-replaces-fix-fan-out contract at
     full-wave scope (medium/low → `workspace/todos/deferred/<wave>-phase-medium-low.md`);
     max 8 rounds, then deferred. A hard agent-call ceiling backstops the whole wave
     against runaway loops: `150` for the handful of Parse-phase calls, then recomputed
     once the group count is known to `max(150, 45 × groups + 80)` (e.g. 260 for a
     4-group wave) so the ceiling scales with the wave's own shape. `args.agentBudget`
     in the `Workflow(...)` args (see step 2 above) is an explicit override that always
     wins over both.
   - **Protocol Audit** — `a2a-advisor`, `mcp-advisor`, `ag-ui-advisor`, `a2ui-advisor` + seam
     check (triggered only for touched protocol surfaces in `src/routes/`).
   - **Codify** — SDK issue scan (sequential) → parallel LRN capture for critical/high
     findings → README index update → sequential C-NNN registration for new component
     candidates.
   - **Archive** — pre-archive pytest gate → commit-intent check (uncommitted scope
     files, harness deliverable dirs, or undeclared mid-wave imports block archive) →
     wave file moved to `completed/`; `plan.md` and FR `Implementation:` fields updated.
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

**`[x]` vs `[~]` on a re-run (GH-278).** `[x]` means the todo is done: its work already landed, so
the runner never dispatches it again (repeating pushes or live runs is the harm this prevents), but
its `Creates:`/`Modifies:` paths stay in the wave scope and the archive gates still check them.
`[~]` means the todo cannot land in this repo: it is skipped and its paths leave the scope.
Never use `[~]` to mean "already done" (the scope empties and the run aborts with `empty-scope`).
- All todos `[x]` (or `[~]`, with at least one `[x]`): the run resumes at archive. It skips plan
  review, implement, redteam, protocol audit and codify, and runs only the pre-archive gate, the
  archive-commit gate and the archive. Pass `resumeAt: "archive"` in the workflow args to force
  this even with open `[ ]` todos (`resumeAt: null` counts as absent); any other `resumeAt` value
  is rejected before any agent runs.
- **The resume fails closed.** Because it skips review, it checks two things first (by script,
  not by a model) and skips the archive with a logged reason if either fails. (1) Every blocking
  note in `workspace/todos/deferred/<waveId>-*` must be resolved: `-budget-exhausted.md`,
  `-rt-null-budget.md`, `-rt-mismatch-budget.md`, `-tests-red-*.md`, `-proto-tests-red.md` and `-gate-null-*.md`. A note counts as resolved
  only when one of its lines starts with `Resolved:` (or `Resolved <date>:`) followed by text,
  written after you fixed and verified the findings. `-medium-low.md` notes never block. (2) The
  same `Creates:` deliverable gate the normal path runs for done groups (`deliv:resume`) must
  pass. The result carries `resumeBlocked` and `resumeBlockedNotes`; an unreadable note check
  counts as blocked.
- Some todos `[x]`, some `[ ]`: only the `[ ]` todos are dispatched. A group whose todos are all
  `[x]` dispatches nothing but still passes the deliverable gate (a pattern `Creates:` path passes
  when any matching file exists), and groups that depend on it run in the next tier. A mixed group
  keeps the normal fresh-file gate for all its `Creates:` paths, so keep a `[x]` todo that owns a
  pattern `Creates:` path in its own group.
- A todo carrying an unreleased `HUMAN GATE:` marker still blocks the archive on every path.
- Only the implementer ticks `[x]` (see `/implement`); do not tick a todo whose work has not landed.

**The wave file is frozen during a run (GH-279).** The runner takes a fingerprint of the wave
file at the first preflight (or the replan preflight when plan review edited it). The fingerprint
covers each todo's id, its `‖ group:` label, its `Depends:` lines, whether it is `[~]` and whether
an unreleased `HUMAN GATE:` holds it (so adding a gate, or releasing one, mid-run stops the run).
It is checked before every tier and right before the pre-archive gate, with no agent between that
check and the gate. Do not add todos or change those
fields while a run is going. Exempt: plan-review fixes (made before the fingerprint is taken),
`[ ]` to `[x]` ticks by the implementer, `Creates:`/`Modifies:` paths adopted by the scope re-scan,
and the runner's own archive step.
- `wave-file-changed`: the fingerprint no longer matches. No further agent runs. Finish the edit,
  then re-run `/wave <id>`; the new run takes a fresh fingerprint (`[x]` todos are not repeated).
- `freeze-check-failed`: the fingerprint could not be read (the check agent failed or returned a
  malformed result). Unknown is treated as changed, so the run stops. Re-run `/wave <id>`.
- `dangling-depends`: a todo still to run lists an id in `Depends:` that is not in the file or is
  marked `[~]`. Write ids in backticks (`` `GH-12` ``, `` `P1b` ``). Bare ids with a hyphen and a
  digit (`P0-01`) are checked too; bare words without a hyphen (`W4`) are read as prose. A `Depends:`
  text that names another wave (`W0`, `w070`: "`P0-04` (W0 complete)") refers to todos outside this
  file, so its bare ids are not checked. Fix the
  `Depends:` line. A dependency on an `[x]` todo counts as met.

Steps:
1. Resolve `workspace/todos/active/w<NNN>-*.md`.
2. **Hard stop** if any `Depends:` item is not in `completed/` — report which dep is missing.
3. **Launch `wave-cycle.js`** — same invocation shape as Mode A step 2:
   ```js
   Workflow({
     scriptPath: ".claude/workflows/wave-cycle.js",
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

## HUMAN GATE marker

A todo that needs a human decision before it runs carries an explicit marker line
`- HUMAN GATE: <reason>`. The wave runner holds that todo's group (it is not
dispatched, its dependents are pruned, and archive is blocked) until the todo also has
a release line `- Release: https://github.com/<org>/<repo>/issues/<n>` citing the
GitHub issue that records the approval. Record the approval in the issue first, then
add the line. Free text such as `Status: NOT DONE` does not gate.
