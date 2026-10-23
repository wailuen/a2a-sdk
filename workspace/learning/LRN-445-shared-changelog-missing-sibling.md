---
id: LRN-445
title: Shared CHANGELOG hides a missing sibling GH entry
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
GH-216 listed CHANGELOG.md as a deliverable, but `grep GH-216 CHANGELOG.md` found nothing under [Unreleased]. The GH-215 entry was present, so the GH-216 bullet was lost in the shared file.

## Root cause
Parallel groups edit one CHANGELOG.md; one group's entry masks another's absence. Extends LRN-407 / LRN-424.

## Check
For each GH-NNN in the wave whose todo lists CHANGELOG.md, run `grep -c "GH-NNN" CHANGELOG.md` and confirm >= 1 under [Unreleased].

## Prevention
When planning parallel groups that all list CHANGELOG.md, add a per-id grep acceptance criterion to each group, and make sign-off check every id, not the file as a whole.
