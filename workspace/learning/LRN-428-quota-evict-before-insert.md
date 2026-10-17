---
id: LRN-428
title: Per-key quota must evict own entries before insert
category: security
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-201 added a 4-session per-identity cap to MCP sessions. The initialize branch inserted the new session, ran the global LRU `_prune_sessions`, and only then trimmed the caller's own oldest. With the map full, a capped identity re-initializing evicted another identity's session needlessly.

## Root cause
The per-key trim ran after the global LRU prune, so a key at its own cap grew the map and pushed out other tenants.

## Check
Verify in agent_sdk/routes/mcp.py that `_evict_identity_lru(` is called before the sessions insert and before `_prune_sessions(sessions)` in the initialize branch. Run tests/test_gh201_mcp_session_sharing.py: with `_MAX_SESSIONS` monkeypatched small, a capped identity re-initializing leaves every other identity's sessions live.

## Prevention
When planning any per-key quota beside a global LRU, order it: evict the caller's own entries (to cap-1), insert, then global prune. Add a cross-tenant survival test.
