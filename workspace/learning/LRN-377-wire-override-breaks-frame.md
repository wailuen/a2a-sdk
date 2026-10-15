---
id: LRN-377
title: Model wire() fix silently changes protocol frame shape
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-179 item 5 only asked to override `wire()`, but the MarketBriefing AG-UI AGENT_ARTIFACT `data` changed from the field dict to `{"markdown", "metadata"?}`. The cited ruling covered only item 1, A2A's non-A2UI DataPart still carried the field dump, and DESIGN.md §4.3/§5.3 was not updated.

## Root cause
A model-level fix was allowed to change a public wire frame without its own ruling, splitting the surfaces.

## Check
Verify `ag_ui.py` MarketBriefing AGENT_ARTIFACT data equals the `runner.py` A2A DataPart data, or that an `issues/<n>#issuecomment` ruling URL for the new shape is in CHANGELOG and DESIGN.md.

## Prevention
When planning a `wire()` change, list every protocol frame whose data shape changes. Treat each as a separate breaking change needing its own recorded maintainer ruling and a DESIGN.md update.
