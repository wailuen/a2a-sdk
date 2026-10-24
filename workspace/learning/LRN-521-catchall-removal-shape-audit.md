---
id: LRN-521
title: List absorbed message shapes before removing a catch-all
category: protocol
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-246 removed the `message.get("id") is None -> 202` fallback in `agent_sdk/routes/mcp.py`. A client's JSON-RPC error response with `id: null` or no id was then treated as a request. It got HTTP 200 with a -32600 body on POST /mcp and a queued reply on /mcp/messages. MCP 2025-06-18 requires 202 with an empty body for a POSTed response.

## Root cause
`_is_jsonrpc_response` required a non-null id, and the removed fallback had been the only thing absorbing null-id and id-less responses.

## Check
Run tests/test_gh246_mcp_route.py and confirm tests post `{"jsonrpc":"2.0","id":null,"error":{...}}` and an id-less error to /mcp, get 202 with an empty body, and leave the /mcp/messages queue empty.

## Prevention
When planning removal of a catch-all fallback, first list every message shape it absorbed (null-id and id-less errors included) and pin each with a test. Classify responses as no `method` plus `result` or `error`, whatever the id.
