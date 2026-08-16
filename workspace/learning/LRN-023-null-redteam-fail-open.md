---
id: LRN-023
title: Null redteam response treated as clean (fail-open)
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js`, the condition `if (!rt || rt.findingsCount === 0) { break }` conflated a null agent response with zero findings. When the redteam agent crashed or returned null, the fix loop broke and marked the group clean — silently passing every group whose redteam agent failed. The same fail-open pattern existed at the phase-redteam null check.

## Root cause
A single guard merged two semantically distinct outcomes (unknown/error vs. confirmed-clean), causing null — an unknown state — to be handled identically to a zero-findings result.

## Check
```
grep -n '!rt || rt\.findingsCount' harness/workflows/wave-cycle.js
```
Must return zero matches. Each call site (unit and phase redteam loops, as landed in `harness/workflows/wave-cycle.js`) has separate branches:
```
if (!rt) {
  log('WARNING: ... returned null ... — treating as unknown (not clean)')
  if (round >= budgetCap) {             // 5 for unit, 8 for phase
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
When writing or reviewing redteam loop guards: null response MUST continue (retry, up to a round-budget cap), never break early, and MUST NOT reset `prevSigs` (LRN-036). The only condition that may break the fix loop as clean is `blockingFindings(rt.findings).length === 0` (GH-132 severity floor) — never raw `rt.findingsCount === 0`. Never merge the null guard and the zero-findings guard into a single `||` condition.
