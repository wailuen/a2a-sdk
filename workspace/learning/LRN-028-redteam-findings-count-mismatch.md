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
grep -n 'rt.findingsCount !== rt.findings.length' \
  .claude/workflows/wave-cycle.js \
  harness/workflows/wave-cycle.js
# Must return 4 matches total — 2 per file (one Unit Redteam gate, one Phase
# Redteam gate).
```

RT-016 replaced the original two-special-case guard this learning was written
against (`findingsCount === 0 && findings.length > 0`; the mirror-image
`findingsCount > 0 && findings.length === 0`) with the single inequality
`rt.findingsCount !== rt.findings.length`, which also catches the partial
mismatch (e.g. `findingsCount=5`, `findings=[<1 item>]`) both special cases let
through. The cross-validation invariant this learning codifies still holds —
only its spelling in code changed — so the Check now pins the current
spelling instead of the one RT-016 deleted.

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
Any redteam-loop cross-validation invariant must stay mirrored across `.claude/workflows/wave-cycle.js` and `harness/workflows/wave-cycle.js` in the same commit. Planner must reject a wave-cycle.js change where `grep -c 'rt.findingsCount !== rt.findings.length' .claude/workflows/wave-cycle.js harness/workflows/wave-cycle.js` returns fewer than 2 per file. Always cross-validate `findingsCount` against `findings.length` before trusting a clean-pass signal from any agent. LRN-133: a wave that rewrites an invariant's spelling in code must repoint every LRN Check that pins the old spelling in the same change — a Check grepping a pattern the wave just deleted is a permanently-passing guard.
