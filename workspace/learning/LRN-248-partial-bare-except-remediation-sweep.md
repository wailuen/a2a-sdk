---
id: LRN-248
title: LRN-044 regression — a remediation sweep left one bare except unlogged
category: security
severity: critical
source: redteam
date: 2026-09-03
---

## What happened
Three bare `except Exception` blocks in `runner.py` map caught errors to a
fixed wire string via `isinstance(exc, ValueError)`, but none log
`type(exc).__name__`. Since pydantic's `ValidationError` subclasses
`ValueError`, any validation failure between toolUse fold and toolResult
fold (e.g. inside `build_artifact`) is silently reduced to "invalid agent
response" with zero operator attribution — the exact failure LRN-044 was
written against, in the file its Check names. The wave's own regression
test docstring claims "two bare except blocks" when there are three; the
untested third (line 1056) is the one that swallows `build_artifact`/
`translate()` failures.

## Root cause
The LRN-044 remediation was applied to two of three matching handlers; the
regression test's own scope description was never checked against the
actual site count, so the gap shipped covered by a test that describes
itself as complete.

## Check
`grep -n "except Exception" agent_sdk/agent/runner.py` at lines ~895, 1056,
1405 — each must log `type(exc).__name__` via `logger.warning`/`.error`
before `_fail`/`set_task_status(FAILED)`. `tests/test_rt003_deferred_exception_enrichment.py`
must cover all three sites, not two.

## Prevention
When a redteam/implement fix claims to close an LRN, require the fix to
grep the LRN's Check pattern across the *whole* file (not just the sites
the finding named) and require the regression test's docstring site-count
to match `grep -c` on the actual pattern before marking it closed.
