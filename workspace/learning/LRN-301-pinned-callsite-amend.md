---
id: LRN-301
title: New bridge_trailing_user caller must amend LRN-144 call-site list
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
`_final_summary` in loop.py added two callers of `bridge_trailing_user` (lines ~457 and ~487: the final_summary=False path and the notice-fallback path). LRN-144's Check allows only `bridge_context_messages` plus run_loop's own exits, so the audit failed. Per LRN-249, an unamended pinned list becomes a permanently failing audit.

## Root cause
A new helper added callers to a pinned call-site list without amending the learning that pins it.

## Check
grep -n "bridge_trailing_user" agent_sdk/agent/loop.py and confirm every hit is named in LRN-144's Check, including both `_final_summary` calls.

## Prevention
When planning a helper that calls `bridge_trailing_user`, include amending LRN-144's Check in the same change. Or keep the bridge call inside run_loop's exits.
