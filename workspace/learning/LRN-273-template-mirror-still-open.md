---
id: LRN-273
title: Template mirror gap persists across redteam rounds
category: ops
severity: high
source: redteam
date: 2026-10-09
---

## What happened
In a later GH-152-E round, `git -C template status --short` still showed .claude/workflows/wave-cycle.js and .claude/skills/setup/SKILL.md modified, with template HEAD at ce6dbb5. This was the earlier budget-exhausted finding (see LRN-271), never closed and with no closing note naming the files.

## Root cause
A finding that runs out of fix budget was dropped silently instead of being recorded as an open deliverable.

## Check
Run `git -C template status --short` and `diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js`. Confirm clean output, or confirm the wave closing note (w042) lists the files as unpropagated.

## Prevention
When planning waves, treat a budget-exhausted or deferred mirror finding as a carried-forward deliverable. The closing note must name each unpropagated file and the diff command that proves the gap.
