---
id: LRN-383
title: Reuses-driven helper still needs scope and CHANGELOG entry
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
dumps_strict was added to common/json_strict.py (and `__all__`) and rewired into sse.py and routes/mcp.py. None of the three files was in the w050 todo's Modifies line, and the CHANGELOG [Unreleased] section did not name them.

## Root cause
The change was treated as covered by a Reuses note, but LRN-322 says a Reuses note is not a scope declaration.

## Check
Compare `git diff --name-only` production files against every todo Modifies/Creates line; grep CHANGELOG.md [Unreleased] for `dumps_strict` and confirm an Added bullet exists.

## Prevention
When a Reuses note introduces or rewires a helper, plan it as a production change: list each touched file in Modifies and add a CHANGELOG Added/Fixed bullet.
