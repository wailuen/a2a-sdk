---
id: LRN-059
title: Wave scope derived from Creates-only silently bypasses review for modify-only waves
category: sdk
severity: critical
source: redteam
date: 2026-06-18
---

## What happened
`sdk-wave.js` built every scope set — the empty-scope guard, unit/phase redteam scope, protocol-surface detection, and audit file filters — from `Creates:` paths only (`allCreates` / `group.creates`). Wave w020 was a modify-only wave (0 Creates:, 6 Modifies:), so `allCreates` was empty and the guard false-aborted the wave as a harness bug. A modify-only wave that slipped past the guard would have landed with empty adversarial-review scope and no protocol audit.

## Root cause
The wave-parse prompt captured only `Creates:` paths; `Modifies:` paths were never collected, making the entire surface of an edit-only wave invisible to all downstream scope consumers.

## Check
```bash
grep -nE 'allCreates|group\.creates' \
  .claude/workflows/sdk-wave.js \
  .claude/workflows/wave-cycle.js \
  harness/workflows/wave-cycle.js
```
Every hit must use `allScope` / `group.scope` (= Creates ∪ Modifies) instead, except the schema definition and the derivation block itself.

## Prevention
When planning any wave-runner change, ensure wave scope (empty-scope guard, redteam scope, protocol-surface detection, audit filters) derives from `Creates:` ∪ `Modifies:` (`allScope` / `group.scope`). The empty-scope guard must fire only when BOTH sets are empty. Never derive scope from `Creates:` alone.
