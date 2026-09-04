---
id: LRN-190
title: Single-pop repair doesn't re-check the invariant it was fixing
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`bridge_context_messages`'s DanglingToolUseUnreadable recovery pops one
message and returns without re-running `close_dangling_tool_use`. A
transcript whose unreadable tail sits atop a readable dangling toolUse comes
back still dangling and gets folded into a new task, which Bedrock's
Converse API then rejects.

## Root cause
The recovery branch treated one pop as sufficient because it fixed the
violation that triggered the branch, without accounting for a second,
different violation the single pass had already walked past.

## Check
Add a regression test with `[user(text), assistant(toolUse t1),
assistant(toolUse missing toolUseId)]` and assert the returned transcript has
a matching toolResult for t1 (not just a tail-role check, which
tests/test_rt004_dangling_unreadable_gates_persist.py:213 already does and
passes on the broken output).

## Prevention
When planning a repair/recovery branch that fixes an invariant by dropping
or mutating state, require it to loop: re-run the invariant check after each
repair step (bounded by input length) until it passes clean, rather than
assuming one repair pass suffices.
