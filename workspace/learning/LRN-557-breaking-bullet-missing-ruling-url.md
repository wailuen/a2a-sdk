---
id: LRN-557
title: Breaking CHANGELOG bullet lacks its own ruling URL
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-262 item 1 Breaking bullet reversed the GH-171 contract (required nullable fields now shown optional) but cited no ruling URL. The sibling item 4 bullet had one. This failed the LRN-357 check.

## Root cause
The author assumed one ruling URL on a sibling bullet covered every bullet for the same GH issue.

## Check
For each Breaking bullet in `[Unreleased]` of CHANGELOG.md, verify it contains a spec clause or `issues/NNN#issuecomment-`. Each bullet must match on its own, not through a neighbour.

## Prevention
When planning a Breaking CHANGELOG entry, require every bullet to carry its own ruling URL, even when several bullets share a GH issue (LRN-357). Bullets that reverse an earlier contract must also name the reversed issue.
