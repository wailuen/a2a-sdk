---
id: LRN-293
title: New field on exported class lacks scope, changelog, durability note
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
GH-154 added `TaskRecord.date_line` in agent_sdk/tasks/store.py. TaskRecord is exported in `agent_sdk.tasks.__all__`, yet store.py was missing from the todo's Modifies list, CHANGELOG [Unreleased] did not mention the field, and DESIGN.md §5 did not say whether durable stores must persist it.

## Root cause
A public-surface change was made as an internal detail, so the LRN-202 public-API checklist was skipped.

## Check
For each new field on a class in any `__all__`, confirm: file is in the todo scope, `grep -n "date_line" CHANGELOG.md` finds an `### Added` line, and DESIGN.md §5 states whether TaskStore subclasses must save it.

## Prevention
When planning a new field on an exported class, list the defining file in Modifies, add a CHANGELOG Added line, and add a durability note (persist vs runtime-only) for TaskStore subclasses.
