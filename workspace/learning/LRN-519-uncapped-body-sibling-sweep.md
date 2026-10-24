---
id: LRN-519
title: Sweep every request.body() when adding a capped-body helper
category: security
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-246 added `read_capped_body` (C-077), but `agent_sdk/routes/oauth.py` still did `raw = await request.body()` before checking `_MAX_BODY_BYTES`, in the unauthenticated POST /register route and in `_parse_form` (token and consent endpoints). Any caller could force an unbounded buffer.

## Root cause
The fix covered the reported route only. Sibling call sites, including unauthenticated ones, were not swept.

## Check
Run `grep -rn "request.body()" agent_sdk/` and confirm no match outside `agent_sdk/common/body.py`. Confirm a test streams an over-cap body to /register and the form endpoints and counts the chunks read.

## Prevention
When planning a new shared guard helper, add a todo step that greps every call site of the unsafe primitive across agent_sdk/ and migrates all of them in the same wave, unauthenticated routes first.
