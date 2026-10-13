---
id: LRN-341
title: Failed LRN Check keeps severity; MCP catch-all still logs exception
category: security
severity: critical
source: redteam
date: 2026-10-13
---

## What happened
The JSON-RPC _dispatch catch-all in agent_sdk/routes/mcp.py still called logger.exception, around _handle_tools_call result rendering. A pydantic ValidationError carrying input_value=<tool output> would be logged. Unit rounds deferred it as medium.

## Root cause
The code predated the wave, so unit rounds downgraded a failed LRN-214 Check, which must inherit the LRN's critical severity.

## Check
grep -n "logger.exception" agent_sdk/routes/mcp.py and confirm no match. Verify a test makes rendering raise a ValidationError with a marker input value via /mcp tools/call and leaves the marker out of caplog.

## Prevention
When planning, ensure a failed LRN Check keeps that LRN's severity even for pre-existing code. Add the file to the todo Modifies line and a CHANGELOG Security entry. Never defer it as medium.
