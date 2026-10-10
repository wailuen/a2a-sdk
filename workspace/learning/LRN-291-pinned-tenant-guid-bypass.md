---
id: LRN-291
title: Pinned-tenant check misses multi-user tenant GUIDs
category: security
severity: high
source: redteam
date: 2026-10-10
---

## What happened
The GH-152 fail-closed gate treated any GUID-pinned Entra issuer as safe. `parse_idp_issuer` rejected the `consumers` alias but accepted its GUID `9188040d-6c67-4c5b-b112-36a304b66dad`, so the agent booted with no warning and admitted any personal Microsoft account.

## Root cause
The tenant validation blocked text aliases only, not the well-known public-population tenant GUID those aliases resolve to.

## Check
Run `grep -n "9188040d-6c67-4c5b-b112-36a304b66dad" agent_sdk/config.py tests/test_gh152_idp_settings_boot.py` and confirm matches in both: the refusal in `parse_idp_issuer` and the `test_boot_refuses_multi_tenant_issuer_aliases` parametrize list.

## Prevention
When planning any "pinned tenant/issuer is safe" gate, require refusal of both aliases and their resolved GUIDs inside the central parser (C-026), not in app.py. Add a test case per GUID and document the exclusion in docs/security.md.
