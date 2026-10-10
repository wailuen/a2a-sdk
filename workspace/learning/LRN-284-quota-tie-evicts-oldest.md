---
id: LRN-284
title: Per-source quota ties evict oldest and ignore IPv6 prefix
category: security
severity: high
source: redteam
date: 2026-10-10
---

## What happened
`IdpFlowStore._evict_for` evicted from the source with the most flows; on a tie `max()` picked the oldest source, the legitimate user. One attacker with an IPv6 /64 sent 1,000 single-flow requests from distinct addresses and the victim's flow was evicted (`pop(victim)` returned None).

## Root cause
Sources were raw IPs (no IPv6 prefix grouping), and ties broke toward the oldest source.

## Check
Run a test where 1,000 distinct sources (and a second one with IPv6 from one /64) fill the table after a victim's flow; assert the victim's flow still completes. Grep `_evict_for` for tie handling that favors the oldest.

## Prevention
When planning a per-source quota, require IPv6 grouping by /64, expired-flow purge before counting, and refusal of the newcomer rather than evicting a source holding few flows.
