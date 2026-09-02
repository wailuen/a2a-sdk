---
id: LRN-136
title: Phase Redteam duplicates Unit Redteam on single-group waves — skip when groups.length === 1
category: harness
severity: medium
source: manual
date: 2026-09-02
---

## What happened
Waves kept getting slower and dispatching more subagents. On a single-group wave
(e.g. w040: one todo, group A) wave-cycle.js ran Unit Redteam on `group.scope` to a
zero-tolerance clean exit, then immediately ran Phase Redteam on `wave.allScope` — the
same file list — with the same 8-dimension checklist, the same debug escalation, and the
same fix → gate → re-gate machinery, for up to 8 more rounds. Worst case (1 finding per
round, budgets hit) that is ~28 extra `agent()` calls that can find nothing new.

## Root cause
Phase Redteam exists to catch cross-group integration (groups are partitioned by
non-conflicting file scope, so only a whole-wave pass sees group A change a signature
group B's reviewed code calls). With one group `allScope == group.scope` and that surface
does not exist, but the phase ran unconditionally. Same defect in sdk-wave.js.

## Check
```bash
grep -n "if (wave.groups.length === 1)" harness/workflows/wave-cycle.js .claude/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js .claude/workflows/sdk-wave.js
```
Each file must show the guard immediately before the Phase Redteam `while (true)` loop,
and `diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js` must
be empty (LRN-075).

## Prevention
A review phase whose scope is derived from a union must be skipped (with a logged reason)
when the union collapses to a scope an earlier phase already cleared with the same
checklist. Never remove Phase Redteam for multi-group waves, never lower the 5/8 round
budgets, and never make the round-4+/stall debug escalation conditional (LRN-076) or fold
the pytest gate into a fix agent (LRN-017) as part of any speed fix.
