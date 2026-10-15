---
id: LRN-366
title: New sanitizer bypasses canonical cut-and-marker helper
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`safe_label_text` in redact.py called `safe_error_text(value, max_len=...)` directly. It cut before the control-char collapse and added no "…" marker, so 250 spaces plus text returned 6 chars, and a 300-char label was cut silently. `safe_line_text` (C-034) does both correctly.

## Root cause
The new sanitizer was not built on `safe_line_text`, giving the SDK two truncation rules.

## Check
`grep -n "safe_error_text" agent_sdk/common/redact.py` shows no call inside `safe_label_text`. Test: a 300-char label yields len 256 ending in "…", and leading whitespace cannot consume the budget.

## Prevention
When planning a new text sanitizer in redact.py, require it to call `safe_line_text` for cutting, then apply character swaps. Swaps must be length-preserving. Add a test for the cut and marker.
