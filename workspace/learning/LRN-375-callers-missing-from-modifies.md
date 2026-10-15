---
id: LRN-375
title: Return-type change leaves caller files off the todo Modifies line
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-179 item 5 changed a model method so `_validate_a2ui_wire` in `agent/runner.py` accepts a str for MarketBriefing. `runner.py` and `routes/ag_ui.py` (AGENT_ARTIFACT data shape) changed behaviour but were not on any Creates:/Modifies: line in `w050-gh-issues.md`.

## Root cause
The plan scoped files by the model being edited, not by the callers whose behaviour follows from its new return type.

## Check
For each `agent_sdk/**` file in `git diff --name-only`, grep the active todo for it: `grep -c "<file>" workspace/todos/active/*.md` must be >= 1, and each has a matching test.

## Prevention
When planning a todo that changes a base-class method's return type, grep for every caller (`grep -rn "<method>" agent_sdk/`) and list each caller file on the Modifies: line with a test, before implementing.
