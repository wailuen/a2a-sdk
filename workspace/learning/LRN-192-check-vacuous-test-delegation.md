---
id: LRN-192
title: Check clause delegates coverage to a test that never actually runs
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
LRN-020/034/075's `## Check` clauses dropped a direct `template/` grep,
justified by "`test_workflow_sync.py` already keeps them identical." That
axis is empty here: `HARNESS_TEMPLATE_SHARED` derives from
`TEMPLATE_DIR.glob('*.js')`, zero cases when `template/` is absent, and
its guards are `xfail(strict=True)` — never a failure.

## Root cause
"A test references this invariant" was treated as "a test exercises it,"
without confirming the cited test's case count or outcome.

## Check
Before a Check cites test X as replacement coverage, confirm X collects
>=1 case and isn't `xfail(strict=True)`/`skip`: `grep -n
'xfail(strict=True)\|pytest.mark.skip' <test>` near the invariant — a
match requires a real pass/fail run, not mere presence.

## Prevention
A Check rewrite swapping a direct assertion for "test Y covers this"
must cite Y's actual run output (case count + result), never just its
existence — reject delegation to xfail(strict=True)-guarded or
zero-case-parametrized tests.
