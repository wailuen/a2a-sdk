---
id: LRN-151
title: Quality-gate exit-condition change left SKILL.md docs frozen at old contract
category: protocol
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-132 moved unit/phase redteam loops from exit-on-zero-findings to exit-on-zero-critical/high, but 5 SKILL.md files (wave x2, implement, setup, wave-cycle desc) still say "zero-tolerance" — no mention of the severity floor, deferred medium/low, debug-replaces-fan-out, or AGENT_CALL_BUDGET.

## Root cause
The loop-semantics fix touched only workflow logic, not the companion docs — LRN-086's pattern, now for loop contracts, not wire formats.

## Check
```bash
grep -rln 'zero-tolerance' .claude/skills/wave/SKILL.md harness/skills/{wave,implement,setup}/SKILL.md \
  | xargs grep -L 'critical/high'
```
Must return no files.

## Prevention
A quality-gate exit-condition change must update every SKILL.md advertising that gate's contract, same commit — LRN-086 covers loop semantics too, not just wire formats.
