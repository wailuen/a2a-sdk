---
id: LRN-123
title: task.artifacts must be appended AFTER the wire frame serializes, not before
category: protocol
severity: low
source: redteam
date: 2026-07-14
---

## What happened
w034/group G RT-002: both `runner._run_deferred_background`'s success path
and `run_task_worker`'s `ArtifactEvent` branch appended the built artifact to
`task.artifacts` BEFORE `TaskArtifactUpdateEvent(...).wire()` serialized the
frame. If `.wire()` raised, the surrounding `except` transitioned the task to
FAILED, but the just-appended artifact remained on the now-FAILED task record
— an artifact that was never actually delivered on any stream.

## Root cause
`build_artifact()` succeeding was treated as the trigger to mutate
`task.artifacts`, when the correct trigger is "the wire frame is about to be
published" — a step later, after `.wire()` has already succeeded.

## Check
`grep -n "task.artifacts = " agent_sdk/agent/runner.py` — at each call site,
confirm the preceding lines already call `.wire()` successfully (i.e. the
append happens after serialization, not before).

## Prevention
When planning any code path that builds an A2A artifact and appends it to
`task.artifacts`, require the AC to state the append happens AFTER the
`TaskArtifactUpdateEvent.wire()` call succeeds, so a serialization failure
degrades to a clean FAILED task with no stranded artifact. Add a regression
test that forces `.wire()` to raise (e.g. via `monkeypatch.setattr`) on an
otherwise-successful artifact build and asserts the FAILED task's
`artifacts` list is empty.
