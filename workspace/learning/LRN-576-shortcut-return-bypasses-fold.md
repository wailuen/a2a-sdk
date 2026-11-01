---
id: LRN-576
title: Tool-call shortcut return path bypasses outputSchema fold helper
category: protocol
severity: high
source: redteam
date: 2026-11-01
---

## What happened
With no resume_handler, an accepted elicitation returned `isError: false` with text only and skipped `_finish_tool_result`. For a tool declaring `emits` (outputSchema advertised), this is a success without structuredContent, which MCP 2025-06-18 forbids (see LRN-469).

## Root cause
A second return path in agent_sdk/routes/mcp.py (the `dumps_strict(content)` branch) was added beside the normal path and did not reuse the single enforcing helper.

## Check
Verify a test: tool with `emits` raises ToolInterrupt, no handler, user accepts; result has schema-valid structuredContent or isError:true. Grep `dumps_strict(content)` in agent_sdk/routes/mcp.py and confirm emits tools route via `_finish_tool_result`.

## Prevention
When planning any new tools/call return path (resume, elicitation, cache, shortcut), require it to call `_finish_tool_result` for tools with emits, with a test per path.
