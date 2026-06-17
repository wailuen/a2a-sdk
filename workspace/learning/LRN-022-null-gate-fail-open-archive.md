---
id: LRN-022
title: Null gate response silently permits archive (fail-open)
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` line 1015, the pre-archive gate check uses `if (preArchiveGate && preArchiveGate.exitCode !== 0)`. When the gate agent crashes and returns null, the `&&` short-circuit evaluates to false, skipping the block entirely and allowing archive to proceed with unknown test state. The template also lacks `testsBlockedArchive` tracking, so there is no record that tests were never actually confirmed passing.

## Root cause
A single boolean expression conflates two distinct failure modes — null response (agent crash) and non-zero exit (tests failed) — causing null to be treated as success rather than unknown/blocked.

## Check
```
grep -n "preArchiveGate &&" template/.claude/workflows/wave-cycle.js
```
Must not exist; expect separate null-guard and exit-code branches with `testsBlockedArchive`.

## Prevention
Every gate check must use two separate branches: null → fail closed (set testsRed=true, protocolBlocked=true, testsBlockedArchive=true, skip archive); non-zero exitCode → same flags. Never combine null and failure checks with `&&`.
