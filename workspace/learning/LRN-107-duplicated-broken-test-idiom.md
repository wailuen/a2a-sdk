---
id: LRN-107
title: Fixed broken test idiom recurs uncaught in a sibling test
category: testing
severity: high
source: redteam
date: 2026-07-10
---

## What happened
RT-002 found a second test (tests/test_gh88_tool_interim_emit.py:288) using
the same fragile `caplog`-vs-`agent_sdk.*` idiom already fixed as
RT-001/LRN-106 — written independently, invisible under per-file gating.

## Root cause
Fixing RT-001 in place fixed only that test, not the anti-pattern — no
shared fixture was mandated repo-wide, so it recurred and surfaced only at
full-scope pytest.

## Check
`grep -rn "caplog\.\(records\|at_level\)" tests/*.py` — every `agent_sdk.*`
match must use `sdk_caplog`, not raw `caplog`. Bare `pytest -q` (LRN-002)
must be green.

## Prevention
Waves adding logging-assertion tests must reuse `sdk_caplog`, never
hand-roll `caplog` on `agent_sdk.*` loggers, and pass full-scope
`pytest -q` before archive — per-file gating misses recurring copies of a
fixed pattern.
