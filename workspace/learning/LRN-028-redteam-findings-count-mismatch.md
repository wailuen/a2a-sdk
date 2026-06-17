---
id: LRN-028
title: Redteam findingsCount can contradict findings array, bypassing zero-tolerance gate
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
The wave-cycle template is missing the `findingsCount` cross-validation guard in both the Unit Redteam and Phase Redteam loops. An agent that returns `findingsCount=0` alongside a non-empty `findings` array would pass the zero-tolerance gate silently, hiding real findings. The harness (WC-RT-004) already carries this guard at lines 510–513 and 680–683 but the template was never updated to match.

## Root cause
Template and harness diverged: the harness received the cross-validation fix but the template was not updated atomically, leaving derived agent projects vulnerable to a misreporting agent producing a false-clean signal.

## Check
```
grep -n "findingsCount === 0 && rt.findings.length" \
  template/.claude/workflows/wave-cycle.js
# Must return 2 matches (one Unit, one Phase) after fix is applied.
```

## Prevention
Any guard added to the harness redteam loop must be mirrored to the template in the same commit. Planner must reject a template release where `grep findingsCount template/.claude/workflows/wave-cycle.js` returns fewer than 2 cross-validation blocks. Always cross-validate `findingsCount` against `findings.length` before trusting a clean-pass signal from any agent.
