---
id: LRN-394
title: Authz narrowing missing changelog, docs and per-kind tests
category: security
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The revoke_by_value change (admin-only api_key revoke) altered public POST /oauth/revoke for all non-admin keys, not just service keys. Plain user keys now get a silent no-op with HTTP 200. CHANGELOG, route docstrings (oauth.py), DESIGN.md and the todo's Modifies list did not mention it, and only service keys were tested.

## Root cause
A fix scoped to one caller kind altered a rule shared by several kinds, without updating docs or tests for the others.

## Check
Verify CHANGELOG names POST /oauth/revoke with old and new rule. Run a test that a plain user API key cannot revoke another client's token, with DISABLE_API_KEYS off and on.

## Prevention
When a fix narrows an authorization rule shared by several caller kinds, list every affected kind, document each in CHANGELOG, docstrings and DESIGN.md, add the file to Modifies, and test each kind.
