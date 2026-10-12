---
id: LRN-295
title: New model call on exit path skips budget and deadline guards
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
GH-155 added a summary model call to the max-turns exit in loop.py without checking token budget or deadline. With budget 200000, max_turns=1 and a 250000-token first turn, the run ended at 500500 tokens. A deadline passed during tools produced one more untimed call and reported "max turns exceeded" instead of "task deadline exceeded".

## Root cause
The old exit made no model call, so it never needed guards; adding a call did not trigger a re-audit of the guards.

## Check
Verify tests exist for max_turns with an exceeded budget and max_turns with an exceeded deadline, and that both exits share one gate helper: `grep -n "deadline.exceeded" agent_sdk/agent/loop.py`.

## Prevention
When planning a model call on any exit path, list every spend and time guard (token budget, deadline) and require each be applied on that path. Put the gate in one shared helper.
