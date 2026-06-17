---
id: LRN-026
title: Null proto-fix gate fails open — crashed gate must set protocolBlocked
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` (~line 799) the proto-fix gate check is `if (protoFixGate && protoFixGate.exitCode !== 0)`. When the gate agent crashes and returns null, the condition short-circuits to false, so neither `testsRed` nor `protocolBlocked` is set. The harness handles null in a dedicated branch that sets both flags and emits a warning. The template silently proceeds to recheck dispatch with the suite in an unknown state.

## Root cause
The null guard and the non-zero exit-code guard were collapsed into one condition. A null return (agent crash) is distinct from a passing exit code and must be treated as a blocking failure.

## Check
```
grep -n 'protoFixGate &&' template/.claude/workflows/wave-cycle.js
```
The result must NOT show a single compound condition; it must show a null branch that sets `testsRed=true` and `protocolBlocked=true` separately from the `exitCode !== 0` branch.

## Prevention
When writing gate checks: always handle null (agent crash) as an explicit blocking branch before checking exitCode. Mirror harness lines 877–883: null → `testsRed=true, protocolBlocked=true` + warning log; non-zero exitCode → same flags + error log. Never collapse the two into a single `&&` predicate.
