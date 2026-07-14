---
id: LRN-124
title: Archive note describing a redteam fix must cover the full landed diff, not just its headline AC
category: ops
severity: low
source: redteam
date: 2026-07-14
---

## What happened
w034/RT-003: the archive note at the top of `workspace/todos/completed/w034-gh-issues.md`
described the RT-002 fix in `agent_sdk/agent/runner.py` as only "serialize the
artifact wire frame before mutating `task.artifacts`". The actual landed diff
was substantially larger: a new `_fail()` helper consolidating every
pre-delivery FAILED branch (`runner.py`, `_run_deferred_background`), a
synthetic `ToolResultEvent(ok=False)` now published on ALL deferred FAILURE
branches (timeout / cancel / generic exception / artifact-build failure) —
where the prior code published none — closing the AG-UI tool-call lifecycle
symmetrically with the success path, and `run_task_worker`'s terminal
`DoneEvent` publish moved outside the `try` into the `else:` clause so a
publish failure there cannot re-enter the FAILED path a second time. These
three behavioral wire changes were documented only in test docstrings
(`tests/test_rt002b_deferred_terminal_frame_no_duplicate.py`,
`tests/test_rt002c_sync_worker_terminal_frame_no_flip.py`,
`tests/test_rt002_deferred_failed_tool_result.py`), not in the archive note —
understating what changed on the wire for anyone reading the wave's audit
trail without also reading every test file.

## Root cause
A redteam follow-up round widened its own fix's blast radius (root-causing
the narrow AC into a broader control-flow consolidation) without a
corresponding widening of the archive note that summarizes the wave for
future readers. The same class as LRN-119 (untracked mid-wave scope), but on
the archive/audit-trail side rather than the `Creates:`/staging side.

## Check
When a wave's archive note cites a specific file:line fix, diff that file
against the wave's branch point and confirm every additional
control-flow/behavioral change (new helper functions, new event publishes,
moved code blocks) is either named in the archive note or explicitly called
out as an intentional, separately-justified widening — not left to be
inferred from test docstrings alone.

## Prevention
When a redteam follow-up round lands behavioral wire changes beyond a todo's
original AC, record them in the wave's tracking/archive doc at codify time,
not only in test docstrings, so the audit trail matches the diff. Treat "the
archive note undersells the diff" as its own low-severity finding class,
distinct from whether the landed code itself is correct.
