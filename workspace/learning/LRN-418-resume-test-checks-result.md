---
id: LRN-418
title: Resume tests must assert the handler's result
category: testing
severity: high
source: redteam
date: 2026-10-17
---

## What happened
The GH-195 test resumed `publish_note` with `payload={"decision": "approved"}`. The example `confirmed()` handler reads only `status` / `payload.status`, so it returned `{"published": false}`. The test still passed because it checked only `tool_done` and scripted fake-model text. The docs/testing.md example showed the same ignored payload.

## Root cause
The test asserted that a tool result frame arrived, not what `resume_handler` returned.

## Check
In `tests/test_gh195_chatdriver_agui_resume.py`, grep for an assertion on `"published": true` (or a `tool_result` emit). Resume must use a payload matching the interrupt's `responseSchema`.

## Prevention
When planning resume tests or docs, require resuming with a payload the handler accepts and asserting the returned tool content, so an ignored payload fails.
