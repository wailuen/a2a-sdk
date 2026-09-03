---
id: LRN-162
title: Wave runs template/ deliverable with no template/ checkout
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-131/GH-132 declared `template/.claude/workflows/wave-cycle.js` (peer-repo
copy, LRN-071/085) as a deliverable, but `template/` is absent from this
checkout. Propagation is unrunnable: both `test_workflow_sync.py` guards
xfail, and `HARNESS_TEMPLATE_SHARED` parametrize collapses to zero cases.

## Root cause
Nothing checked the peer-repo checkout existed before implementation began,
so the missing prerequisite silently degraded to xfail/empty parametrize.

## Check
```bash
test -d template/ || echo MISSING
pytest -q tests/test_workflow_sync.py -rA | grep -E "xfail|passed"
```
Both tests must PASS with nonzero parametrize count, not xfail.

## Prevention
A wave listing any `template/.claude/workflows/*` deliverable must add a
preflight step verifying `template/` exists. Absence blocks the wave.
