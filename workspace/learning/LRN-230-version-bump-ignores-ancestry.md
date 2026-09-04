---
id: LRN-230
title: Version bump written while branch is behind origin's tag lineage
category: ops
severity: high
source: redteam
date: 2026-09-03
---

## What happened
pyproject.toml was bumped to 0.8.0 on a tree 14 commits behind origin/main,
while origin already carries tags v0.6.0/v0.7.0 that this branch never
merged. The CHANGELOG's own 0.8.0 header admits divergence is unresolved,
yet the version field was committed anyway.

## Root cause
The version bump was treated as a local counter increment instead of a
claim about ancestry — nothing checked that HEAD actually contains the
history behind every lower-numbered tag before writing a higher number.

## Check
Before any bump, run `git rev-list --count HEAD..origin/main` and
`git tag --list 'v*' --merged HEAD` — refuse to write pyproject.toml if
the first is non-zero or if a tag with a higher SemVer than the target
exists but is not `--merged`.

## Prevention
When planning a release step, require `sdk-release` to fail closed on
divergence: gate the version bump on `HEAD..origin/main` being empty and
on the new version sorting above every tag reachable from HEAD, not just
above the previous local pyproject.toml value.
