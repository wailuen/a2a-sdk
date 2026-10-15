---
id: LRN-367
title: Release gate lacks per-issue CHANGELOG coverage check
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
Code for GH-175, GH-176 and GH-177 was in the working tree, but [Unreleased] had no entries for them. GH-176 is a breaking Basic Catalog name boot check needing a Breaking entry with a Migration line. A line pointed to "done in GH-176", which did not exist. Releasing 0.14.0 would have shipped an undocumented breaking change.

## Root cause
No release step compares landed GH issues against CHANGELOG entries.

## Check
For every GH number in `git log` and `workspace/todos/`, `grep "GH-NNN" CHANGELOG.md` matches in [Unreleased]. Breaking entries contain `**Migration**`. The intro line covers the full GH range.

## Prevention
When planning a release, add a gate: block tagging until each landed GH issue has its own entry, with Breaking + Migration where the todo requires it, and each cites its ruling URL.
