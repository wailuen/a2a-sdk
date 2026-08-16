---
id: LRN-139
title: Row-fabrication guard neutralised only CR/LF, missing Unicode/C0 breaks
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
The GH-130 delimiter-safety fix in `_sanitize_cell` (agent_sdk/models/content_types.py) used
`_CRLF_RUN = re.compile(r"[\r\n]+")`, which only collapses CR/LF. U+2028 LINE SEPARATOR, U+0085
NEL, `\x0b` VT, and `\x0c` FF still split `str.splitlines()` output into fabricated rows, and C0
controls like `\x1b` pass through untouched to the A2A TextPart / MCP text wire.

## Root cause
The fix targeted the two break characters seen in the original report instead of the full
`str.splitlines()` break set plus C0/C1 controls, leaving a one-character-substitution bypass.

## Check
Verify `agent_sdk/models/content_types.py` neutralises `\x0b`, `\x0c`, `\x1c`-`\x1e`, `\x85`,
` `, ` ` and C0 controls (not just `\r`/`\n`) in `_sanitize_cell`; add/confirm
regression tests in tests/test_content_types.py asserting a 1-data-row ComparisonTable stays
1 row after `.splitlines()` for each of these characters, including `\x1b`.

## Prevention
When planning any delimiter/row-fabrication defense over free-text cell values, require
neutralisation of the full `str.splitlines()` break set (not a `[\r\n]`-only regex) plus C0/C1
controls — reuse the C-007 `str.translate(dict.fromkeys(range(0x20), " "))` idiom (loop.py:392)
rather than re-deriving a narrower regex.
