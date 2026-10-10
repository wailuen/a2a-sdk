---
id: LRN-287
title: Todo "Reuses: C-NNN" either/or directive landed neither branch
category: sdk
severity: high
source: redteam
date: 2026-10-10
---

## What happened
A todo said "Reuses: C-024": build the shared bounded store with a per-key quota, or amend the C-024 registry entry. Neither was done. IdpFlowStore hand-rolled a third OrderedDict eviction variant and C-024 stayed "planned" with no quota in its contract.

## Root cause
The either/or directive was not tracked as a gate, so the implementer shipped bespoke code and left the registry untouched.

## Check
Verify that for every `Reuses: C-NNN` in the wave todo, either the code imports the shared component or the `workspace/components/README.md` diff changes that C-NNN row. Run `grep -n "C-024" workspace/components/README.md` and confirm it mentions the per-source quota.

## Prevention
When planning a todo with a "Reuses: C-NNN" either/or, split it into one explicit task per branch and require the registry diff or the shared-module import as an acceptance criterion.
