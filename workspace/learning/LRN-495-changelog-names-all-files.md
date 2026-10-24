---
id: LRN-495
title: CHANGELOG bullet omits one-line route edits
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-235 changed `agent_sdk/routes/ag_ui.py` (resume length check, line 717), but no [Unreleased] entry named that file. `grep -c 'ag_ui.py'` over the block returned 0, failing LRN-491.

## Root cause
The bullet described behaviour but listed only the main file; the small route edit was treated as too minor to name.

## Check
For each path in `git diff --name-only -- agent_sdk`, `grep -c "<path>"` over the [Unreleased] block must be >= 1.

## Prevention
When planning a group, require its CHANGELOG bullet to name every changed `agent_sdk/` file by repo path, including one-line edits. Compare the bullet to the diff file list before sign-off.
