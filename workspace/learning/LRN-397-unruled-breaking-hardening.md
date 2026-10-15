---
id: LRN-397
title: Hardening beyond ruled scope shipped without ruling
category: security
severity: high
source: redteam
date: 2026-10-15
---

## What happened
revoke_by_value narrowed revoke rights to admin api_key callers, changing behaviour for existing user keys on the public RFC 7009 /oauth/revoke route. The GH-182 ruling covered only service keys. The wave shipped it under CHANGELOG Changed, and the SI annotation claiming "only admin keys can do that today" was wrong.

## Root cause
The wave self-authorized a breaking change outside the ruled scope (LRN-251, LRN-308 pattern).

## Check
Verify the revoke guard is `caller.kind == "api_key" and not caller.service`, or that a ruling comment URL is cited in the CHANGELOG entry and DESIGN.md section 5.5.

## Prevention
When planning security hardening, limit changes to the ruled scope. Any behaviour change for other existing callers needs a recorded maintainer ruling URL before release; an SI annotation is not a ruling.
