---
id: LRN-523
title: CHANGELOG gets a second Unreleased heading
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`CHANGELOG.md` ended up with two `## [Unreleased]` headings (lines 7 and 22). The GH-254 bullet was added under a new second heading with its own `### Fixed`, violating LRN-494.

## Root cause
The bullet was added under a freshly created heading instead of appended to the existing `### Fixed` block.

## Check
Run `grep -c '^## \[Unreleased\]' CHANGELOG.md` and require exactly 1.

## Prevention
When planning any todo that touches CHANGELOG.md, require appending bullets under the existing `[Unreleased]` / `### Fixed` heading, never adding a heading. Make the grep count a done-criterion.
