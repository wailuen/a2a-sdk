---
id: LRN-121
title: Codified LRN Check exists as text but isn't wired into an enforced gate
category: ops
severity: high
source: redteam
date: 2026-07-14
---

## What happened
RT-001 found `agent_sdk/common/origin.py` untracked (`??`) yet imported by
`routes/mcp.py`, `routes/a2a.py`, `routes/ag_ui.py` — the exact scenario
LRN-119 already documented. LRN-119's Check clause currently fails on the
live tree: it was recorded but never executed.

## Root cause
A codified Check clause was treated as satisfied once written to a learning
file, with no automated step actually running it pre-archive — so the
same untracked-import-at-archive failure recurred verbatim.

## Check
Verify a pre-archive gate runs `git status --short` and cross-checks every
`??` `.py` file for import-by a tracked module; fail (non-zero) if any such
file isn't also listed in the todo's Creates: and isn't yet `git ls-files`-tracked.
`git ls-files agent_sdk/common/origin.py` must be non-empty before archive.

## Prevention
When planning a wave/archive step, require LRN Check clauses tagged as
pre-archive gates to be an executable script step in wave-cycle.js's
archive phase, not a documentation-only reminder. Track "Check exists as
text" and "Check is enforced as gate" as separate, both-required criteria.
