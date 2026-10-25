---
id: LRN-554
title: Diff touches files not declared in todo scope
category: protocol
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`agent_sdk/auth/context.py` (new public `ResumeEnvelope.accepted_output_modes` field) was modified, but no w067 todo lists it in Creates:/Modifies:. `agent_sdk/tasks/store.py` was limited to one runtime-only field, yet the `deliver_resume` docstring was also rewritten.

## Root cause
Implementers extended the change past the declared file and edit scope, and nothing compared the diff to the todo (LRN-168).

## Check
For each file in `git diff --name-only -- agent_sdk/`, grep the wave file for its path in a Creates:/Modifies: line; every file must match, with the edit scope stated.

## Prevention
When planning, list every agent_sdk/ file a group may touch, with the exact edit scope (field, docstring). Public-model fields need their own entry. A CHANGELOG mention does not declare scope.
