---
id: LRN-023
title: Null redteam response treated as clean (fail-open)
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` line 468, the condition `if (!rt || rt.findingsCount === 0) { break }` conflates a null agent response with zero findings. When the redteam agent crashes or returns null, the fix loop breaks and marks the group clean — silently passing every group whose redteam agent fails. The same fail-open pattern exists at the phase-redteam null check on line 571.

## Root cause
A single guard merged two semantically distinct outcomes (unknown/error vs. confirmed-clean), causing null — an unknown state — to be handled identically to a zero-findings result.

## Check
```
grep -n '!rt || rt\.findingsCount' template/.claude/workflows/wave-cycle.js
```
Must return zero matches. Each call site must have separate `if (!rt)` (continue/warn) and `else if (rt.findingsCount === 0)` (break) branches.

## Prevention
When writing or reviewing redteam loop guards: null response MUST continue (retry or warn), never break. Zero findings is the only condition that may break the fix loop as clean. Never merge the null guard and the zero-findings guard into a single `||` condition.
