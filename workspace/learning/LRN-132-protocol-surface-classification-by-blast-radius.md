---
id: LRN-132
title: Protocol surface classification must follow code sharing, not directory naming
category: protocol
severity: high
source: protocol-audit
date: 2026-07-20
---

## What happened
`.claude/workflows/sdk-wave.js` classifies `agent_sdk/routes/oauth.py` as MCP-only (`MCP_SURFACE`), so waves touching it never trigger `runA2A`/`runAGUI` and only mcp-advisor runs. But `oauth.py`'s `OAuthTokenStore.verify` backs `require_identity` for every protected A2A and AG-UI route too, and its own docstrings state the bare PRM `resource` serves `/v1/` and `/ag-ui/` as well as MCP.

## Root cause
Surface classification was derived from the file's directory/module name (`routes/oauth.py` "looks" MCP-specific) instead of from its actual runtime consumers, which span all three transports.

## Check
`grep -n "MCP_SURFACE\|A2A_SURFACE\|AGUI_SURFACE" .claude/workflows/sdk-wave.js` — confirm `agent_sdk/routes/oauth.py` (or a shared `AUTH_SURFACE` folded into all three) appears in all three protocol arrays. Also confirm `tests/test_workflows.py` asserts this membership: `test_lrn132_oauth_present_in_all_three_protocol_surfaces` locks oauth's membership across `A2A_SURFACE`/`MCP_SURFACE`/`AGUI_SURFACE`, and `test_rt001_middleware_present_in_all_three_protocol_surfaces` locks the same for the shared auth middleware.

## Prevention
When planning wave-audit tooling or protocol-surface arrays, classify a file by tracing its actual runtime consumers (grep call sites / Depends() usage) across all protocols before assigning it to a single-protocol list; shared auth/middleware files must be added to every protocol surface they gate, with a regression test locking the membership.
