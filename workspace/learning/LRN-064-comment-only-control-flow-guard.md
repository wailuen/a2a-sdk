---
id: LRN-064
title: Comment claiming guard is not a control-flow guard
category: ops
severity: high
source: redteam
date: 2026-06-18
---

## What happened
In `.claude/workflows/wave-cycle.js` lines 988-993, a comment states "do not proceed to the protocol recheck — jump out of the if-block" after setting `protocolBlocked=true`, but no `if (!protocolBlocked)` wrapper was placed around the recheck dispatch block. Control fell straight through, dispatching all advisor recheck agents even when tests were already red, wasting agent calls and emitting a misleading "protocol-blocked" deferred note instead of a "tests-red" one.

## Root cause
The developer wrote a comment describing the intended guard rather than implementing the guard itself. The canonical copy in `harness/workflows/wave-cycle.js` correctly wraps the recheck with `if (!protocolBlocked) { ... }` (WC-RT-005), but the diverged copy lacked that wrapper.

## Check
Verify that every `protocolBlocked = true` assignment in `.claude/workflows/wave-cycle.js` is followed by a matching `if (!protocolBlocked)` guard around any recheck dispatch:
```
grep -n "protocolBlocked" .claude/workflows/wave-cycle.js
```
Confirm no recheck `TaskCreate` / dispatch call appears outside an `if (!protocolBlocked)` block after any assignment that sets it `true`.

## Prevention
When planning or reviewing harness control-flow, treat every "do not proceed" / "jump out" comment as a red flag — verify the actual `if (!blocked)` wrapper exists in code. Comments do not gate execution; only explicit conditional blocks do. Diff diverged copies against the canonical harness copy at WC-RT-005 before shipping.
