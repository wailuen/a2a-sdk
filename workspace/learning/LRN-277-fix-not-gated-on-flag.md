---
id: LRN-277
title: Redteam fix to shared store not gated on feature flag
category: security
severity: high
source: redteam
date: 2026-10-09
---

## What happened
`_evict_clients_if_needed` in agent_sdk/auth/oauth_tokens.py began evicting consented clients with no live refresh family, even with AGENT_SDK_OAUTH_IDP=none. A DCR flood past MAX_CLIENTS deleted the org client from `provision-org-oauth-client`, breaking every member's connector.

## Root cause
An IdP-mode fix changed shared eviction behaviour unconditionally, and the off-mode regression file pinned response bytes but not registration/eviction behaviour.

## Check
Run the IdP-off test that registers more than MAX_CLIENTS clients and asserts a consented, token-less client survives. Grep `_evict_clients_if_needed` for a `require_user` guard.

## Prevention
When planning a change to a shared store for a feature flag, gate it on that flag. Require an off-mode regression test covering store side effects, and a CHANGELOG line for any remaining behaviour change.
