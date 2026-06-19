---
id: LRN-090
title: Protocol route rename leaves reference binding table stale
category: protocol
severity: high
source: redteam
date: 2026-06-15
---

## What happened
GH-75 renamed the live A2A resubscribe route to `POST /v1/tasks/{id}:resubscribe` in `a2a.py`, but the canonical reference table at `harness/reference/a2a-protocol-0_3_0.md:67` still maps `tasks/resubscribe` to `POST /v1/tasks/{id}:subscribe`. The same stale entry exists in the peer copy at `template/.claude/reference/a2a-protocol-0_3_0.md:67`. Because the a2a-advisor agent and the a2a-check skill cite this table as ground truth, the conformance auditor flags the corrected implementation as wrong and may recommend the now-404 path.

## Root cause
The route rename wave updated the implementation file but did not include the companion reference binding table or its template peer copy as required modifies, leaving the advisor's source-of-truth out of sync with the live wire path.

## Check
`grep -n "subscribe" harness/reference/a2a-protocol-0_3_0.md template/.claude/reference/a2a-protocol-0_3_0.md` — confirm both show `POST /v1/tasks/{id}:resubscribe` (not `:subscribe`) in the `tasks/resubscribe` row.

## Prevention
When planning any protocol route rename, ensure the wave's modifies list explicitly includes the companion reference binding table (`harness/reference/<protocol>.md`) and its template peer copy (`template/.claude/reference/<protocol>.md`); the advisor agent and check skills cite these files as ground truth, so a rename that omits them makes the auditor regress against the old path.
