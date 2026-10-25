---
id: LRN-047
title: Terminal re-message rule violated — _continue_from_terminal creates new task instead of returning error
category: protocol
severity: critical
source: redteam
date: 2026-06-17
---

## Observation

`_continue_from_terminal` in `agent_sdk/routes/a2a.py` (lines 173–190) silently creates a new
continuation task when an inbound `message/send` or `message/stream` carries a `taskId` that
resolves to a completed, failed, canceled, or rejected task. The branches at lines 247–254
(`message_send`) and 346–350 (`message_stream`) divert into this function before the shared
`_resume_or_error` path (which correctly raises `-32004` at line 206–208) is ever reached.
A2A v0.3.0 §3 and §6 item 14 state unambiguously that a message targeting a terminal task
MUST return an error and MUST NOT start a new task.

## Root Cause

The continuation-task feature was added as a new branch upstream of the terminal-state guard,
rather than being expressed through the correct protocol-compliant path (send a message with a
`contextId` but no `taskId` to begin a new task in an existing context). The prior `-32004`
guard at line 203 is bypassed because the new branch short-circuits before `_resume_or_error`
is called for terminal tasks.

## Prevention

When planning any feature that reuses an existing task context, ensure the new-task path is
driven by `contextId` alone (no `taskId`). Never add a branch that intercepts a `taskId`
referencing a terminal task before the terminal-state guard fires. The A2A §6 item 14 hard MUST
is non-negotiable; implementation convenience cannot override it.

## Check

Verify that sending `message/send` or `message/stream` with a `taskId` whose task is in
`TERMINAL_STATES` returns JSON-RPC error `-32004` (HTTP 400, GH-266 ruling https://github.com/wailuen/a2a-sdk/issues/266#issuecomment-6395232882) and does NOT create a new task:

```
grep -n "_continue_from_terminal" agent_sdk/routes/a2a.py
# Must return no matches — function and all call sites must be removed.

# Regression test: assert -32004 on terminal taskId send (GH-51 test suite)
pytest -q tests/ -k "terminal"
```
