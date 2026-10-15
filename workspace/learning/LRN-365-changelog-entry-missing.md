---
id: LRN-365
title: Todo AC requiring a CHANGELOG entry shipped without one
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-174 (label ASCII fix) landed in the tree with no CHANGELOG [Unreleased] entry. No ruling URL, no text-format-change flag, and no list of the other labels still rendered through `safe_cell_text`. Two todo acceptance criteria were unmet.

## Root cause
Several groups edit the shared CHANGELOG.md, so one group's missing entry is hidden by the others' entries.

## Check
For each GH number in the wave todos, run `grep -n "GH-NNN" CHANGELOG.md` and confirm a match inside the `[Unreleased]` block. Text-format changes must carry a "Text-format change" flag and the ruling URL.

## Prevention
When planning, give every GH issue its own CHANGELOG AC naming the section (Fixed/Breaking), the ruling URL and any format-change flag. Add a grep-per-GH-number step to the phase gate.
