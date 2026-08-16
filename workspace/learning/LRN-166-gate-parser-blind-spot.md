---
id: LRN-166
title: Text gate parser has quote and multi-fence blind spots
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
The LRN-079 dead-path gate inspected only 28 of 135 LRNs' grep paths: it
split on any `|`, even inside a quoted pattern, and stopped scanning
`## Check` after the first closed fence. Nine flagged LRNs still grep
`template/`-only paths and stayed green.

## Root cause
Naive `split("|")` and "stop at first fence" both silently skip input
instead of erroring — a skipped check looks identical to a passing one.

## Check
`tests/test_learning_index.py` must split on unquoted `|` only, keeping
`in_check` true across fence closes (reset only on next `##` heading).
Then `grep -l 'template/' workspace/learning/LRN-*.md` — each match must
`ls`-resolve or be guarded by `test -d template/ &&`.

## Prevention
When planning a text/regex conformance gate, require quote-aware split,
full-heading-scope scanning, and a test asserting no silent input drops.
