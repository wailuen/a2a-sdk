---
id: LRN-337
title: New cap setting needs a route-level wiring test
category: testing
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-168 made the AG-UI history cap a setting (`agui_max_message_chars`). Tests covered settings parsing and `_fold_history` with an explicit argument, but none drove `/ag-ui/run`. The helper default (32000) equals the settings default, so deleting the route argument at `ag_ui.py:687-690` left all tests green.

## Root cause
The helper kept a default equal to the setting default, so broken wiring was invisible; same trap as LRN-304.

## Check
Verify a test builds the app with `AGENT_SDK_AGUI_MAX_MESSAGE_CHARS=1000`, POSTs `/ag-ui/run` with a 5000-char history message, and asserts the captured model input is at most 1000 chars. Confirm `_fold_history` has no default for `max_chars`.

## Prevention
When a setting replaces a hard-coded cap, plan a through-the-route test with a non-default value, and make the helper parameter required so a missing argument fails loudly.
