---
id: LRN-329
title: Wave group closed with failing AC tests (source change lost)
category: testing
severity: critical
source: redteam
date: 2026-10-13
---

## What happened
GH-160 (`hide_input_in_errors=True` in `BaseAgentSettings.model_config`) was missing from the final tree. Untracked `tests/test_config.py` failed 3/3 and a model_validator error still printed `MASTER_KEY` input values (SI-2).

## Root cause
The group was marked done without running its AC test files against the final tree; the tracked source hunk was lost while the untracked test survived.

## Check
Run `pytest tests/test_config.py` and confirm it passes; `grep -n hide_input_in_errors agent_sdk/config.py` must match.

## Prevention
When planning a wave group, add a gate: every AC test file in the group scope must pass in the final tree. An untracked test failing against a tracked source means the source change was lost.
