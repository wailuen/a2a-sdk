---
id: LRN-473
title: Unreleased work added to tagged release section
category: ops
severity: high
source: redteam
date: 2026-10-23
---

## What happened
The GH-229 entry (w062, unreleased) was added under the already-tagged `## [0.19.0] — 2026-10-23` `### Fixed`. This rewrote a shipped release's notes. Another group owned the item, but CHANGELOG was in G1's scope.

## Root cause
The tagged section sat next to the work and was edited as if it were open.

## Check
`git diff CHANGELOG.md` must show no added lines below the first tagged `## [x.y.z]` heading (LRN-145).

## Prevention
When planning CHANGELOG edits, state that only [Unreleased] may change; tagged sections are read-only.
