---
id: LRN-513
title: Pre-lookup resume checks must live in the shared helper
category: protocol
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-247 added an AG-UI resume status check only inside `_run()`. The pre-admission `_resume_target_task_id()` calls `_resume_interrupt_id()`, which ignores status and looks up the interrupt first. A bad-status resume at the per-task cap returned 429 instead of RUN_ERROR.

## Root cause
The validation sat in the run generator, not in the helper the pre-admission path also uses.

## Check
Run a test next to `test_two_entry_resume_at_cap_is_run_error_not_429`: a bad-status single-entry resume at `_MAX_A2A_STREAMS_PER_TASK=1` must give 200 + RUN_ERROR "invalid resume entry".

## Prevention
When planning any "checked before lookup" rule for resume entries, put it in `_resume_interrupt_id` (returning "" on invalid), not only in `_run()`. Verify docs claims against the cap path.
