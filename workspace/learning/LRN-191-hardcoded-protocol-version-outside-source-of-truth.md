---
id: LRN-191
title: Hardcoded MCP protocol-version literal drifts from the real source of truth
category: protocol
severity: high
source: protocol-audit
date: 2026-09-03
---

## What happened
admin.py's `/admin/api/selfcheck-info` hardcodes
`"mcp_protocol_version": "2025-06-18"` instead of reading
`routes/mcp.py`'s `SUPPORTED_PROTOCOL_VERSIONS[0]`. A later change added
`"2025-11-25"` and gated `serverInfo.title` behind it, but admin.py's
constant was never updated, so the self-check UI always negotiates the old
version and never probes the gated field.

## Root cause
The protocol-version string was duplicated outside its single source of
truth (`routes/mcp.py`), so it silently went stale when that source changed
— the same drift class as LRN-118, but in runtime code, not docs.

## Check
`grep -rn '"20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]"' agent_sdk/routes/admin.py`
and confirm any MCP/A2A version-string literal outside `models/a2a.py` and
`routes/mcp.py` instead imports and reads
`mcp.SUPPORTED_PROTOCOL_VERSIONS[0]`. Add a test asserting
`selfcheck_info()['mcp_protocol_version'] == SUPPORTED_PROTOCOL_VERSIONS[0]`.

## Prevention
When planning any surface that reports a protocol version (self-check,
diagnostics, docs), require it to import the value from its single source of
truth (`routes/mcp.py` for MCP) rather than a literal, and flag any new
hardcoded date-shaped version string outside that module in review.
