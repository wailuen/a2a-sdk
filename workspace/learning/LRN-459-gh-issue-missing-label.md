---
id: LRN-459
title: Auto-filing with gh --label fails when labels do not exist
category: ops
severity: high
source: redteam
date: 2026-10-23
---

## What happened
wave-cycle.js FILE_SDK_ISSUES_PY runs `gh issue create --label auto-filed` plus a component label. Neither exists on wailuen/a2a-sdk (only the 9 default labels), so every filing fails and nothing is logged as failed.

## Root cause
Labels were assumed to exist; fake-gh tests accept any label, so the failure was invisible.

## Check
Verify that `grep -n "label create\|label list" harness/workflows/wave-cycle.js` shows labels are ensured before `issue create`, and a fake-gh test makes an unknown label exit non-zero and asserts it is logged.

## Prevention
When planning automation that calls `gh issue create --label X`, ensure the plan creates or checks X first, falls back to no labels, and tests the missing-label failure.
