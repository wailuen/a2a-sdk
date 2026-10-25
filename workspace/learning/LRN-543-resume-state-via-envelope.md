---
id: LRN-543
title: Resume state must travel in the envelope
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`routes/a2a.py` set `record.accepted_output_modes` on the record `store.get()` returned. A copy-on-get store loses the change, and `a2ui_opted_in` read back False (wrong 415). Two back-to-back resumes let the loser overwrite the winner's modes before getting -32001.

## Root cause
Handoff state was written to a store-returned record, not sent through the `deliver_resume` channel.

## Check
`grep -n 'record\.accepted_output_modes *=' agent_sdk/routes/` finds no route-side write. Test: copy-on-get store resume applies new modes; a losing resumer changes nothing.

## Prevention
When planning resume features, require route-to-worker state in `ResumeEnvelope` and a copy-on-get store test plus a two-racer test.
