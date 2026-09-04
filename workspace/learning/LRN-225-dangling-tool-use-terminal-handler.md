---
id: LRN-225
title: Terminal exception handlers skip dangling tool_use repair
category: protocol
severity: high
source: redteam
date: 2026-09-02
---

## What happened
`run_task_worker`'s `except AgentError` and `except Exception` handlers set the task to
FAILED and publish the terminal frame without calling `repair_dangling_tool_use`. If the
exception fires mid-tool-call, `record.messages` ends on an assistant `toolUse` with no
matching `toolResult`. FAILED is terminal, so `context_messages()` replays that broken
transcript into the next turn and Bedrock's Converse API rejects it — the exact GH-150
defect.

## Root cause
The shared repair helper was wired into the deliberate cancel/deferred exit paths but not
into the loop's own catch-all exception handlers, despite the loop's own docstring
claiming universal coverage.

## Check
`grep -n "repair_dangling_tool_use" agent_sdk/agent/runner.py` — confirm both the
`except AgentError` (~line 881) and `except Exception` (~line 894) branches call it
before `_set_status(..., FAILED, ...)`. Add a regression test that a task FAILED
mid-tool-call leaves no dangling `toolUse` in `context_messages()`.

## Prevention
When planning any change to a task loop's terminal-state writers, require every writer of
`record.messages` at a terminal transition — including catch-all exception handlers, not
only intentional exit paths — to call the shared repair helper, and update the helper's
docstring to name every actual caller.
