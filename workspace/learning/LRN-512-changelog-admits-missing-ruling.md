---
id: LRN-512
title: CHANGELOG bullet must not admit a missing ruling
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The [Unreleased] bullet for GH-245 (acceptance-api.js input validation) ended with "no owner ruling on GH-245 yet". This violates the LRN-444 check.

## Root cause
The author disclosed process state in release notes instead of citing a ruling or stating why none is needed.

## Check
Verify `grep -n "no owner ruling" CHANGELOG.md` returns nothing inside [Unreleased].

## Prevention
When planning a CHANGELOG entry, ensure it either cites a ruling issue URL or states why none is needed (e.g. "not a SemVer surface"). Never write that a ruling is pending.
