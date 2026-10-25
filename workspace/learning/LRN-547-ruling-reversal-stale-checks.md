---
id: LRN-547
title: Wire-status ruling leaves old status pinned in LRN Checks
category: protocol
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-266 ruling changed terminal-task resume from 501/-32004 to 400/-32004. LRN-197 Check (line 17) and LRN-047 (line 38) still required the old 501, so every later redteam would fail the new docs and push a revert.

## Root cause
The ruling updated code and docs but not the LRN Check clauses that pin the old status.

## Check
`grep -n "501" workspace/learning/LRN-197-*.md workspace/learning/LRN-047-*.md` must show 501 only for the colon-id guard or history text, and resume lines must say 400 with the ruling URL.

## Prevention
When a ruling reverses a wire status, plan a task that greps workspace/learning for the old status and updates each Check clause in the same wave. Keep history in "What happened".
