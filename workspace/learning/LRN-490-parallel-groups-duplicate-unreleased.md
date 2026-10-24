---
id: LRN-490
title: Parallel groups each open their own Unreleased heading
category: ops
severity: high
source: redteam
date: 2026-10-23
---

## What happened
CHANGELOG.md ended up with four `## [Unreleased]` headings (GH-231, GH-206 groups each opened their own). The wave rule said each item edits only its own row.

## Root cause
Parallel groups each created a fresh section instead of adding bullets to the one existing block.

## Check
Run `grep -c '^## \[Unreleased\]' CHANGELOG.md` and confirm the result is exactly 1. Same for each `### Added/Changed/Fixed` heading under it.

## Prevention
When planning parallel CHANGELOG edits, tell every group to append bullets inside the single existing [Unreleased] block and never add a heading (LRN-145).
