---
id: LRN-330
title: Superseded exemption test not inverted with ruling
category: security
severity: critical
source: redteam
date: 2026-10-13
---

## What happened
GH-161 ruling (every oidc issuer needs role/group/opt-out) was not in the tree. `_validate_idp_settings` still exempted GUID-pinned Entra issuers, and `test_entra_guid_issuer_boots_without_gate_or_warning` still asserted the old behavior (SI-5).

## Root cause
The test pinning the superseded exemption was not inverted in the same change, so it kept the less safe behavior locked in.

## Check
Run `pytest tests/test_gh152_idp_settings_boot.py`; confirm an Entra GUID issuer with no gate fails boot, and `grep -n "tenant_id is None" agent_sdk/app.py` has no match in the validator.

## Prevention
When a ruling removes an exemption, plan the inversion of the test asserting it, plus the ADR, docs, setup skill and CHANGELOG Breaking/Migration entry, in the same group.
