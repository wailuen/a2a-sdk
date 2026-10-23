---
id: LRN-454
title: Rate-limited scenarios scored as pass in acceptance gate
category: testing
severity: high
source: redteam
date: 2026-10-22
---

## What happened
acceptance-api.js told the scenario agent "If every turn on a transport was rate-limited, score that transport 10", and passed=true needs both transports at 7 or more. A scenario with no answered turn could report passed, contradicting SKILL.md:489. The JS only counted rate-limited results and never overrode passed.

## Root cause
An infrastructure failure class was mapped to a top score, and no code forced passed=false.

## Check
`grep -n "score that transport 10" harness/workflows/acceptance-api.js` returns no match; a behaviour test asserts a result with `failureClass==='rate-limited'` is never counted as passed and shows as "not run".

## Prevention
When planning pass gates, make excluded or infrastructure failures count as not run (passed=false) in code after the pipeline, not via prompt wording. Untested turns never score 10.
