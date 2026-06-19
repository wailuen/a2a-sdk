---
id: LRN-063
title: Null gate response fails open in wave-cycle archive path
category: security
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
The active runtime `.claude/workflows/wave-cycle.js` (line 1239) checked `if (archiveIntent && archiveIntent.offendingPaths && ...)` before blocking archive. When the gate agent crashed and returned null, the null archiveIntent fell through to the else branch which logged "Commit check passed" and allowed the archive to proceed — a silent false-clean result on unknown commit state. The corrected harness copy at `harness/workflows/wave-cycle.js:1303` already guarded this with an explicit null check that sets `protocolBlocked = true`.

## Root cause
The compound `if (x && x.field && ...)` idiom used to check offending paths conflates "gate said clean" with "gate returned nothing" — a null response falls through to the affirmative else branch instead of being treated as a failure.

## Check
grep -n 'archiveIntent &&' .claude/workflows/wave-cycle.js | grep -v 'protocolBlocked'
# Must return no results; a bare `if (archiveIntent && archiveIntent.offendingPaths` without a prior null-block guard is a violation.

## Prevention
When planning any gate/agent response handler in a wave runner, ensure null or missing responses are caught as the FIRST branch and set protocolBlocked (or equivalent fail-closed flag) before any offendingPaths or field checks. Never let a null gate response reach an else branch that would log or act as a pass. Keep .claude/ and harness/ workflow copies in lockstep on this invariant — port guards to both files in the same commit.
