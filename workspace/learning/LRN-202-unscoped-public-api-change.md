---
id: LRN-202
title: Public API change lands outside declared todo/CHANGELOG scope
category: sdk
severity: high
source: redteam
date: 2026-08-19
---

## What happened
w040 group G's todo scoped changes to routes/a2a.py and routes/mcp.py only,
but the diff also added a new public `Subscription.owner_task` attribute and
reaping behavior in `agent_sdk/tasks/store.py` and `memory.py` — both
exported from `tasks/__init__.py::__all__` (TaskStore is C-005). Neither file
appears in the todo's Modifies: line or either CHANGELOG entry's file list.

## Root cause
Planning scoped by the directory the feature request named (routes/) without
tracing that the change also widened an exported stable-core class's public
surface, so the extra touch never entered the declared scope that drives
adversarial review, protocol audit, or SemVer accounting.

## Check
For each production file in `git status --short`/diff, confirm it appears in
its wave's todo Creates:/Modifies: line AND in the CHANGELOG entry's file
list; for any newly-public attribute/method on a class in an `__all__`
export, confirm an `### Added` CHANGELOG line exists. Same class as LRN-053 /
LRN-168, extended to CHANGELOG file-list parity.

## Prevention
When planning a wave that touches a component registered in the component
registry (C-NNN) or exported via `__all__`, grep its full symbol surface
(attributes/methods) for the diff, not just the directories named in the
request, and add every touched file to both the todo scope and the
CHANGELOG file list before implementation starts.
