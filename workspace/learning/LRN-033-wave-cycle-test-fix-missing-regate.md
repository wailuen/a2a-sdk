---
id: LRN-033
title: Wave-cycle missing re-gate after test-fix dispatch
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
After a gate RED in unit or phase redteam (wave-cycle.js lines 538–547 and 630–639), the harness dispatches a `fix:tests:unit` or `fix:tests:phase` agent but immediately continues the loop without verifying the fix succeeded. The loop advances to the next round assuming the fix turned the gate green, which it may not have.

## Root cause
No re-gate agent call (`gate:unit:<group>:r<N>:recheck` / `gate:phase:r<N>:recheck`) follows the fix dispatch. LRN-017 RT-002 mandates a re-gate after every test-fix agent; the template omitted this step entirely.

## Check
```
grep -n "fix:tests:unit\|fix:tests:phase" harness/workflows/wave-cycle.js | \
  awk -F: '{print $2}' | while read ln; do
    awk "NR>$ln && NR<=$((ln+20))" harness/workflows/wave-cycle.js | \
      grep -q "recheck" || echo "MISSING re-gate after line $ln"
  done
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
After every `fix:tests:*` agent dispatch, immediately enqueue a re-gate agent (`*:recheck`). If re-gate result is null or RED, write a deferred note and break the inner loop — never advance the wave on an unconfirmed fix. Mirror harness lines 566–585 (unit) and 694–706 (phase).
