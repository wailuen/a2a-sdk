---
id: LRN-563
title: Parallel group adds duplicate Unreleased heading
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
CHANGELOG.md ended up with six "## [Unreleased]" headings. Group G1 added its own for GH-268 instead of adding a bullet under the existing one. This failed the LRN-494/502/523/542 checks and the wave preamble rule.

## Root cause
Parallel groups each created a new heading rather than appending under the existing subheading.

## Check
`grep -c '^## \[Unreleased\]' CHANGELOG.md` must print 1; also one each of Breaking changes, Changed and Fixed subheadings under it.

## Prevention
When planning parallel groups that touch CHANGELOG.md, instruct each to append bullets under the existing [Unreleased] subheadings and never add a heading; run the grep -c check before signoff.
