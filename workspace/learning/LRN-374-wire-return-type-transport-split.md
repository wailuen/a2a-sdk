---
id: LRN-374
title: Shared wire() return-type change breaks AG-UI schema and metadata
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`MarketBriefing.wire()` began returning a str. The AG-UI AGENT_ARTIFACT `data` became a string while the agent card still advertises `data: {"type":"object"}`. The GH-63 `metadata` envelope was dropped from that frame, and A2A (model_dump branch) sent a different shape than AG-UI for the same artifact.

## Root cause
Callers of `.wire()` were not enumerated per transport, and no test compared frames to the advertised valueSchema.

## Check
Test: build a MarketBriefing AGENT_ARTIFACT frame with `metadata={'coverage_note': ...}`; validate `data` against the agent card valueSchema (routes/agent_card.py) and assert metadata survives. grep `\.wire()` in agent_sdk/routes/ and check each caller.

## Prevention
When planning a return-type change to a shared method like `wire()`, require a caller grep per transport and a test checking each advertised schema against the new shape. Keep carve-outs in the mapper, not the base contract.
