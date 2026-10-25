---
id: LRN-569
title: CHANGELOG file coverage must use full paths
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`agent_sdk/a2ui/catalog.py` changed in GH-270 but its full path was absent from [Unreleased]. The only "catalog.py" match was inside `tests/test_gh258_catalog.py`, so a basename grep passed by accident while the LRN-491 rule was broken.

## Root cause
Checking by basename matches test file names that embed source basenames.

## Check
For each changed file from `git diff --name-only -- agent_sdk/`, run `grep -F "<full repo path>" CHANGELOG.md` and confirm a match. Never grep the basename.

## Prevention
When planning or checking CHANGELOG coverage, match full `agent_sdk/...` paths. Name symbols as `path::symbol`, for example `agent_sdk/a2ui/catalog.py::_annotation_str`.
