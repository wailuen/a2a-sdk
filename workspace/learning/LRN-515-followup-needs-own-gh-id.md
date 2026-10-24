---
id: LRN-515
title: Follow-up issue needs its own GH id in CHANGELOG
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The G4 todo was GH-247, but its [Unreleased] entry was labelled GH-235, an id already shipped in [0.21.0]. GH-247 appeared nowhere in [Unreleased], so the release step that closes issues by CHANGELOG id would miss #247. The test docstring repeated the mislabel.

## Root cause
The entry reused the id of the earlier issue because it extended the same test file.

## Check
For every GH id in the wave, verify `grep -n "GH-<n>" CHANGELOG.md` matches inside [Unreleased]. For GH-247, grep that line 11 starts with `GH-247:`.

## Prevention
When planning CHANGELOG entries, ensure each follow-up issue is labelled with its own GH id (optionally "follow-up to GH-N"), even when it extends an earlier issue's test file.
