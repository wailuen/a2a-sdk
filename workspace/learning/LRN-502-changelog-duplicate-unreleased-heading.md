---
id: LRN-502
title: Parallel groups add duplicate [Unreleased] headings to CHANGELOG
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
CHANGELOG.md ended a wave with three `## [Unreleased]` headings (lines 7, 21, 26), each with its own `### Fixed`. The LRN-494 check and LRN-491's section scan then missed bullets under the later headings.

## Root cause
Each parallel group appended a fresh heading block instead of adding bullets under the one existing heading.

## Check
Verify `grep -c '^## \[Unreleased\]' CHANGELOG.md` prints 1 and `grep -c '^### Fixed' CHANGELOG.md` has no duplicates inside [Unreleased].

## Prevention
When planning parallel groups that touch CHANGELOG.md, require in-place Edit that appends bullets under the existing [Unreleased] subheadings, never new headings. Add the count==1 grep to the archive gate.
