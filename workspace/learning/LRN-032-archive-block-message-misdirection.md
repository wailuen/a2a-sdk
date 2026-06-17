---
id: LRN-032
title: Archive-blocked log message must distinguish test failure from protocol block
category: ops
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
`.claude/workflows/wave-cycle.js` emits a single unconditional "blocked by critical protocol findings" message whenever archive is skipped, even when the actual block was a failing test suite. The template variant (`template/.claude/workflows/wave-cycle.js`) carries the RT-003 fix with a `testsBlockedArchive` flag and two differentiated log messages; the SDK-context copy was never updated to match.

## Root cause
The SDK-context copy of `wave-cycle.js` diverged from the template after the RT-003 fix was applied to the template only. No sync step enforced parity, so the misleading single-message path remained in the shipped file.

## Check
```
grep -n "testsBlockedArchive" .claude/workflows/wave-cycle.js
# must return at least one hit; zero hits means the fix is absent
grep -n "blocked by critical protocol" .claude/workflows/wave-cycle.js
# should be inside an else branch, not unconditional
```

## Prevention
When a bug-fix is applied to `template/.claude/workflows/wave-cycle.js`, the planner MUST include a paired task to apply the identical change to `.claude/workflows/wave-cycle.js` in the same wave before archiving.
