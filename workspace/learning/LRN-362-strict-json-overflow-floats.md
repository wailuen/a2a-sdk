---
id: LRN-362
title: Strict JSON parser misses overflowing floats (1e999)
category: security
severity: high
source: redteam
date: 2026-10-15
---

## What happened
loads_strict blocked NaN/Infinity literals via parse_constant, but 1e999 still parsed to inf. A2A message:send metadata and MCP id with 1e999 caused HTTP 500; AG-UI state crashed the SSE stream. The CHANGELOG claim of full rejection was false.

## Root cause
Only parse_constant was hooked; parse_float turns overflowing numbers into inf unchecked.

## Check
Run `grep -n parse_float agent_sdk/common/json_strict.py` (must match) and tests in tests/test_gh173_non_finite_values.py with 1e999 and -1e400 for A2A send/stream, MCP, AG-UI and oauth/register.

## Prevention
When planning strict-JSON ingress, require both parse_constant and parse_float finiteness checks, and parametrize tests with overflow numbers as well as bare literals on every surface.
