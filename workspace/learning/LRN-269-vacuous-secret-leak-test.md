---
id: LRN-269
title: Secret-leak test checks values code never saw
category: testing
severity: high
source: redteam
date: 2026-10-09
---

## What happened
test_no_idp_secrets_in_logs_or_responses read `idp.claims["id_token"]` after the last callback, which was the replay that returns 400 before token exchange. The access-token sentinel was "AT", no refresh token was planted, failure-path nonces/cookies went unchecked, and the missing-secret and token-endpoint 4xx paths were never driven.

## Root cause
Sentinels were read from shared mutable fixture state after the fact, so the test could check values the SDK never received.

## Check
In tests/test_gh152_idp_no_secret_leak.py, confirm each flow's id_token is captured inside callback(), sentinels are long unique strings (including refresh_token), and a /token 400 mode and missing-secret path are driven.

## Prevention
When planning a no-leak pin test, require sentinels captured at the point of production, one per flow, with success and every failure path driven.
