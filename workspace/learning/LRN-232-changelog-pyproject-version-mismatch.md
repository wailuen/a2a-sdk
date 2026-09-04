---
id: LRN-232
title: pyproject version and CHANGELOG heading disagree, both collide with real tags
category: ops
severity: high
source: redteam
date: 2026-09-03
---

## What happened
pyproject.toml read version 0.5.45 while CHANGELOG.md's top heading read
`## [0.8.0]`, and `git tag` showed v0.6.0/v0.7.0 already exist on a
lineage not merged into main. A tag cut from main today would produce
v0.5.45 carrying a changelog announcing 0.8.0, below two already-released
tags.

## Root cause
Two files that must agree on the release identity (pyproject.toml and
CHANGELOG.md) were edited independently across waves with no check that
they still match, and neither was checked against existing tags.

## Check
`grep '^version' pyproject.toml` and the top `## [` heading in
CHANGELOG.md must be the identical SemVer string; that string must sort
above every entry in `git tag --list 'v*'`. Fail the release gate if
either comparison fails.

## Prevention
When planning a release, require `sdk-release` to assert
pyproject-version == newest-CHANGELOG-heading == a value greater than
every existing tag, as one atomic pre-tag check, before bumping anything.
