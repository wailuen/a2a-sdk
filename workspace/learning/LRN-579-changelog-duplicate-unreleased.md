---
id: LRN-579
title: Wave groups must share one Unreleased changelog heading
category: ops
severity: high
source: redteam
date: 2026-11-10
---

## What happened
CHANGELOG.md ended up with three `## [Unreleased]` headings and two `### Fixed` subsections. GH-277 and GH-276 each added their own block instead of joining the one GH-278/279 created. The first section also named none of the changed agent_sdk files.

## Root cause
Parallel groups each appended a fresh heading instead of editing the existing Unreleased section.

## Check
Verify that `grep -c '^## \[Unreleased\]' CHANGELOG.md` prints 1 and that `grep -c '^### Fixed' ` within the Unreleased section is at most 1; confirm the section names each changed agent_sdk file.

## Prevention
When planning multi-group waves, instruct every group to add its bullet under the existing `## [Unreleased]` and its existing `### Fixed`/`### Changed`, never a new heading; run the grep count == 1 before handing back.
