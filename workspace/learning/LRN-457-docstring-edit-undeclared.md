---
id: LRN-457
title: Docstring-only edit to a Reads-only file left undeclared
category: testing
severity: high
source: redteam
date: 2026-10-23
---

## What happened
`agent_sdk/agent/registry.py` had its `output_schema()` docstring rewritten for GH-219. The file appeared only under GH-221 Reads, in no Creates/Modifies line, and not in `[Unreleased]` CHANGELOG.

## Root cause
A docstring edit was treated as not a real modification, so scope declarations were skipped.

## Check
Verify that every path in `git diff HEAD --name-only` under agent_sdk/ appears in a todo Creates/Modifies line and in the `[Unreleased]` CHANGELOG Changed list (grep each by basename).

## Prevention
When planning, ensure any production file touched, even only a docstring, is listed in the owning GH todo's Creates/Modifies and its CHANGELOG bullet.
