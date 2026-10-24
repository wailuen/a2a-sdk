---
id: LRN-494
title: Parallel groups add duplicate Unreleased headings
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
CHANGELOG.md ended up with 7 `## [Unreleased]` headings. Group G1 added two (GH-235, GH-236). LRN-491's Check reads only from the first heading to the next `## [`, so it saw just the GH-239 entry.

## Root cause
Parallel groups each created their own `[Unreleased]` section instead of adding bullets under the existing one.

## Check
`grep -c '^## \[Unreleased\]' CHANGELOG.md` must print 1, with one `### Fixed` and one `### Changed` inside it.

## Prevention
When planning parallel groups that touch CHANGELOG.md, tell each group to append bullets under the existing single `[Unreleased]` heading and its Fixed/Changed subheadings, never add a new heading.
