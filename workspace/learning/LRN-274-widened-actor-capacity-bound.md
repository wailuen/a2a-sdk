---
id: LRN-274
title: Widened actor invalidates capacity-bound assumptions
category: security
severity: high
source: redteam
date: 2026-10-09
---

## What happened
Under AGENT_SDK_OAUTH_IDP=oidc, every IdP consent calls `mark_consented`, making each DCR client non-evictable. With MAX_CLIENTS=200 (oauth_tokens.py:57), the 201st `register_client` raises AgentError. Any assigned tenant user, or an org with over 200 users, can fill the table; no new connector can register until rows are deleted by hand.

## Root cause
Consent moved from admin-only to any tenant user, but the "operationally near-impossible at 200" assumption was never re-checked.

## Check
Run a test that creates MAX_CLIENTS consented clients under IdP and asserts a new `register_client` still succeeds. Add a test that one signed-in user cannot fill the table.

## Prevention
When planning a feature that widens who can perform a state-changing action, list every capacity bound and "impossible" comment keyed to that action. Require eviction of consented clients with no live refresh family, or a per-user cap.
