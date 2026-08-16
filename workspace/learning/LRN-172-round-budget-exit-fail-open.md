---
id: LRN-172
title: Round-budget loop exits skip archive-blocking flags (fail-open)
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
In `.claude/workflows/wave-cycle.js`, four round-budget exits from the zero-tolerance redteam loops (null-response at unit :849-857/phase :1095-1102, and the newly added RT-016 findingsCount/findings-mismatch budget exits at unit :877-886/phase :1122-1130) write a deferred note but set none of `unitBudgetBlocked`, `phaseBudgetBlocked`, `protocolBlocked`, or `testsRed`. A redteam agent returning null or a mismatched findingsCount on every round therefore lets the wave reach Protocol Audit and Archive as if verdict were clean, despite the RT-016 exit's own comment claiming it "fails closed exactly like a null response."

## Root cause
The null-GATE exit path (:1000, :1241) sets `testsRed`, but the round-budget exits from the unit/phase redteam loops were never wired to any blocking flag — an UNKNOWN verdict (null or mismatched) was not treated as at least as blocking as a findings-present verdict.

## Check
```
grep -n "budgetCap\|BUDGET" .claude/workflows/wave-cycle.js harness/workflows/wave-cycle.js .claude/workflows/sdk-wave.js
```
For each round-budget exit block found, confirm it sets `protocolBlocked = true` and a dedicated `redteamUnknownBlocked` flag before `break`. Add `test_workflows.py` cases asserting each null-budget and mismatch-budget exit sets a blocking flag.

## Prevention
When planning changes to redteam loop exit paths, require every exit reached because the verdict is UNKNOWN (null, malformed, or findingsCount/findings mismatch) to set `protocolBlocked` plus its own `redteamUnknownBlocked` flag (distinct message per LRN-032) — never rely on an adjacent comment's "fails closed" claim without a flag-setting grep/test proving it.
