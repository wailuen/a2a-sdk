---
id: LRN-177
title: Actionable errors need reachability tests, not raise-site unit tests
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-139 added three actionable `RuntimeError` messages in `_boto_client()`,
unit-tested by calling the raising helper directly. `converse()`'s only
production path wraps it in a generic `except Exception` reading `.message`
only, so the actionable text never reaches an operator.

## Root cause
Reachability depends on every catch-all between raise site and caller-facing
surface; a test invoking the raising function directly can't observe
intervening `except Exception` wrappers.

## Check
Tests asserting an actionable error message must call the real entrypoint
(e.g. `converse()`, not `_boto_client()` alone) and confirm the message
survives every wrapping `except Exception`. `grep -n "except Exception"
agent_sdk/agent/bedrock.py` — each branch must re-raise or log the specific
exception's detail before generalizing it.

## Prevention
When planning a new actionable error message, require an end-to-end test
through the real call path — never accept a raise-site-only unit test as
proof the message reaches the operator.
