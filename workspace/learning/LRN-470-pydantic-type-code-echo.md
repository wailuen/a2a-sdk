---
id: LRN-470
title: Unknown pydantic error type code echoed into tool error text
category: security
severity: medium
source: redteam
date: 2026-10-23
---

## What happened
safe_validation_message (agent_sdk/agent/loop.py) fell back to the bare pydantic error `type` code for any code it did not know. A validator raising `PydanticCustomError(f"leak_{x}", ...)` with a code built from input put that input into MCP isError text, A2A/AG-UI tool results and admin try-tool output (GH-230, verified on pydantic 2.13).

## Root cause
The fallback assumed every type code is a fixed pydantic identifier. Custom codes are author-chosen strings and can embed input.

## Check
Run tests/test_gh230_safe_value_error.py. Also grep agent_sdk/agent/loop.py for `_VALIDATION_TYPE_PHRASES.get(` and confirm the default is a fixed phrase, not the code.

## Prevention
When planning any text built from a pydantic error, render only allowlisted codes (LRN-044, LRN-216). Give authors a fixed-text channel (SafeValueError class `message`) instead of letting raise-time text through.
