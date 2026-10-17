---
id: LRN-421
title: New bridge_trailing_user caller needs LRN-144 Check amended
category: sdk
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-194 added `_empty_reply_retry` (loop.py), a third caller of `bridge_trailing_user`. The LRN-144 Check still listed only `bridge_context_messages` and `_final_summary`, so the recorded invariant no longer matched the code. The code was correct, but the next redteam would flag it or someone might delete the bridge.

## Root cause
A new helper added a call site without amending the allowed-callers list in the LRN, the same drift as LRN-249.

## Check
`grep -n "_empty_reply_retry(" agent_sdk/agent/loop.py` shows only its definition plus one call in run_loop's no-tool-call exit. Confirm LRN-144 `## Check` lists `_empty_reply_retry`.

## Prevention
When a plan adds a `bridge_trailing_user` call site in loop.py, include a task to amend the LRN-144 Check allowed-callers list in the same change.
