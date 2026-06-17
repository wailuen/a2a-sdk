---
id: LRN-037
title: Protocol test-fix path missing re-gate before recheck
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
The protocol audit phase in wave-cycle.js dispatches a `fix:tests:proto:fix` agent when `protoFixGate.exitCode != 0`, then immediately proceeds to the protocol recheck without verifying the fix succeeded. Unit and phase redteam loops each have a formal re-gate agent (`unitReGate`/`phaseReGate`) whose GATE_SCHEMA response is checked before continuing. The proto path has no equivalent guard, so a failed test-fix silently advances to recheck and potentially to archive.

## Root cause
The protocol audit branch was added without mirroring the re-gate pattern that unit/phase loops require. All test-fix paths must independently verify tests are green before proceeding.

## Check
```
grep -n "fix:tests:proto:fix\|gate:proto:fix:recheck\|protocolBlocked" \
  harness/workflows/wave-cycle.js \
  template/.claude/workflows/wave-cycle.js
```
The `gate:proto:fix:recheck` label must appear after `fix:tests:proto:fix` and before the parallel advisor tasks.

## Prevention
Planner constraint: every `fix:tests:*` agent dispatch must be immediately followed by a re-gate agent call using GATE_SCHEMA; a null or failing re-gate must set a `*Blocked` flag and skip downstream steps. Apply to both `harness/workflows/wave-cycle.js` and `template/.claude/workflows/wave-cycle.js`.
