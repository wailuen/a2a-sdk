---
id: LRN-170
title: Round-cap durability fix (LRN-164) unported to sdk-wave.js
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-132's round-cap fix (push-before-break, deferred note, blocking flag)
landed in wave-cycle.js mirrors but not sdk-wave.js: its phase cap stayed
a bare log+break with the push after break; the unit cap also pushed
after break, with no unitBudgetBlocked/phaseBudgetBlocked flags —
surviving critical/high findings went uncaptured and the wave archived
clean.

## Root cause
Same root cause as LRN-131/159/163: the sync guard compares only
wave-cycle.js copies, never sdk-wave.js, so a fix's own "port to all
runners" remediation went unenforced — even for the fix meant to close
that gap (LRN-164).

## Check
`grep -n "unitBudgetBlocked\|phaseBudgetBlocked" .claude/workflows/sdk-wave.js`
— both flags must be set true right after each round-cap's deferred-note
write, with `allHighFindings.push` BEFORE each `break`, not after.

## Prevention
When a remediation says "port to all runners," list sdk-wave.js as an
explicit Modifies: target, and block archive until a test_workflows.py
parity case asserts the symbols exist there too — a codified LRN alone
is not a gate.
