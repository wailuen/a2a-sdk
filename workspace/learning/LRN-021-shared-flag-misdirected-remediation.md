---
id: LRN-021
title: Shared block flag emits wrong remediation instruction
category: ops
severity: high
source: redteam
date: 2026-06-15
---

## What happened
In `harness/workflows/wave-cycle.js` the pre-archive gate sets `protocolBlocked=true` for both a red test suite (lines 1015-1020) and actual protocol violations. The archive-skip log message always reads "Archive SKIPPED — wave X blocked by critical protocol findings" and instructs the user to run `/agent-verify`, even when the real cause is a failing test suite. This sends developers down the wrong remediation path.

## Root cause
A single boolean flag (`protocolBlocked`) conflates two distinct failure modes. The log message was written only for the protocol-violation case and was never updated to cover the test-suite-red case.

## Check
```
grep -n "protocolBlocked" harness/workflows/wave-cycle.js | grep -v "^\s*//"
```
Confirm that every branch setting `protocolBlocked = true` is followed by a distinct log message that names the actual cause (tests vs. protocol).

## Prevention
When multiple conditions share a single block flag, either split into dedicated flags (`testsBlockedArchive`, `protocolBlockedArchive`) or capture a `blockReason` string at the point of the assignment. The archive-skip message must interpolate that reason; never hard-code a single remediation instruction for a multi-cause flag.
