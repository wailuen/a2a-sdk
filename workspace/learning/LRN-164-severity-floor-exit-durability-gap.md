---
id: LRN-164
title: Round-cap exit drops severity-floor findings without deferred note
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
Phase redteam's round-cap exit (`pRound >= 8 { log(...); break }`) breaks
with a bare log: no deferred note, precedes `allHighFindings.push(...)`,
sets neither `protocolBlocked` nor `testsRed`, so the wave archives.
Medium/low gets a durable deferred note on exit; critical/high — the only
severity survivable at round 8 post-GH-132 — gets none.

## Root cause
GH-132 narrowed round-8 survivors to a severity floor without re-deriving
the exit's durability; it still behaves as if dropping a low nit.

## Check
`grep -n "pRound >= 8" .claude/workflows/wave-cycle.js harness/workflows/wave-cycle.js .claude/workflows/sdk-wave.js`
— each hit must write a deferred note under `workspace/todos/deferred/`
and set a blocking flag before `break`.

## Prevention
When narrowing a loop-exit condition to a severity floor, re-audit every
surviving exit path for the durability (defer, codify, archive block) the
pre-narrowing path had — a write-nothing exit isn't safe once its trigger
got more severe.
