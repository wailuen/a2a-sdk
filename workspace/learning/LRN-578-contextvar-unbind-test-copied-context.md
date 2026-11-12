---
id: LRN-578
title: Contextvar unbind tests must run inside the request context
category: testing
severity: high
source: redteam
date: 2026-11-10
---

## What happened
GH-276 "nothing stays bound" tests (`_nothing_bound()` in tests/test_gh185_current_identity.py) still passed when `admin_mod.unbind_identity` and `forwarding.unbind` were patched to no-ops, i.e. with the new `finally` deleted.

## Root cause
httpx ASGITransport runs the app in a copied context, so reads of contextvars from the test task never see a leak. The second request sent no header, so it bound `{}` and read None regardless.

## Check
Verify that each unbind test fails when the `finally` body is removed: spy on `bind_identity`/`unbind_identity`/`forwarding.bind`/`forwarding.unbind` and assert every bound token is unbound once on success, AgentError, timeout and validation exits; or probe `current_identity()` from a post-finally hook (`admin_mod._safe_result`).

## Prevention
When planning a contextvar bind/unbind fix, require the test to observe from inside the request's own context (spy or post-finally hook), never from the test task, and require a mutation check that the assert fails with the unbind removed.
