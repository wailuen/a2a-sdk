---
id: LRN-458
title: Re-captured golden hash test not declared in todo
category: testing
severity: high
source: redteam
date: 2026-10-23
---

## What happened
GH-222 re-captured the authorization-server metadata golden hash in tests/test_gh152_idp_off_regression.py. That file was not in the G3 todo's Creates: line nor in the GH-222 CHANGELOG Tests list.

## Root cause
A wire change forced an existing test to be edited, but the edit was not recorded in the todo scope.

## Check
Verify that `git diff HEAD --name-only -- tests/` lists only files named in workspace/todos/active/*.md Creates: lines (grep each basename), per LRN-441.

## Prevention
When planning a wire change, ensure the todo lists every existing golden-hash or regression test it will re-capture, in Creates: and in the CHANGELOG Tests list.
