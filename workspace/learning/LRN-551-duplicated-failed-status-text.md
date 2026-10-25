---
id: LRN-551
title: Failed-status text hand-built outside the shared builder
category: protocol
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-261 item 7 was marked done, but `_unserializable_tail` in `agent_sdk/routes/a2a.py` still builds the FAILED tail message by hand. The text "invalid agent response" is written twice (TextPart and WireError). GH-259 says every failed task gets status.message from `set_task_status`.

## Root cause
A stream-tail path was left with its own copy of the failed-status text instead of calling the shared builder.

## Check
grep -n "invalid agent response" agent_sdk/routes/a2a.py; confirm at most one literal (a module constant) and that the tail uses the same helper as `set_task_status`.

## Prevention
When planning failed-status changes, require one builder or constant for status text. List every tail/stream path that emits FAILED as an AC and grep each for hand-built TextPart or WireError copies.
