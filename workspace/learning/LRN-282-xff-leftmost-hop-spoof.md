---
id: LRN-282
title: Forwarded-for parser trusts attacker-chosen leftmost hop
category: security
severity: high
source: redteam
date: 2026-10-10
---

## What happened
`client_ip()` returned the leftmost untrusted X-Forwarded-For hop. Behind a trusted proxy that appends, a caller sending `X-Forwarded-For: 6.6.6.6` was billed as 6.6.6.6, so it could mint a new source per request and bypass the per-source flow quota and unauth rate limit.

## Root cause
The XFF chain was read from the left; the leftmost entry is caller-controlled whenever a trusted proxy appends.

## Check
Run `client_ip('10.0.0.1', '6.6.6.6, 203.0.113.7', ['10.0.0.1'])` and confirm it returns `203.0.113.7`. Confirm tests/test_client_ip_xff.py covers: untrusted peer with XFF gives the peer; trusted peer with `spoof, real` gives `real`.

## Prevention
When planning any quota or rate limit keyed on client IP, require the parser to walk XFF from the RIGHT and take the first hop not in trusted_proxies, with spoofed-XFF unit tests in the todo ACs.
