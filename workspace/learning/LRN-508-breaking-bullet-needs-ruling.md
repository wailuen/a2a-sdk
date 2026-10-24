---
id: LRN-508
title: Breaking bullets need spec clause or ruling URL
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
Three GH-245 bullets under Breaking changes cited neither an `issues/245#issuecomment-` ruling URL nor an exact spec clause. GH-245 had zero comments, so an issue body was the only authority.

## Root cause
The issue body was treated as a ruling. A wave cannot self-ratify a breaking change.

## Check
For each bullet under `### 🔴 Breaking changes` in CHANGELOG.md, grep for `issuecomment-` or a quoted spec clause (e.g. `A2A v0.3.0`, `MCP 2025-06-18`). Confirm `gh api repos/wailuen/a2a-sdk/issues/245/comments` is non-empty when a ruling is cited.

## Prevention
When planning a breaking change, ensure the bullet carries a spec clause or ruling URL at write time. If neither exists, escalate to the user for a ruling comment instead of writing one. Non-SemVer harness behavior goes under Fixed.
