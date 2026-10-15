---
id: LRN-364
title: MCP writer lacks non-finite output guard after strict serializer
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The wave added strict serialization guards to A2A and AG-UI but not MCP. A tool artifact holding NaN made POST /mcp return a bare 500. On legacy /mcp/messages, json.dumps(allow_nan=False) raised uncaught, so the SSE client never got a reply. CHANGELOG wrongly claimed a -32006 failure.

## Root cause
Strict serialization was applied per surface; MCP writers were left without a caught-and-terminal path.

## Check
Run route tests for /mcp and /mcp/messages with a BarChart.model_construct NaN artifact: expect isError result (tools/call) or a -32603 error for the id. `grep -n "allow_nan" agent_sdk/routes/mcp.py` must sit inside try/except ValueError.

## Prevention
When a wave adds a strict serializer to one protocol writer, plan the same guard plus route test for every surface, and verify CHANGELOG claims against a probe.
