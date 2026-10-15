---
id: LRN-368
title: Sanitizer defines its own look-alike table
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`safe_label_text` added a private `_LABEL_LOOKALIKES` table (redact.py:217) and re-added the │/｜ entries by hand, though the todo said "Reuses C-007, do not add a third translate table". Values matched today only by coincidence.

## Root cause
The author copied the characters instead of deriving the swap from `_BARE_SEPARATORS` / `_SPACED_SEPARATORS`.

## Check
`grep -n "_LABEL_LOOKALIKES" agent_sdk/` returns nothing. In redact.py, any `str.maketrans` or look-alike dict outside `_BARE_SEPARATORS` / `_SPACED_SEPARATORS` is a failure. A test asserts label and cell swaps agree for | and :.

## Prevention
When a todo says "Reuses C-NNN", the plan must name the exact existing symbols to import. Forbid new translate tables in redact.py, so labels and data cells cannot drift apart.
