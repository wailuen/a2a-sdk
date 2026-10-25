---
id: LRN-542
title: Parallel waves leave duplicate Unreleased headings
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
CHANGELOG.md had two `## [Unreleased]` headings (lines 7 and 31) with repeated Breaking/Fixed/Changed subheadings. LRN-491's first-block scan missed half the release notes.

## Root cause
Parallel work on separate GH items each added its own Unreleased block instead of merging into the existing one.

## Check
`grep -c '^## \[Unreleased\]' CHANGELOG.md` must print 1, and each subheading must appear once inside that block.

## Prevention
When planning parallel waves, assign changelog edits to one merge step that appends bullets under the existing Unreleased subheadings and never adds a new heading.
