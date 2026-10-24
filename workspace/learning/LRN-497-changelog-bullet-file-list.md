---
id: LRN-497
title: CHANGELOG bullet lacks changed file list
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The GH-240 bullet named none of the four `agent_sdk` files G4 changed: `a2ui/translator.py`, `a2ui/catalog.py`, `agent/runner.py`, `routes/a2a.py`. Each appeared 0 times in [Unreleased], failing LRN-491. The wave rule requires every item to name each changed file.

## Root cause
The bullet described behaviour only and skipped the "Changed: <files>" list that the GH-236 bullet used.

## Check
For each file in `git diff --name-only -- agent_sdk`, `grep -c` of its path over the [Unreleased] block must be >= 1.

## Prevention
When planning a group, include a CHANGELOG step: end each bullet with "Changed: <every agent_sdk path, docs, DESIGN.md>", built from the diff file list, in the GH-236 format.
