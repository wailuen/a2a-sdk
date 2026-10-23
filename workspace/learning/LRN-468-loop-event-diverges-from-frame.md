---
id: LRN-468
title: Loop event not reshaped with the A2A artifact frame
category: protocol
severity: high
source: redteam
date: 2026-10-23
---

## What happened
GH-225 made a deferred `emits=KpiCard` tool with a no-match result text-only on A2A. The runner still published `artifact_ev` (model=raw_result), so AG-UI emitted AGENT_ARTIFACT plus two A2UI_UPDATE cards. A2A gave ['text'] while AG-UI gave cards.

## Root cause
Only the wire frame was changed. AG-UI renders from the loop event published beside it, not from the A2A frame.

## Check
Run tests/test_gh225_multi_type_emits.py: a deferred no-match ContentModel result yields no A2UI_UPDATE and no AGENT_ARTIFACT on the store/`/ag-ui/run`. Also grep runner.py for `publish(artifact_frame` and confirm the no-match branch passes None.

## Prevention
When planning a change to how an artifact is shaped on one delivery path, list every sibling output (loop event, AG-UI mapper, MCP result) and change them together. Require a test per surface (A2A, AG-UI, deferred).
