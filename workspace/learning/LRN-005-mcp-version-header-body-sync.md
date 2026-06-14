---
id: LRN-005
title: MCP Mcp-Protocol-Version response header must match negotiated body version on initialize
category: protocol
severity: high
source: redteam
date: 2026-06-14
---

## What happened

GH #4 — on the first `initialize` RPC call, the client sends no `MCP-Protocol-Version` request header. The server's `_negotiated_version()` fell back to the default `"2025-03-26"`, which was locked into `base_headers` before dispatch. `_handle_initialize` correctly negotiated `"2025-06-18"` in the body. Header and body contradicted each other.

## Root cause

Version negotiation happened in two places: `_negotiated_version()` (reads request header) and `_handle_initialize()` (reads params body). On first contact the header path gets the default; the params path gets the correct version. The result was never unified before building the response.

## Check

POST to /mcp with `{"method":"initialize","params":{"protocolVersion":"2025-06-18",...}}` and NO `Mcp-Protocol-Version` request header. Response header `mcp-protocol-version` must equal `"2025-06-18"`, not `"2025-03-26"`.

## Prevention

After any change to `_handle_initialize` or `_negotiated_version`, add or run the test that verifies header == body for the negotiate-up case (client version > server default).
