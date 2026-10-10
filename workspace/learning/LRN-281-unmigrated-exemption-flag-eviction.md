---
id: LRN-281
title: New exemption flag leaves pre-upgrade records evictable
category: security
severity: high
source: redteam
date: 2026-10-09
---

## What happened
GH-152 (w042) made `_evict_clients_if_needed` in `agent_sdk/auth/oauth_tokens.py` evict any consented client with no live refresh family, exempting only records with `pinned`. `pinned` is written only by provision-org-oauth-client going forward, so org clients provisioned earlier lack it. With IdP on, their legacy userless families are revoked, and ~200 anonymous `/oauth/register` calls evict the shared org client_id (probe: client returned None). Every member's connector then hits the "unknown client" 400 page.

## Root cause
An eviction rule was widened and its exemption flag was introduced without migrating or grandfathering existing records, so the upgrade itself created the victims.

## Check
Verify a test exists that boots with a pre-upgrade consented client lacking the `pinned` key, enables IdP (`require_user`), floods DCR past the eviction cap, and asserts the client still resolves. Grep: `grep -rn "pinned" agent_sdk/auth/oauth_tokens.py agent_sdk/__main__.py` and confirm a migration or default path for records with no `pinned` key.

## Prevention
When planning any new exemption/pin flag that guards records from an eviction, expiry, or cleanup rule, include a migration or grandfather step for existing records, plus an upgrade-path regression test. Record the policy change in the todo or ADR.
