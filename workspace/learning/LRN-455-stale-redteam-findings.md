---
id: LRN-455
title: Redteam findings must quote the current line so stale ones can be dropped
category: workflow
severity: medium
source: redteam
date: 2026-10-22
---

## What happened
A redteam kept re-raising findings about code that earlier fix rounds had already changed. The fix loop had no way to check a finding against the current file. Stall detection sent the loop to debug but never dropped the stale finding. (GH-211. The a2a-teamwork agent's own LRN-001 records the same incident; the SDK's LRN-001 is unrelated.)

## Root cause
`RT_SCHEMA` findings had no quoted source line, and `redteam.md` had no stale-finding rule.

## Check
`grep -n "quote" harness/workflows/wave-cycle.js .claude/workflows/sdk-wave.js` must show `quote` in `RT_SCHEMA` required and in `STALE_CHECK_PY`. `grep -c "never re-raise\|Never re-raise" harness/agents/core/redteam.md` must be >= 1.

## Prevention
Every finding carries `line` and an exact `quote`. Before each fix round one script runs `grep -F` for each quote in its file. Findings whose quote is gone are dropped, logged as stale, and left out of the blocking count and of "clean". An empty quote or a null script result keeps the finding (fail closed).
