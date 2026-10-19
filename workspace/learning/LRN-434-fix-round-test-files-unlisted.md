---
id: LRN-434
title: Fix-round test files and base-class changes missing from todo scope
category: testing
severity: high
source: redteam
date: 2026-10-19
---

## What happened
GH-202 fix round added `tests/test_gh202_api_key_races.py` and changed `_MemStore` in `tests/test_gh183_184_service_key_mint_step.py` from a duck-typed class to a `CredentialStore` subclass. Neither path was on a Creates/Modifies line (LRN-361 scope check failed). The subclass change also hid a behavior change: `ApiKeyStore.count()` now needs `list_items`, so duck-typed stores raise AttributeError at startup.

## Root cause
Fix rounds edit tests without updating the todo scope, and a new base-class method silently breaks duck-typed stores.

## Check
For each `git status` test path in a wave, grep the active todo: `grep -c "<path>" workspace/todos/active/*.md` must be >= 1. Grep CHANGELOG.md for "CredentialStore" or "list_items" when `ApiKeyStore` gains a store method.

## Prevention
When planning a fix round, add every test file created or edited (including duck-type to subclass changes forced by a new base method) to the todo's Creates/Modifies line in the same round. Note any new required store method in the CHANGELOG.
