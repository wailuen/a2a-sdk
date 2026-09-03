---
id: LRN-142
title: New zero-tolerance exits can bypass one-sided count/array guards
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-132 added loop-exit `blocking.length===0` in wave-cycle.js. The nearby
guard only fixed `findingsCount===0 && findings.length>0`, so schema-valid
`{findingsCount:5, findings:[]}` (no `minItems` in RT_SCHEMA) broke the
group clean at round 1 — a silent zero-tolerance bypass.

## Root cause
Guard coverage was checked against the old exit condition, not the new one
added in the same change, leaving a one-directional guard as a bypass.

## Check
`grep -n 'findingsCount !== rt.findings.length' .claude/workflows/wave-cycle.js
harness/workflows/wave-cycle.js` — must cover both directions, not the
`===0 && >0` special case alone. See LRN-028 for pinned spelling.

## Prevention
When a wave adds/changes a zero-tolerance exit keyed on an array, verify
every upstream count/array guard feeding it covers both mismatch
directions.
