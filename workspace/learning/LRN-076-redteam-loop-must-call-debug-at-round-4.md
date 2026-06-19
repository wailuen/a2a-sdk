---
id: LRN-076
title: Wave redteam fix loop must invoke debug agent unconditionally at round 4+ — not only on stall
category: sdk
severity: high
source: manual
date: 2026-06-19
---

## What happened
Wave w020 ran 8 phase-redteam rounds using only the redteam+implementer pair,
exhausted the round budget (`exhausted: true`), left todos unimplemented, and
never invoked the debug agent. The debug trigger was either absent or only
wired to the stall condition, not to the round-count threshold.

## Root cause
sdk-wave.js / wave-cycle.js has a debug-on-stall trigger but the unconditional
round-count trigger (fire debug at uRound > 3 for unit, pRound > 3 for phase)
was either not implemented or bypassed. Without the unconditional trigger, the
loop can spin through all available rounds with the same implementer strategy,
never getting a fresh diagnostic perspective.

## Check
```bash
grep -n 'debug\|uRound\|pRound' .claude/workflows/sdk-wave.js | grep -i 'round\|stall\|debug'
grep -n 'debug\|uRound\|pRound' harness/workflows/wave-cycle.js | grep -i 'round\|stall\|debug'
```
Both files must show debug dispatched unconditionally when round > 3 (not only when stall is detected).

## Prevention
When modifying or reviewing sdk-wave.js / wave-cycle.js: unit redteam loop MUST
call the `debug` agent when `uRound > 3` (unconditional, not just stall-triggered);
phase redteam loop MUST call `debug` when `pRound > 3`. Both are hard thresholds.
The debug agent provides a fresh-lens root-cause view that the implementer loop
cannot produce by repeating the same strategy.
