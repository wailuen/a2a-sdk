---
id: LRN-479
title: Unfixed caplog empty-capture in GH-205 skill leak tests
category: testing
severity: high
source: redteam
date: 2026-10-23
---

## What happened
Repeat of LRN-478. The GH-205 SI-2 skill-name leak checks (tests/test_gh205_mcp_skills.py lines 243 and 253) pass vacuously: configure_logging() (agent_sdk/observability/logging.py:46) turns off agent_sdk propagation on first build. A probe warning left MARKER out of caplog.text. It is still open in workspace/todos/deferred/w062-group-G1-budget-exhausted.md.

## Root cause
Same as LRN-478; the fix was deferred when the wave budget ran out.

## Check
Probe test: `logging.getLogger('agent_sdk.routes.mcp').warning('leak %s', MARKER)` after build_app() must appear in the captured text. grep the test file for `sdk_caplog('agent_sdk.routes.mcp'`.

## Prevention
When planning, treat budget-deferred high testing gaps as release blockers; schedule the sdk_caplog fix for lines 243 and 253 first in the next wave.
