---
id: LRN-450
title: Time-based workflow gate reads banned clock and fails open
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
`implementStartSec` in wave-cycle.js / sdk-wave.js uses `typeof Date !== "undefined" ? Math.floor(Date.now()/1000) : 0`, yet the file header says the sandbox bans Date. With Date undefined, since=0 and any old file passes the freshness check; if Date.now throws, every wave crashes at Implement. Tests run under plain node, so neither case is exercised.

## Root cause
A gate took its timestamp from a clock the workflow sandbox forbids, with a 0 fallback that fails open.

## Check
`grep -n "Date.now" harness/workflows/*.js .claude/workflows/*.js` returns no match; a test runs the runner with `Date` deleted from global scope and asserts null/malformed timestamps count every pattern path as missing.

## Prevention
When planning any time-based gate in a workflow script, take the timestamp from a deterministic shell step (or marker-file mtime) and fail closed when it is absent. Never default a missing timestamp to 0.
