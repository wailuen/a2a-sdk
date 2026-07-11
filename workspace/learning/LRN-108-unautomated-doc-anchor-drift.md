---
id: LRN-108
title: Unautomated documentation anchors drift silently
category: testing
severity: high
source: redteam
date: 2026-07-10
---

## What happened
RT-003 found GH-98 added `TOOL_PROGRESS` to `CUSTOM_EVENTS`, `_CUSTOM_EVENT_SCHEMAS`,
and `chat.js` `handleCustom()` — all three pytest-enforced anchors — but left the
DESIGN.md §5.3 frozen-contract table listing only the original 4 events.

## Root cause
LRN-102 added pytest parity guards for the three code-level anchors but explicitly
left the DESIGN.md table as a manual-only cross-check (no test covers it). An anchor
with no automated gate drifts the moment a new event is added, even when the other
anchors stay in sync.

## Check
`grep -oP '^\|\s*[A-Z_]+\s*\|' DESIGN.md` (§5.3 table rows) must list every name in
`CUSTOM_EVENTS` (agent_sdk/routes/agent_card.py). Since no pytest enforces this, the
redteam pass must run this diff by hand each time `CUSTOM_EVENTS` changes.

## Prevention
When planning a change to a multi-anchor frozen contract, do not trust existing
parity tests alone — check whether any prior learning (e.g. LRN-102) flagged an
anchor as "no automated check," and if so add an explicit todo/redteam step to
manually diff that anchor against the code in the same commit.
