---
id: LRN-065
title: Runtime and template workflow copies diverge silently
category: ops
severity: high
source: redteam
date: 2026-06-15
---

## What happened
The runtime copy `.claude/workflows/wave-cycle.js` and the template/distribution copy `harness/workflows/wave-cycle.js` accumulated ~10 behavioral differences over time: the harness copy was ahead on null-gate hardening and deferred notes, while the runtime copy was ahead on archive plan.md row-append handling. Each copy had fixes the other lacked, meaning deployed agents seeded from the harness were missing runtime fixes and vice versa.

## Root cause
There is no automated sync-check asserting the two copies are identical, so divergence accumulates silently whenever a fix is applied to one copy but not the other.

## Check
Run `diff .claude/workflows/wave-cycle.js harness/workflows/wave-cycle.js` and confirm the output is empty or limited to the intentional description/manifest line. Add this as a CI assertion so it fails the build on divergence.

## Prevention
When planning any change to `.claude/workflows/` or `harness/workflows/`, ensure the same change is applied to both copies atomically in the same commit. Add a CI diff-check step that blocks merge if the two copies diverge beyond the allowed manifest line.
