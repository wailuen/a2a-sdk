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
  .claude/workflows/wave-cycle.js \
  harness/workflows/wave-cycle.js
```
The `gate:proto:fix:recheck` label must appear after `fix:tests:proto:fix` and before the parallel advisor tasks.

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
Planner constraint: every `fix:tests:*` agent dispatch must be immediately followed by a re-gate agent call using GATE_SCHEMA; a null or failing re-gate must set a `*Blocked` flag and skip downstream steps. Apply to both `harness/workflows/wave-cycle.js` and `template/.claude/workflows/wave-cycle.js`.
