---
id: LRN-467
title: CHANGELOG alias mention trips ratchet test unplanned
category: testing
severity: high
source: redteam
date: 2026-10-23
---

## What happened
The GH-218 CHANGELOG line named AGENT_SDK_TRUSTED_PROXIES, forcing it out of `_GRANDFATHERED_ALIASES` in tests/test_changelog_gh143_gh144_wire_changes.py. That test file was modified but is in no todo Creates/Modifies line and the CHANGELOG bullet does not name it (LRN-441/LRN-446 check fails).

## Root cause
The planner did not foresee that naming a grandfathered settings alias in CHANGELOG changes the alias ratchet test.

## Check
Verify that `grep -c "test_changelog_gh143_gh144_wire_changes" workspace/todos/active/*.md` is at least 1 whenever that test file appears in `git diff --name-only`.

## Prevention
When planning a CHANGELOG line that names a grandfathered settings alias, add tests/test_changelog_gh143_gh144_wire_changes.py (`_GRANDFATHERED_ALIASES`) to the same todo's Creates/Modifies line and add a `Tests:` clause to the bullet.
