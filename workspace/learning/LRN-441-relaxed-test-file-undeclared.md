---
id: LRN-441
title: Test file relaxed for a wire change must be declared in the todo
category: testing
severity: high
source: redteam
date: 2026-10-22
---

## What happened
For GH-219, tests/test_forwarding_integration.py (lines ~168-173) was relaxed from `securitySchemes == {bearer}` to a key-set check. No todo Creates/Modifies line or CHANGELOG entry named the file.

## Root cause
The older exact-equality assertion broke as a side effect of the card change, and the fix was made without updating the todo scope.

## Check
For each path in `git diff --name-only -- agent_sdk tests`, run `grep -c <path> workspace/todos/active/*.md` and confirm >= 1.

## Prevention
When a card or wire change may break an exact-equality test, plan that test file into the todo's Modifies line and the CHANGELOG bullet in the same commit.
