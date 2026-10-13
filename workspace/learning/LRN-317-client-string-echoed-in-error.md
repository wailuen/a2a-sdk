---
id: LRN-317
title: Client enum-like string echoed unbounded into wire error text
category: security
severity: high
source: redteam
date: 2026-10-13
---

## What happened
AG-UI put the client's raw `content[i].type` into `RUN_ERROR.message` after only an `isidentifier()` check. A probe with `type='a'*200000` returned a 200 KB error frame. The todo's "Reuses: C-007" and "SI: SI-2" notes were not followed.

## Root cause
`isidentifier()` is not a length or content bound, and `ag_ui.py` never used C-007 `safe_error_text`.

## Check
Grep `agent_sdk/routes/` for client-derived labels in error messages; confirm each uses an allowlist or `safe_error_text(..., max_len=...)`. Test: 10k-char and non-ASCII `type` yield a bounded `RUN_ERROR.message`.

## Prevention
When planning any error path that names a client-supplied value, require a fixed allowlist mapping (unknown -> "unknown") or C-007 `safe_error_text(max_len=32)`, plus an oversize-input test.
