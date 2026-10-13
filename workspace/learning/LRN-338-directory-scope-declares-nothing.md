---
id: LRN-338
title: Directory in todo scope declares no files
category: ops
severity: high
source: redteam
date: 2026-10-13
---

## What happened
Wave changes landed in `agent_sdk/console/static/console.js` (GH-163 named only `agent_sdk/console/`), `docs/protocols.md`, `uv.lock`, three `_fold_history` test files, `tests/test_gh152_idp_authorize_flow.py` and a w042 deferred file. No todo named them by exact path, so they escaped the wave scope and every scope-keyed gate (LRN-207, LRN-322).

## Root cause
The scope rule rejects directory entries, and todos were written with directory or prose scope.

## Check
Run `git status --short` and confirm every modified or new path appears as an exact path on a `Creates:` or `Modifies:` line in `workspace/todos/`. Include `uv.lock` when a version bump resyncs it.

## Prevention
When planning todos, list every file by exact path on `Creates:`/`Modifies:`, including tests, docs, lockfiles and deferred notes. Never use a directory or prose phrase as scope.
