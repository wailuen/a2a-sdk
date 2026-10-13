---
id: LRN-318
title: Validation skip-guard looser than the branch it defers to
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
AG-UI `_validate` skipped the GH-159 non-text rejection whenever `body['resume']` was truthy. The route treats resume as real only when it is a non-empty list. `resume=true` with a binary part fell to the fresh-run branch, dropped the part silently, and ended `RUN_FINISHED`.

## Root cause
Two different predicates for "is this a resume" on the same field.

## Check
Confirm one shared helper (e.g. `_is_resume(body)`) is used by both `_validate` and the generator in `agent_sdk/routes/ag_ui.py`. Test: resume in `True`, `"x"`, `{}`, `[]` plus a binary newest part gives `RUN_ERROR` and no task.

## Prevention
When planning a validation that is skipped for another code path, require the skip to call the same predicate function as that path, with parametrized bypass tests.
