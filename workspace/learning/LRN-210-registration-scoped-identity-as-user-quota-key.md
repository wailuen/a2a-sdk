---
id: LRN-210
title: Registration-scoped identity used as per-user quota key
category: security
severity: critical
source: redteam
date: 2026-08-19
---

## What happened
`agent_sdk/routes/mcp.py` capped concurrent GET /mcp streams per caller using
`_identity_key(identity)` with a low fixed bound (8). Under the SDK's own
documented org-wide OAuth client mode (`provision-org-oauth-client`) or a
shared API key, every caller in the org collapses onto one `_identity_key()`
value, so the cap silently became a per-ORG cap: the 9th connector in the org
got 429 and could never establish an MCP connection.

## Root cause
`Identity.subject` is the OAuth client_id (`oauth_tokens.py`) or API-key id
(`api_keys.py`) — a registration, never an end user. Treating it as a
per-user quota key ignores that many real end users can share one
registration by design.

## Check
`grep -n "_MAX_GET_STREAMS_PER_IDENTITY" agent_sdk/routes/mcp.py` — confirm
the default is not a single-digit value, that `AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`
(config.py) is a real override reachable without a code change, and that a
test exists asserting N distinct connections sharing one `client_id`/API key
all admit up to that raised bound.

## Prevention
When planning any per-caller rate/concurrency limit keyed on `Identity.subject`
or `_identity_key()`/`identity_key()`, treat it as a per-REGISTRATION limit,
not per-end-user — size defaults assuming org-wide OAuth client or shared
API-key deployment (many users, one identity value), and require an
`AGENT_SDK_*` settings override plus a multi-connection-per-identity test in
the same todo.
