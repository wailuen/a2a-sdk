---
id: LRN-093
title: AG-UI route missing Content-Type enforcement unlike A2A and MCP
category: protocol
severity: high
source: protocol-audit
date: 2026-06-15
---

## What happened
AG-UI POST `/ag-ui/run` (`agent_sdk/routes/ag_ui.py`) accepts any Content-Type and silently attempts JSON parse, emitting an opaque `RUN_ERROR` stream event on failure. A2A (`_parse_send`, line 115) and MCP (`mcp_post`, line 443) both reject non-`application/json` bodies with HTTP 415 before any processing begins. A browser client sending the wrong media type receives no corrective HTTP signal and instead sees a failed stream.

## Root cause
The AG-UI route was implemented without mirroring the Content-Type guard present in the other two protocol surfaces, leaving a seam gap in input validation uniformity.

## Check
`grep -n "415\|content.type\|Content.Type\|media_type" agent_sdk/routes/ag_ui.py` — confirm at least one match guards the entry point of `ag_ui_run()` before any `json.loads` call. Absence of a 415 return path is a failure.

## Prevention
When planning any new or modified protocol surface (A2A / AG-UI / MCP), ensure the route entry point validates `Content-Type: application/json` and returns HTTP 415 before attempting body parsing. Cross-check all three surfaces together; a guard present on two but absent on the third is a seam violation.
