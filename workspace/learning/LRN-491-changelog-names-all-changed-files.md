---
id: LRN-491
title: CHANGELOG Unreleased bullet must name every changed agent_sdk file
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The GH-234 bullet in CHANGELOG [Unreleased] named chat.py and acceptance-api.js but not agent_sdk/console/static/a2ui.js or chat.js, both changed in the diff. The new export `resetSurfaces()` was mentioned without its file.

## Root cause
The bullet was written from the Python change; console static JS files were treated as secondary and skipped.

## Check
For each path in `git diff --name-only -- agent_sdk`, verify its basename appears between `## [Unreleased]` and the next `## [` in CHANGELOG.md (e.g. `grep -c agent_sdk/console/static/a2ui.js CHANGELOG.md`).

## Prevention
When planning a GH item, list every touched agent_sdk file, console static JS included, and require the CHANGELOG bullet to name each by basename, tying new exports to their file.
