---
id: LRN-437
title: Todo lists CHANGELOG.md in Creates but lands no line
category: sdk
severity: high
source: redteam
date: 2026-10-22
---

## What happened
GH-220 and GH-217 both listed CHANGELOG.md in Creates, but `[Unreleased]` had no entry for either. GH-217's AC required a documented caveat (self-check probes still cost a model turn) that lived only in the missing entry. RUN_ERROR.code, outcome on RUN_FINISHED and disconnect-cancel shipped with no release note.

## Root cause
Nothing verified that a declared Creates file was actually written.

## Check
`grep -n 'GH-220\|GH-217' CHANGELOG.md` must hit within `[Unreleased]`; each entry names its test file.

## Prevention
When planning, make the archive gate grep `[Unreleased]` for every GH id in the wave, and put any AC-mandated caveat text in the todo as a literal CHANGELOG line to land.
