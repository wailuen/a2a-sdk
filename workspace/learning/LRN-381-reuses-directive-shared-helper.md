---
id: LRN-381
title: Reuses directive means the named shared helper, not a private one
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The Reuses C-007 note asked for a shared dumps_strict beside loads_strict in common/json_strict.py, used by A2A, sse.py and mcp.py. A private _strict_json_response in a2a.py was built instead, relying on Starlette JSONResponse calling json.dumps(allow_nan=False). sse.py and mcp.py kept inline dumps.

## Root cause
The helper relied on a framework default and ignored the named landing module.

## Check
grep -rn "allow_nan=False" agent_sdk/ and confirm the only match is in agent_sdk/common/json_strict.py; confirm a unit test for dumps_strict exists.

## Prevention
When planning, treat a Reuses note that names a landing module as an AC. Forbid guards that depend on a framework default; require explicit serialization via the shared helper (LRN-344).
