---
id: LRN-571
title: CHANGELOG bullet names symbols but not file paths
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-271 CHANGELOG bullets named symbols (`apply_output_modes`, `TaskStore.get`) but never the full paths agent_sdk/routes/a2a.py, agent_sdk/agent/runner.py, agent_sdk/tasks/store.py or workspace/components/README.md. The bullet also misdescribed old behaviour as "always deleted".

## Root cause
Bullets were written from symbol names, not from the todo's touched-file list, and old behaviour was not re-read from `git show`.

## Check
For each file in `git diff --name-only -- agent_sdk workspace/components`, `grep -c "<path>" CHANGELOG.md` in the [Unreleased] block must be >= 1.

## Prevention
When planning, require every GH-N CHANGELOG bullet to carry a `Files:` list with the full repo path of every touched agent_sdk file, and verify any "was:" claim against `git show HEAD:<file>`.
