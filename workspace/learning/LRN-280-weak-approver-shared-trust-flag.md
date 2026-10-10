---
id: LRN-280
title: Weaker approver writes trust flag read by stronger path
category: security
severity: high
source: redteam
date: 2026-10-09
---

## What happened
POST /oauth/idp/consent (agent_sdk/routes/oauth.py) called `store.mark_consented()`, setting the same `consented` flag the admin path sets. With IdP later switched to none and AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true, every client an Entra user had allowed was issued codes with no admin approval.

## Root cause
A new, weaker approver (any signed-in user) reused the trust bit that a stronger path's shortcut reads as "admin approved".

## Check
Test: consent under IdP, rebuild app with idp=none and one_time_consent=true, and assert GET /oauth/authorize renders the admin-key page. Grep `mark_consented` in routes/oauth.py for callers outside admin approve and provision-org.

## Prevention
When planning a new approval path, give it its own flag (e.g. `idp_consented_at`). Never reuse a flag that a stronger mode's shortcut trusts, so a later mode switch cannot promote its approvals.
