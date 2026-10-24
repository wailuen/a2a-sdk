---
id: LRN-474
title: Strict schema drops required but validator still demands it
category: protocol
severity: high
source: redteam
date: 2026-10-23
---

## What happened
Strict mode (agent_sdk/common/schema.py:85) removed every anyOf-null property from `required`, including nullable fields with no default (`query: str | None`). A client omitting the key, as the schema allows, got ToolInputValidationError. docs/deployment.md:110 claimed otherwise; the test always passed the key.

## Root cause
The schema rewrite was not checked against what pydantic actually accepts.

## Check
Run a test calling a tool with `x: Optional[int]` (no default) over MCP in strict mode, key omitted, and expect success.

## Prevention
When planning a schema rewrite that loosens `required`, add a test per field shape (default, no default) proving the validator accepts the advertised inputs.
