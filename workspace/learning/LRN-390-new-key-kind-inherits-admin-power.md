---
id: LRN-390
title: New key kind inherits operator power via kind check
category: security
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`revoke_by_value` in oauth_tokens.py lets any `kind == "api_key"` caller revoke any user's OAuth token family, and /oauth/revoke skips the DISABLE_API_KEYS check. A narrow service key kept in CI could sign out every person in the tenant. ADR a003 D3 calls the route an admin-only kill-switch. The SI-5 annotation named it, but no AC or test exists.

## Root cause
Code branches on `kind == "api_key"` without also checking `admin`, so a new non-admin kind gets operator powers.

## Check
grep -n 'kind == "api_key"' agent_sdk/ and confirm each cross-owner decision also requires `.admin`. Test: a service key POSTs /oauth/revoke with another client's token, gets 200, and the token still verifies.

## Prevention
When adding a non-admin key kind, planner must list every `kind == "api_key"` branch and give each an AC and test; record any wider policy in the ADR and CHANGELOG.
