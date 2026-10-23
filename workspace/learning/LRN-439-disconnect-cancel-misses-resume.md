---
id: LRN-439
title: Disconnect-cancel hook skips the resume branch
category: protocol
severity: high
source: redteam
date: 2026-10-22
---

## What happened
In `agent_sdk/routes/ag_ui.py`, `owned.append(record)` ran only on the fresh-run branch. On resume, the record from `store.find_interrupt(interrupt_id, identity)` was never added, so `_cancel_if_unfinished` returned early. A client disconnect during a resumed run left the model turn and tools running, and the CHANGELOG over-claimed.

## Root cause
The hook was attached where the record is created, not where a stream attaches to a worker.

## Check
Run a test that parks an interrupt, resumes via raw ASGI, disconnects before RUN_FINISHED, and asserts the worker is cancelled and the task is CANCELED. `grep -n 'owned.append' agent_sdk/routes/ag_ui.py` must show both branches.

## Prevention
When planning a disconnect or cancel hook, list every branch that attaches a stream to a worker (fresh, resume) and require a test per branch.
