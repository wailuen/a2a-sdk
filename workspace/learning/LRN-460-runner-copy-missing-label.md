---
id: LRN-460
title: Runner copy repeats missing-label auto-filing defect
category: ops
severity: high
source: redteam
date: 2026-10-23
---

## What happened
The sdk-wave.js copy of FILE_SDK_ISSUES_PY has the same `--label auto-filed` defect as wave-cycle.js (see LRN-459). With autoFileSdkIssues true, the SDK runner files nothing.

## Root cause
The script is duplicated across runners, so the label bug exists in both copies.

## Check
Verify that `grep -n "label create\|label list" .claude/workflows/sdk-wave.js harness/workflows/wave-cycle.js` matches in both, and test_candidate_logic_matches_across_runners passes.

## Prevention
When planning a fix to FILE_SDK_ISSUES_PY, ensure both runner copies are changed in the same todo and kept identical.
