---
id: LRN-020
title: Null redteam response treated as clean pass in unit loop
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js`, the unit redteam loop used `if (!rt || rt.findingsCount === 0) { break }` to exit the loop. When the redteam agent crashes or returns null, this condition is true and the loop breaks — incorrectly declaring the group clean. A crashed reviewer is an unknown state, not a pass.

## Root cause
The null check and zero-findings check were collapsed into a single OR condition. Null (agent failure) and zero findings (genuine clean) require different handling: null must continue (retrying up to a round-budget cap) so debug can engage, while zero blocking findings should break.

## Check
```bash
grep -n '!rt || rt.findingsCount === 0' .claude/workflows/wave-cycle.js harness/workflows/wave-cycle.js
test -d template/ && grep -n '!rt || rt.findingsCount === 0' template/.claude/workflows/wave-cycle.js
```
Any match is a bug. Correct pattern (as landed in `harness/workflows/wave-cycle.js`'s unit redteam loop) splits into separate branches:
```
if (!rt) {
  log('WARNING: ... returned null ... — treating as unknown (not clean)')
  if (uRound >= 5) {                    // round-budget cap
    // write deferred note; protocolBlocked = true; redteamUnknownBlocked = true
    break
  }
  // Do NOT reset prevSigs — see LRN-036 (resetting it defeats stall detection)
  continue
}
...
const blocking = blockingFindings(rt.findings)   // GH-132: critical/high only
if (blocking.length === 0) { break }
```

RT-002 (round-7 fresh-lens debug) — corrects an RT-005/RT-014 rewrite that dropped
the `template/` line on the justification that "`test_workflow_sync.py`'s
harness↔template axis already keeps the two byte-identical whenever it is checked
out". **That justification is false in a checkout without `template/`, which is the
only checkout where it was load-bearing.** `HARNESS_TEMPLATE_SHARED` is built from
`TEMPLATE_DIR.glob("*.js")` and is EMPTY when `template/` is absent, so
`test_harness_and_template_copies_are_identical` is parametrized over **zero cases**
and the two presence guards are `xfail(strict=True)` — never a failure. Delegating a
Check to that axis converts it into a permanent silent pass.

The `template/` copy is also currently KNOWN divergent (see
`workspace/todos/deferred/w039-group-G-budget-exhausted.md` RT-001) — and it is the
copy a downstream agent's `/wave` actually executes.

So the template path is restored, guarded INLINE on the same line per LRN-054 (a
guard on its own line is still flagged as a dead-path guard) — a live check where
the peer repo exists, a documented no-op where it does not.

## Prevention
When authoring redteam loop termination logic, null responses must never share a branch with zero-findings responses, must never reset `prevSigs` (LRN-036), and must never continue past their own round-budget cap. The clean-exit condition is `blockingFindings(rt.findings).length === 0` (GH-132 severity floor), not raw `rt.findingsCount === 0`. Planner must verify template and harness wave-cycle.js stay in sync on this guard whenever either file is modified.
