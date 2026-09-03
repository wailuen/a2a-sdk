---
id: LRN-143
title: Bare catch-all on tool-dispatch path must log exception type, not just fixed string
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-135's SI-2 AC required the tool-dispatch internal-error path to emit a
fixed generic string to the caller while still recording exception detail via
`logger.exception`/`logger.error`. `loop.py`'s three catch-all branches
implemented the fixed-string half but used bare `except Exception:` with no
binding and no logging, leaving body-raised errors with zero operator
signal — while sibling dispatch sites in `mcp.py`/`admin.py` did log,
breaking the intended cross-surface parity.

## Root cause
The AC's two halves (safe caller-facing string + logged internal detail)
were treated as one requirement during implementation; only the string half
was checked, so the silent branch shipped unnoticed since it produces
correct-looking output on the happy path and only fails to diagnose on the
error path.

## Check
`grep -n "except Exception:$" agent_sdk/agent/loop.py agent_sdk/agent/mcp.py
agent_sdk/agent/admin.py` — every bare `except Exception` on a tool/handler
dispatch path must bind the exception (`as exc`) and be immediately followed
by a `logger.error`/`logger.exception` call logging `type(exc).__name__`
(never `exc`'s str/args, which can carry body-supplied SI-2 data).

## Prevention
When planning a fix whose AC pairs "safe fixed string to caller" with
"detail via logger" on an error path, add an explicit sub-check verifying
both halves land at every site the AC's `Reuses:`/parity annotation names —
not just the caller-visible half — and require a test asserting a log
record is produced naming the exception type with no field values.
