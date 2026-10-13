---
id: LRN-345
title: Scope scan accepts only backticked paths, misses planner format
category: ops
severity: high
source: redteam
date: 2026-10-13
---

## What happened
The GH-164 scope scan in wave-cycle.js extracted only backticked tokens. The planner writes bare comma-separated paths (`- Creates: a.py, b.py`), so the scan printed `[]` and the mismatch gate never fired.

## Root cause
The guard was tested against one todo format, not the formats the harness itself writes.

## Check
Run the scan script (extracted from wave-cycle.js) on fixtures: planner bare format, bare `(modifies a, b)`, backticked, bold `**Creates:**`. Assert each yields its paths (`tests/test_wave_scope_extraction.py`).

## Prevention
When planning a deterministic parser over todo files, require fixtures for every format the planner agent documents, and a fail-closed result when path-shaped tokens go unparsed.
