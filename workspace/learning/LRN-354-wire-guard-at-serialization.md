---
id: LRN-354
title: Wire validity enforced only in validators, not at serialization
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-173 coerced NaN only in pydantic validators. `build_artifact`'s guard `json.dumps(artifact.wire(), ensure_ascii=False)` still allowed NaN, so a field mutated after construction, `model_construct()`, or a tool returning plain `float('nan')` streamed `"value":NaN` (invalid JSON) on A2A.

## Root cause
No enforcement at the one serialization point every artifact passes through; validators are bypassable.

## Check
grep `json.dumps` in agent_sdk/agent/runner.py, agent_sdk/common/sse.py and agent_sdk/routes/mcp.py and confirm `allow_nan=False`. Confirm a test assigns nan post-construction and asserts no `NaN` in the SSE frame.

## Prevention
When planning a wire-validity fix, require it at the serialization point (`allow_nan=False`) as well as in model validators, with tests for post-construction mutation and plain scalar returns.
