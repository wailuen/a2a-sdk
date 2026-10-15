---
id: LRN-369
title: SI note lands without a hostile-input test
category: testing
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The GH-175 todo said to cut only after the control-char collapse, so stripped characters cannot fill the 1024-char budget. No test checked it. Tests used only plain "A"/"T" strings, so restoring the old slice-before-collapse order would still pass. Same pattern as LRN-340 and LRN-292.

## Root cause
The SI-2 note was implemented but never mapped to a named test with hostile input.

## Check
In tests/test_gh175_title_cap_marker.py, confirm tests with `"\n" * 3000 + "X" * 10`, control chars (\x1b, \x85) around index 1023, and `safe_label_text("a|" * 300, neutralise="|")` (256 chars, ends in "…", no "|").

## Prevention
When planning, map every SI note to a named test using hostile input at the cut point (line breaks, C0/C1 chars), not filler text.
