---
id: LRN-320
title: SI annotation satisfied by docs warning only
category: security
severity: high
source: redteam
date: 2026-10-13
---

## What happened
The GH-157 todo carried SI-6 and SI-2 annotations. The landed `mcp_instructions` feature had only a "no secrets" docs warning: no build-time secret check, no recorded "SI-6 docs-only" decision, and no test that an unauthenticated `initialize` gets no instructions.

## Root cause
Implementation treated SI annotations as advisory; a docs warning was accepted as a guard.

## Check
Grep DESIGN.md for "SI-6" near mcp_instructions, or a build-time check in `agent_sdk/app.py` that fails on SecretStr values (field name only in the error). Confirm a test in `tests/test_gh157_mcp_instructions.py` posts `initialize` with no auth and asserts 401 and no instructions text.

## Prevention
For each SI annotation in a todo, plan one concrete artifact: a guard, a recorded decision, or a named test. A docs warning alone never satisfies it.
