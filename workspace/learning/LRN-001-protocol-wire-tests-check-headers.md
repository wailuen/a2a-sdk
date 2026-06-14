---
id: LRN-001
title: Protocol wire tests must verify HTTP headers, not just response bodies
category: testing
severity: high
source: redteam
date: 2026-06-14
---

## What happened

4 of the 5 GH #4–#8 protocol bugs were about wrong or missing HTTP response headers (Mcp-Protocol-Version, WWW-Authenticate, Access-Control-Expose-Headers, customEvents schema in agent card). None were caught by the SDK test suite because all existing tests check response body / internal logic only.

## Root cause

No test layer exercises the HTTP wire format (status lines, response headers, header values) for SDK protocol routes.

## Check

`grep -rn "response.headers\|assert.*headers" tests/` — if this returns nothing or very few results relative to protocol routes, the wire layer is untested.

## Prevention

When planning any wave that touches a protocol route (cors.py, auth/middleware.py, routes/mcp.py, routes/agent_card.py, routes/a2a.py, routes/ag_ui.py), add a todo item for a TestClient-level test that checks the HTTP response headers, not just the response body.
