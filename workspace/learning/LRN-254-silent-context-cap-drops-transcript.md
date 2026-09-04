---
id: LRN-254
title: Context-message cap silently drops entire transcript instead of truncating
category: protocol
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`MAX_CONTEXT_MESSAGES=50` silently disables A2A §3 `contextId` continuation once a
task produces more than ~50 messages after its seed turn. `_turn_boundary_slice`
returns `[]` when the trailing cap-sized window contains no plain user turn, and
`context_messages` returns that empty list with no log line and no fallback — the
whole prior transcript is dropped, not truncated. Verified: `max_turns=24` carries
50 messages, `max_turns=25` carries 0.

## Root cause
The cap was added with no coupling check against `AGENT_SDK_MAX_TURNS` (default 20,
operator-configurable), so a task emitting `2*max_turns+2` messages can exceed the
cap and silently lose all context; the cap is undocumented outside the store
docstring.

## Check
`grep -n "MAX_CONTEXT_MESSAGES\|_turn_boundary_slice" agent_sdk/tasks/memory.py` —
confirm a WARNING log fires when the slice returns `[]`, and a regression test
exists at `max_turns=25` asserting non-empty context (not silent total loss).

## Prevention
When planning any fixed-size cap on conversation/context history, require it be
checked against the loop's own turn-count knob at app-build time (or documented in
DESIGN.md + docs/deployment.md), and require the degenerate case to log a warning
rather than silently return empty.
