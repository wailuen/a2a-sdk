---
id: LRN-139
title: Deferred tool handoff leaves dangling toolUse with no matching toolResult
category: protocol
severity: high
source: redteam
date: 2026-09-02
---

## What happened
The GH-87 deferred-handoff path returns from `run_loop` right after the assistant
`toolUse` block is appended but before the matching `toolResult` would be. The
background resolver (`_run_deferred_background`) never touches `record.messages`, so a
completed deferred task's stored transcript ends on a dangling `toolUse` block, which
Converse-shaped backends (Bedrock) reject on the next turn.

## Root cause
Only the request path (a2a.py, ag_ui.py) appends to `record.messages`; the background
deferred-resolution path was never wired to close out the `toolUse` it left open, unlike
the cancel path already fixed for GH-150.

## Check
`grep -n "toolUseId" agent_sdk/agent/runner.py` — confirm `_run_deferred_background`
appends a `toolResult` for the deferred call on both success and failure/timeout; add a
test asserting no `toolUse` in `record.messages` lacks an immediately-following matching
`toolResult` after a deferred tool resolves.

## Prevention
Every `run_loop` exit path that returns after folding an assistant `toolUse` block must
be planned with an explicit matching-`toolResult` step (cancel, deferred handoff,
max-turns) — an unmatched `toolUse` breaks Converse-style transcript replay.
