---
id: LRN-389
title: SI-2 no-leak test covered only one named path
category: testing
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The SI-2 annotation named mint, list, revoke and refused-request paths. `test_service_mint_logged_without_plaintext` covered only mint. Nothing captured caplog around list, revoke, a 401 with DISABLE_API_KEYS, or a 403 on /admin/api/*, and nothing compared service-key and user-key refusal bodies. Same root cause as LRN-292, LRN-340, LRN-369.

## Root cause
Tests were written for the path that changed, not for every path the annotation listed.

## Check
In tests/test_gh182_service_key.py, confirm one DEBUG caplog test covers all four paths, asserts the plaintext is absent from caplog.text and every body, and that service-key refusal bodies and WWW-Authenticate equal user-key ones.

## Prevention
An SI-2 annotation that names paths needs one caplog assertion per named path. Planner: list each path as its own AC.
