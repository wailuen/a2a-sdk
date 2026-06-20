---
id: LRN-090
title: Protocol route rename leaves reference binding table stale
category: protocol
severity: high
source: redteam
date: 2026-06-15
---

## What happened
GH-75 corrected the live A2A resubscribe route from `POST /v1/tasks/{id}:resubscribe` back to `POST /v1/tasks/{id}:subscribe` in `a2a.py` (per spec §2 transport table; see LRN-099). However, the canonical reference table at `harness/reference/a2a-protocol-0_3_0.md:67` and its peer copy at `template/.claude/reference/a2a-protocol-0_3_0.md:67` still mapped `tasks/resubscribe` to the old `:resubscribe` suffix. Because the a2a-advisor agent and the a2a-check skill cite this table as ground truth, the conformance auditor flagged the corrected implementation as wrong and recommended the now-404 path.

## Root cause
The route correction wave updated the implementation file but did not include the companion reference binding table or its template peer copy as required modifies, leaving the advisor's source-of-truth out of sync with the live wire path.

## Check
`grep -n "subscribe" harness/reference/a2a-protocol-0_3_0.md template/.claude/reference/a2a-protocol-0_3_0.md` — confirm both show `POST /v1/tasks/{id}:subscribe` (not `:resubscribe`) in the `tasks/resubscribe` row. The JSON-RPC method name `tasks/resubscribe` is correct and unchanged; only the REST path suffix must be `:subscribe`.

## Prevention
When planning any protocol route change, ensure the wave's modifies list explicitly includes the companion reference binding table (`harness/reference/<protocol>.md`) and its template peer copy (`template/.claude/reference/<protocol>.md`); the advisor agent and check skills cite these files as ground truth, so a route correction that omits them makes the auditor regress against the old path.

## Related
- LRN-099: A2A v0.3.0 spec §2 transport table maps `tasks/resubscribe` JSON-RPC method to `POST /v1/tasks/{id}:subscribe` REST path — the `:subscribe` suffix is the spec-correct form.
