---
id: LRN-417
title: Todo signed off without its CHANGELOG entries
category: ops
severity: high
source: redteam
date: 2026-10-17
---

## What happened
In `[Unreleased]` of CHANGELOG.md, the only G1 entry was GH-192. Entries for GH-198 (with ruling URL), GH-191 and GH-195 (provisional `agent_sdk.testing` API) were missing though the code had landed.

## Root cause
The CHANGELOG AC was treated as optional, and nothing checked it before sign-off.

## Check
For each GH id in the group, `grep -n "GH-<id>" CHANGELOG.md` must match inside the `[Unreleased]` section. Rulings must include their issue comment URL.

## Prevention
When planning a group, add a final AC per GH id: "CHANGELOG `[Unreleased]` entry exists (Fixed/Added/Changed, ruling URL, provisional/additive notes)". Verify by grep before marking the todo done.
