---
id: LRN-272
title: New consent path skips client-lifecycle side effects
category: security
severity: high
source: redteam
date: 2026-10-09
---

## What happened
POST /oauth/idp/consent (`oauth_idp_consent` in agent_sdk/routes/oauth.py) minted a code without calling `store.mark_consented(client_id)`, unlike the admin approve path. IdP-used clients stayed "never consented", so DCR floods (cap 200, oldest-first eviction) could evict a live connector in about 7 minutes. Probe: with MAX_CLIENTS=5, 6 junk registrations deleted the live client.

## Root cause
A new code-minting route was written without copying the lifecycle side effects of the original consent path.

## Check
`grep -n "mint_code\|mark_consented" agent_sdk/routes/oauth.py` and confirm every `mint_code` call site has a matching `mark_consented`. Run the tests `test_idp_consent_marks_client_consented` and the MAX_CLIENTS+1 junk-registration test.

## Prevention
When planning any new consent or code-minting route, list the side effects of the existing path (mark_consented, audit, revocation hooks) and require parity tests. Include a DCR-flood eviction test.
