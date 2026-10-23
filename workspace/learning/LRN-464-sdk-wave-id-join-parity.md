---
id: LRN-464
title: Finding-id join defect repeated in sdk-wave.js
category: sdk
severity: high
source: redteam
date: 2026-10-23
---

## What happened
.claude/workflows/sdk-wave.js originalFinding had the same id+file match with id-only fallback. A still-open SDK candidate could be matched to an earlier fixed finding with the same RT-NNN id and marked fixed-in-wave.

## Root cause
originalFinding is copied between the two runners; the fix was applied to only one copy.

## Check
Verify `grep -n "f.id === c.id" .claude/workflows/sdk-wave.js` matches wave-cycle.js (id+file+quote, no fallback) and the originalFinding parity test passes.

## Prevention
When planning a fix in a function shared by wave-cycle.js and sdk-wave.js, include both files in the same unit and keep the parity test covering that function.
