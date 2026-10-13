---
id: LRN-316
title: AG-UI input rejection must not scan replayed history
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-159 made AG-UI `_validate()` reject a non-text part in any message of the replayed history. Clients re-send the whole history each turn, so one rejected image turn made every later turn end in RUN_ERROR, and resume runs were blocked. Probe: history [binary user turn, text user turn] gave RUN_ERROR. The docstring's RT-001 "never hard-reject content" became false.

## Root cause
The check scanned all messages instead of only the new input of this run.

## Check
Run a test where history holds an earlier binary user turn and the new text turn succeeds; also confirm resume is not rejected. Review `_validate` in `agent_sdk/routes/ag_ui.py`.

## Prevention
When planning AG-UI input rejection rules, scope them to the newest user message only, skip resume, and let history folding drop old unsupported parts. Add a bad-history-then-good-turn test.
