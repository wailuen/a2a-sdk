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
grep -n "fix:tests:unit\|fix:tests:phase" template/.claude/workflows/wave-cycle.js | \
  awk -F: '{print $2}' | while read ln; do
    awk "NR>$ln && NR<=$((ln+20))" template/.claude/workflows/wave-cycle.js | \
      grep -q "recheck" || echo "MISSING re-gate after line $ln"
  done
```

## Prevention
After every `fix:tests:*` agent dispatch, immediately enqueue a re-gate agent (`*:recheck`). If re-gate result is null or RED, write a deferred note and break the inner loop — never advance the wave on an unconfirmed fix. Mirror harness lines 566–585 (unit) and 694–706 (phase).
