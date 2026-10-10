---
id: LRN-288
title: Docs and ADR describe eviction/refusal policy the code no longer has
category: security
severity: high
source: redteam
date: 2026-10-10
---

## What happened
docs/security.md and ADR-003 D4 said a full flow table evicts the largest holder's oldest flow with "no refusal path". The code (`IdpFlowStore._evict_for`) refuses a new source with `IdpUnavailable`, surfacing as `temporarily_unavailable`. Operators were not told that ~20 IPs can lock out new sign-ins until flow TTL.

## Root cause
Design prose from an earlier iteration was not re-checked against the final code branch; tests passed so the drift went unnoticed.

## Check
Verify that `docs/security.md` and `workspace/adr/a003-oauth-idp-sign-in.md` mention `temporarily_unavailable` and the lockout residual risk. `grep -n "No refusal path" workspace/adr/a003-oauth-idp-sign-in.md` must return no match.

## Prevention
When a todo changes an eviction, quota or refusal policy, add an acceptance criterion to compare every docs/ and ADR sentence about it with the final code branches, including the over-limit caller's visible result.
