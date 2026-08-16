---
id: LRN-030
title: Null redteam response silently treated as clean pass
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js`, the unit-redteam loop and phase-redteam loop used `if (!rt || rt.findingsCount === 0) { break }` to exit the fix loop. A null agent response and a genuine zero-findings result were collapsed into the same branch, so a failed or non-responsive redteam agent was silently treated as a clean pass. This allowed archive to proceed on code that was never inspected.

## Root cause
Null-check and clean-detection were merged into one condition. A null response should continue the loop without resetting `prevSigs` (engage debug); a zero-findings response should break. Conflating them violated RT-004 (fail-safe redteam).

## Check
```
grep -n 'if (!rt || rt.findingsCount' harness/workflows/wave-cycle.js
```
Must return no matches. Correct pattern (as landed in `harness/workflows/wave-cycle.js`'s unit and phase redteam loops) uses separate guards, with a round-budget deferral on the null branch and the GH-132 severity floor on the clean-exit branch:
```
if (!rt) {
  log('WARNING: ... returned null ... — treating as unknown (not clean)')
  if (uRound >= budgetCap) {           // 5 for unit, 8 for phase
    // write deferred note; protocolBlocked = true; redteamUnknownBlocked = true
    break
  }
  // Do NOT reset prevSigs — preserve the last real finding set so stall
  // detection stays valid across null rounds. See LRN-036.
  continue
}
...
const blocking = blockingFindings(rt.findings)   // GH-132: critical/high only
if (blocking.length === 0) { break }
```

RT-002 (round-7 fresh-lens debug) — corrects an RT-005/RT-014 rewrite that dropped
the `template/` copy from this Check on the justification that
"`test_workflow_sync.py`'s harness↔template axis already keeps the two byte-identical
whenever it is checked out". **That justification is false in exactly the checkout
where it was load-bearing.** `HARNESS_TEMPLATE_SHARED` is built from
`TEMPLATE_DIR.glob("*.js")` and is EMPTY when `template/` is absent, so
`test_harness_and_template_copies_are_identical` is parametrized over **zero cases**,
and the two presence guards are `xfail(strict=True)` — never a failure. Delegating a
Check's coverage to that axis turns the Check into a permanent silent pass. The
`template/` copy is also currently KNOWN divergent (deferred RT-001 in
`workspace/todos/deferred/w039-group-G-budget-exhausted.md`) — and it is the copy a
downstream agent's `/wave` actually runs.

So also run this Check's grep against the template copy, guarded INLINE on the same
line per LRN-054 (a guard on its own line is still flagged as a dead-path guard):

```bash
test -d template/ && grep -n '<this Check's pattern>' template/.claude/workflows/wave-cycle.js
```

It is a live check where the peer repo is checked out and a documented no-op where it
is not — never a silent removal.

## Prevention
When authoring or reviewing redteam loop logic: null response MUST `continue` (never `break`) until its own round-budget cap is exhausted, and MUST NOT reset `prevSigs` on the way (see LRN-036 — resetting it defeats stall detection). The loop's clean-exit condition is `blockingFindings(rt.findings).length === 0` (GH-132 severity floor: only critical/high findings block), not raw `rt.findingsCount === 0`. Any condition that joins null with zero-findings is a fail-open bug. Planner must add an explicit review step for this pattern whenever wave-cycle loop logic is modified.
