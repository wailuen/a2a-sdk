---
id: LRN-325
title: Mirror guard test silently passes when peer repo absent
category: testing
severity: high
source: redteam
date: 2026-10-13
---

## What happened
`test_skills_have_no_stale_parent_message_id_trap` in `tests/test_gh156_mcp_text_ids.py` wraps each mirror path in `if p.exists()`. Without `template/` checked out (CI), the mirror is skipped and the test passes. It also never compares the copies, and it belongs to GH-158 but sits in the GH-156 file. LRN-157's Check failed.

## Root cause
An existence guard was used instead of an explicit xfail, so absence became a silent pass.

## Check
`grep -n "p.exists()" tests/test_gh156_mcp_text_ids.py` must show no guard around mirror paths. Confirm the test is parametrized over all three paths and asserts .claude and harness copies are byte-identical.

## Prevention
When planning mirror-guard tests, require `pytest.xfail` or a failure for an absent mirror, never `if exists`. Place the test in the file of the issue it guards.
