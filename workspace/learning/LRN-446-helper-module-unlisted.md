---
id: LRN-446
title: Split-out helper module missing from todo scope and CHANGELOG
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
GH-216 added agent_sdk/console/static/interrupt.js and changed tests/test_card_console.py. Neither was in the todo's Creates/Modifies line, and the CHANGELOG named neither.

## Root cause
A helper was split out of chat.js during implementation and the plan and changelog were not updated. Extends LRN-322 / LRN-433.

## Check
`git status --porcelain agent_sdk tests` : every changed path must appear in the group's Creates/Modifies line and in its CHANGELOG bullet (grep the basename in both).

## Prevention
When planning, state that any module split out during implementation is new surface: update the todo Creates line and the CHANGELOG bullet in the same change.
