---
id: LRN-286
title: Client-IP key wiring lacks route-level test
category: testing
severity: high
source: redteam
date: 2026-10-10
---

## What happened
No test checked what source `_federate` (routes/oauth.py) passes to `flows.put`. All per-source tests called `IdpFlowStore.put` with hand-picked strings, and test_client_ip_xff.py only tested `client_ip()`. A regression passing `source=""` or reading XFF unconditionally would pass every test.

## Root cause
Store and parser were unit-tested in isolation; the route wiring between them was not.

## Check
Confirm a route test sends per_source_max+1 GET /oauth/authorize requests from one untrusted peer with different spoofed XFF values and asserts they were billed to the peer; plus a trusted-proxy mirror case.

## Prevention
When a todo adds a control keyed on client IP, require an AC for a route-level test proving the trusted-proxy-aware key reaches the control, in both trusted and untrusted peer cases.
