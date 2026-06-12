---
name: debug
category: core
description: "Fresh-lens debug: read code cold, run tests, diagnose root cause from first principles — no anchoring on prior fix attempts. Automatically invoked at redteam round 3+ by the wave-cycle workflow."
---

# /debug — Fresh-Lens Debug

A fresh pair of eyes on a stuck problem. The agent reads code directly, runs
tests, and diagnoses root cause without inheriting prior assumptions. The value
is the **cold read** — prior fix attempts are shown only after the agent has
formed its own hypothesis.

## Usage

```
/debug [scope]
```

- `(no args)` — debug the most recently failing test area
- `src/path/to/file.py` — specific file and its test suite
- `group:A w001` — a specific wave group's scope
- `w001` — full-wave fresh-lens pass across all created files

## When to use

- A redteam fix loop has stalled at 3+ rounds without converging
- Tests pass individually but fail together (cross-unit drift)
- A finding recurs after a fix that "should have worked"
- The implementation appears structurally wrong, not just patchy

## Steps

1. Parse scope from argument (or default to last failing area).
2. Launch a fresh debug agent — **no prior context loaded**:

   **Step 1 — Read cold.**
   Read every file in scope directly. Form an independent understanding of
   what the code does and what its contracts are. Do not reference prior
   findings yet.

   **Step 2 — Run tests; capture raw output.**
   `pytest -q tests/` (or the scope subset). Capture exact failure messages,
   not summaries. If tests are green, check whether they actually assert the
   right things — a vacuously-passing test is a bug, not a pass.

   **Step 3 — Diagnose from first principles.**
   Trace the failure upstream: where does the value *first* go wrong, not
   where it is finally observed? State the root cause in one sentence backed
   by evidence from the code or test output.

   **Step 4 — Cross-check against prior findings.**
   Only now review the prior findings list. If your diagnosis matches:
   confidence up. If it diverges: trust the fresh reading — prior rounds may
   have been chasing a symptom.

   **Step 5 — Fix at the root cause.**
   Change the code where the value first goes wrong. Rewrite fundamentally
   broken implementations rather than patching around them. Surgical changes.

   **Step 6 — Confirm green, report.**
   Re-run tests. Report: root cause (one sentence), files changed, test count
   before and after.

3. If the fix lands: mark resolved. If root cause was non-obvious, codify as LRN.
4. If the fix fails a second debug pass: spawn an independent second agent with
   a different hypothesis — no two debug agents share context.

## Principles

- **Cold read first, prior context last.**
- **Fix the cause, not the symptom.**
- **Rewrite > patch.** If the implementation is wrong structurally, patching
  extends the debt.
- **Never suppress a test to make it green.** A silenced assertion is not a fix.

## SDK security during debug

Debug agents still enforce SI-1…SI-7. Do not widen test fixtures to bypass
auth or credential resolution — mock the resolution layer correctly, not absent.

## Integration

- **wave-cycle.js** — invokes automatically at unit redteam round 3+ and phase
  redteam round 3+; label prefix `debug:unit:` / `debug:phase:`
- **`/redteam`** — invoke standalone if critical findings persist across 2 passes
- **`/codify`** — call after every non-obvious root cause
