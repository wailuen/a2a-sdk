---
id: LRN-285
title: Evicting heaviest source still lets one source evict another
category: security
severity: high
source: redteam
date: 2026-10-10
---

## What happened
With a full table, `_evict_for` evicted the oldest flow of the heaviest source even for a brand-new caller. A shared office NAT IP holding 3 flows lost one to a fresh IP. The unauth rate limiter keyed on the raw IPv6 address, so a /48 attacker could mint 1,000+ sources and dodge it.

## Root cause
Eviction policy chose the heaviest other source instead of refusing the newcomer, and the rate limiter and flow store used different source keys.

## Check
Confirm a test with a victim holding 3 flows plus a fresh-source insert into a full table keeps the victim's flows. Confirm a test that rotating IPv6 addresses inside one /64 hits the 429.

## Prevention
When planning fairness quotas, require multi-flow victim tests, refuse newcomers over evicting others, and one shared source-key helper (IPv6 /64) for both limiter and store.
