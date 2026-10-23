---
id: LRN-451
title: Stale-quote filter drops findings whose quote was never present
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
`dropStaleFindings` / `STALE_CHECK_PY` also drops findings whose quote was never in the file, from round 1 before any fix ran. Quotes with an elided "..." or a Read-tool line-number prefix came back stale and were dropped. A real critical/high finding with an invented quote is silently dismissed.

## Root cause
The filter treats "quote not found now" as "fixed", without proving the quote was ever found.

## Check
Test: an unverifiable round-1 quote stays blocking and is logged "unverifiable quote". `grep -n "dropStaleFindings" harness/workflows/wave-cycle.js` shows a signature-to-quote-verified map is consulted.

## Prevention
When planning any "no longer present" filter, drop only quotes previously confirmed present in an earlier round AND whose file changed since; skip it at round 1. Redteam prompts must say to use quote "" for findings about absent code or files.
