---
id: LRN-036
title: Phase redteam null-response must not reset prevSigs
category: testing
severity: high
source: redteam
date: 2026-06-17
---

## What happened
The phase redteam null-response handler in `harness/workflows/wave-cycle.js` (line 657) and `template/.claude/workflows/wave-cycle.js` (line 656) resets `prevSigs = new Set()` on a null round. The unit redteam null handler (lines 482-485) explicitly preserves `prevSigs` with a comment explaining why — resetting it allows a subsequent round that returns the exact same findings as the last real round to evade stall detection, because `sigsEqual(currentSigs, prevSigs)` compares against an empty set instead of the real prior set.

## Root cause
The phase loop was written without carrying over the invariant established in the unit loop: `prevSigs` must always hold the last real finding set, not be cleared on null rounds. The omission was silent — no comment flagged the constraint.

## Check
```
grep -n "prevSigs = new Set" \
  .claude/workflows/wave-cycle.js \
  harness/workflows/wave-cycle.js
# Must return 0 lines inside null-response blocks after fix.
# (Legitimate initialisation at top of loop is at a different line number.)
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
Any null-response handler in a redteam loop must not touch `prevSigs`. Add the same comment block carried by the unit loop. Planner must gate phase-loop changes on a grep confirming `prevSigs = new Set()` does not appear inside null-response branches.
