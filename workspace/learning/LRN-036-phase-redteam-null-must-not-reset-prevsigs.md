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
  harness/workflows/wave-cycle.js \
  template/.claude/workflows/wave-cycle.js
# Must return 0 lines inside null-response blocks after fix.
# (Legitimate initialisation at top of loop is at a different line number.)
```

## Prevention
Any null-response handler in a redteam loop must not touch `prevSigs`. Add the same comment block carried by the unit loop. Planner must gate phase-loop changes on a grep confirming `prevSigs = new Set()` does not appear inside null-response branches.
