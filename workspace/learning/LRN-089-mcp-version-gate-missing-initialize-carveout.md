---
id: LRN-089
title: MCP version gate missing initialize carve-out in legacy handler
category: protocol
severity: high
source: redteam
date: 2026-06-15
---

## What happened
GH-77 broadened the MCP-Protocol-Version 400 rule across MCP handlers, but the fix was applied only to the Streamable HTTP path (`mcp_post`). The legacy POST `/mcp/messages` handler (`mcp_messages`) received the same version gate without the `is_initialize` bypass, and the gate runs before the request body is parsed, so a legacy HTTP+SSE client's `initialize` request (which carries no version header on first contact) is rejected with 400 before the handshake can complete.

## Root cause
The `is_initialize` carve-out was not replicated to every dispatch entry point when the version enforcement was tightened, and the version check was placed before body parsing in the legacy handler, making it impossible to detect `initialize` at the gate.

## Check
`grep -n "is_initialize" agent_sdk/routes/mcp.py` — confirm at least one match falls inside the `mcp_messages` function body (lines 678-720). Also verify a regression test exists: `grep -rn "mcp/messages.*initialize\|initialize.*mcp/messages" tests/` returns a hit that asserts a 202 response with no `MCP-Protocol-Version` header.

## Prevention
When planning any tightening of MCP-Protocol-Version enforcement, ensure the `is_initialize` bypass is applied to EVERY handler that dispatches MCP requests (both `/mcp` and legacy `/mcp/messages`), and enforce that body parsing precedes the version gate in each handler so `initialize` can be detected before rejection.
