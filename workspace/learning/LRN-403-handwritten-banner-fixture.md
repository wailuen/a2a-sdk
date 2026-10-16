---
id: LRN-403
title: Test fixture hand-copies the banner it parses
category: testing
severity: high
source: redteam
date: 2026-10-16
---

## What happened
agent-verify step 3 extracted the bootstrap token with awk, taking the first word of the first non-empty line after the banner header. The real banner (agent_sdk/auth/api_keys.py:157-163) puts "Bootstrap token (valid 15 min...):" there, so the header sent was `X-Bootstrap-Token: Bootstrap` and every later step failed with 401. The test passed because its invented log put the token directly under the header.

## Root cause
The fixture was a hand-written copy of the banner, not output of the code that prints it.

## Check
Test must call `BootstrapManager(store).arm_if_needed()` with stderr captured, use that text as the log, and assert the real token reaches curl stdin.

## Prevention
When planning a test that parses log or banner output, build the fixture from the producing code. Never hand-write it.
