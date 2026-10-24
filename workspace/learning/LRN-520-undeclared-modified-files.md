---
id: LRN-520
title: Phase gate must check git diff, not declared files
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
`agent_sdk/example/agent.py` was changed so `publish_note` reads `payload.decision` after GH-247 refused the AG-UI status shorthand. The file was not named in the CHANGELOG [Unreleased] section or in any todo's Creates/Modifies list, so the LRN-491 check failed.

## Root cause
The LRN-491 basename check ran only over files the todos declared, so a knock-on edit outside the plan went unseen.

## Check
For each path in `git diff --name-only -- agent_sdk`, verify its basename appears in CHANGELOG [Unreleased] and in a todo Creates/Modifies list under workspace/todos/active/.

## Prevention
When planning a behavior change, list its callers (examples, contrib, testing helpers) in the todo's Modifies list. Run the LRN-491 basename check over the full `git diff --name-only -- agent_sdk` at the phase gate.
