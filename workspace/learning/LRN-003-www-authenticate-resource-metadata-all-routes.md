---
id: LRN-003
title: WWW-Authenticate must include resource_metadata on ALL protected routes
category: protocol
severity: medium
source: redteam
date: 2026-06-14
---

## What happened

GH #7 — the auth middleware emitted `Bearer resource_metadata="..."` only for /mcp paths. All other protected routes (A2A, AG-UI, admin) returned bare `Bearer realm="agent"`. OAuth discovery clients (including Claude.ai) use `resource_metadata` as the RFC 9728 entry point; the bare form breaks non-MCP OAuth flows.

## Root cause

The `_unauthorized()` function in auth/middleware.py had a path check (`if request.url.path == "/mcp"`) that created inconsistent challenge headers across surfaces.

## Check

`grep -n "realm\|resource_metadata" agent_sdk/auth/middleware.py` — must not see conditional logic that emits `realm` on some paths. All 401s must use `resource_metadata`.

## Prevention

When planning any change to auth middleware or adding new protected routes, ensure the 401 challenge uses `resource_metadata` uniformly. The `realm` form is deprecated for this SDK.
