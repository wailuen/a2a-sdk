---
id: LRN-562
title: Wire scalars persisted without type check
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
A2A frames with a non-string task id, contextId or status.state passed the _obj/_text_of guards and were saved in at.ids. run_turn then called write_text(int|list) and raised TypeError, breaking the "no raw exception escapes" ruling.

## Root cause
The shape guard stopped at container types, so wrong scalar types survived until they were written to disk.

## Check
Verify tests exist in tests/test_gh237_testing_clients.py for {kind:'task', id:123} and status {state:['x']}, each asserting reason 'malformed-stream'. Review `_a2a_attempt` in agent_sdk/testing/turns.py: id/taskId/contextId/state must be checked as str.

## Prevention
When planning wire readers, require read-time str checks on any value persisted to disk or typed dict[str,str], and a wrong-scalar probe test per such field.
