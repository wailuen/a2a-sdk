---
id: LRN-376
title: Green pytest does not prove mypy gate passes after route change
category: testing
severity: high
source: redteam
date: 2026-10-15
---

## What happened
A new MarketBriefing branch in `_RunMapper.map` (`routes/ag_ui.py`) assigned `data["metadata"]` to a variable inferred as `dict[str, str]`. mypy reported 1 error while pytest passed 3375 tests. /sdk-test runs mypy, so the release gate was blocked.

## Root cause
The wave verified with tests only; mypy was never run over `agent_sdk/`.

## Check
Run `.venv/bin/python -m mypy agent_sdk` and confirm zero errors.

## Prevention
When planning any wave that touches `agent_sdk/routes/` or other typed code, add a done-criterion: mypy over `agent_sdk/` reports zero errors. Annotate dict literals that later gain mixed-type keys (`data: dict[str, Any]`).
