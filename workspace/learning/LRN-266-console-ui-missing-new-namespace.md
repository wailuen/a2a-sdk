---
id: LRN-266
title: New credential namespace not rendered in admin console
category: sdk
severity: high
source: redteam
date: 2026-10-09
---

## What happened
GET /admin/api/credentials gained an `oauth_idp` card, and the boot warning, ADR-003 D7 and GH-152-E docs told operators to set the secret at /admin -> Credentials. The console page only rendered `data.sources` and `data.bedrock`, so operators had no field to enter it and /oauth/authorize stayed `temporarily_unavailable`.

## Root cause
The wave changed the JSON API and operator messages but never the console.js renderer; "done" was judged on the API response.

## Check
grep -n "oauth_idp" agent_sdk/console/static/console.js must match inside `renderCredentials`; a console test must assert the card renders.

## Prevention
When planning a reserved credential namespace or any operator message that points at a console page, list console.js (and a render test) in the todo's Modifies, or reword the message to name the exact API call.
