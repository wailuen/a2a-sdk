---
id: LRN-357
title: Breaking CHANGELOG entries must cite their authority
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The GH-172 Breaking entry said "A2UI needs PascalCase wire names" with no spec clause and no maintainer ruling URL. The GH-173 entry also lacked its ruling URL.

## Root cause
Justification was prose-only, so nothing showed who authorized the boot failure.

## Check
For each Breaking bullet in the release section, verify it contains a spec clause or an `issues/NNN#issuecomment-` URL: `grep -n "issuecomment-" CHANGELOG.md`.

## Prevention
When planning a rejection or boot failure, record the ruling comment URL (or exact spec clause) in the todo, and require it in the CHANGELOG Breaking bullet. Never write an uncited "the protocol needs X".
