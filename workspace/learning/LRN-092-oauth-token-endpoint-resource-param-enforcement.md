---
id: LRN-092
title: OAuth token endpoint does not enforce RFC 8707 resource param
category: protocol
severity: high
source: protocol-audit
date: 2026-06-15
---

## What happened
The MCP OAuth implementation (oauth.py) accepts token requests that omit the `resource` parameter, contradicting the RFC 8707 §2 MUST that clients send `resource` at both the authorization and token endpoints. A code comment explicitly documents this as intentional — audience is bound at the authorization step and persisted in code metadata, so the token endpoint reads audience from metadata rather than from the inbound `resource` param. Claude.ai is confirmed to omit `resource` at the token endpoint, making this a practical non-issue for that surface.

## Root cause
The server satisfies the three-part binding (validate-at-issue, persist-in-metadata, check-at-use) but skips the redundant inbound check at the token endpoint. A token request carrying a mismatched `resource` param would be silently ignored rather than rejected with `invalid_target`.

## Check
grep -n "resource" src/agent_sdk/contrib/mcp/oauth.py | grep -i "token" — confirm no `store.validate_audience` call appears inside the token-request handler for the inbound `resource` form field. Also verify no test exercises a mismatched resource-at-token-endpoint rejection.

## Prevention
When planning OAuth 2.1 / MCP token endpoint work, ensure that if a `resource` param is present in the token request body and non-empty, the server calls audience validation against code metadata and returns `invalid_target` on mismatch — even when audience is already bound via code metadata. This closes the RFC 8707 strict-conformance gap without breaking the existing implicit path.
