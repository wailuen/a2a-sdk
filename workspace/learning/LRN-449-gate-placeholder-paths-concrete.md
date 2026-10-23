---
id: LRN-449
title: Deliverable gate treats NNN placeholder paths as files
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
The gate checked `workspace/learning/LRN-NNN-x.md` as a concrete path and reported it missing, though the real file was LRN-435-.... Its pat() only handled `*` and `?`, so the group would be marked incomplete and archive blocked.

## Root cause
Planner placeholders (LRN-NNN, C-NNN, run-NNN) were not recognised as patterns.

## Check
Test feeds a real `Creates:` line with a `LRN-NNN` path through Parse and then the gate script; expect no "missing". `grep -n "N{3,}" harness/workflows/wave-cycle.js` shows the placeholder rule.

## Prevention
When planning deliverable gates, treat any NNN segment as a glob ([0-9]*) with the freshness rule, never as a concrete path.
