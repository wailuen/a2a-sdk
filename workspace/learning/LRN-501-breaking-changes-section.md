---
id: LRN-501
title: New rejections not listed under Breaking changes
category: sdk
severity: high
source: redteam
date: 2026-10-24
---

## What happened
`[Unreleased]` had no `### 🔴 Breaking changes` heading or **Migration:** line, yet the wave added new rejections and withheld output: GH-240 (card withheld without the standard profile URN), GH-241 (`TypeError` at class definition), GH-236 (bad cursor now -32602), GH-235 (64-level ingress cap, multi-entry resume is RUN_ERROR). Only GH-241 had an inline "behaviour change" note.

## Root cause
Breaking items were filed under Fixed/Changed/Added because the plan already targeted a minor bump.

## Check
Verify `grep -n "Breaking changes" CHANGELOG.md` matches inside `[Unreleased]`, and each entry there has a ruling URL and a `**Migration:**` line.

## Prevention
When planning, list every new rejection or withheld output as a Breaking item with ruling URL and Migration line (LRN-321, LRN-472), regardless of bump size.
