---
id: LRN-386
title: Remote card values copied into requests without caps or fixed source
category: security
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`loadCatalogIds()` in `agent_sdk/console/static/chat.js` kept every string from `params.supportedCatalogIds` with no count or length cap. It also fetched the agent card from the user-editable `state.base`, so any origin could push an unbounded catalogs array into A2A metadata and AG-UI forwardedProps.

## Root cause
A type filter was treated as enough validation for an untrusted remote value, and the fetch source was not pinned to same-origin.

## Check
In `chat.js`, grep `agent-card.json` and confirm the fetch uses the relative path `/.well-known/agent-card.json`, not `${state.base}`. Confirm `loadCatalogIds` applies `.slice(0, 32)` and a length check (<= 256), and always includes `urn:a2ui-profile:standard:v1`.

## Prevention
When planning code that copies a value from a remote document into an outbound request, require a fixed same-origin source plus explicit count and length caps, and a safe default when nothing valid remains. Write these as SI lines in the todo.
