---
id: LRN-125
title: Terminal-artifact guard caught build/wire exceptions but not non-serializable payloads
category: protocol
severity: high
source: redteam
date: 2026-07-15
---

## What happened
RT-001's guard in `_run_deferred_background` and `run_task_worker`'s
ArtifactEvent branch converts `build_artifact()`/`.wire()` exceptions into a
deterministic FAILED task. But `TaskArtifactUpdateEvent.wire()` does no
JSON-serializability check: a tool result resolving to a non-BaseModel,
non-serializable value (plain class, `datetime.date`, `set`) sails through
unchanged, producing a false COMPLETED that only crashes later at the
unguarded `sse_data()` json.dumps, killing the stream with no terminal frame.

## Root cause
The guard only catches raised exceptions; it treated "no exception" as proof
a frame is deliverable, when `build_artifact()`'s scalar branch embeds the
raw value with no serialization dry-run/coercion.

## Check
`tests/test_rt001_deferred_artifact_build_failure.py::test_deferred_nonserializable_result_transitions_to_failed`
and `tests/test_rt001_sync_artifact_nonserializable_emits.py` must pass: a
non-serializable resolved result reaches FAILED (-32006), no artifact
retained, streams closed. `grep -n "json.dumps\|mode=\"json\"" agent_sdk/agent/runner.py`
inside the guarded build block to confirm the dry-run/coercion step exists.

## Prevention
When planning any new path that builds/delivers an artifact frame (new
transport, new ArtifactEvent branch, MCP artifact delivery), require the AC
to state the guard does an explicit JSON-serializability dry-run of the
payload before publish — never treat ".wire() didn't raise" as sufficient —
plus a non-serializable-payload regression test for that surface.
