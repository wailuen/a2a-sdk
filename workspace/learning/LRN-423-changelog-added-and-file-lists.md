---
id: LRN-423
title: CHANGELOG missing Added entries and incomplete file lists
category: ops
severity: high
source: redteam
date: 2026-10-17
---

## What happened
`LoopPolicies` (exported) gained `empty_reply_retry`, but CHANGELOG had no `### Added` line. The GH-196 entry listed only registry.py though it also changed loop.py, docs/tools.md and the add-tool skill. The GH-194 entry omitted its main condition (only after a tool result).

## Root cause
Entries were written per issue, with file lists copied from one group and trigger wording summarized loosely.

## Check
For each new public field or parameter on a symbol in `__all__`, `grep` CHANGELOG [Unreleased] for an `### Added` line naming it. Compare each entry's files to `git diff --name-only` for that issue.

## Prevention
When planning a wave, require an `### Added` line for every new public field/parameter, and each entry's file list must name every production file its issue touched, even if shared with another issue.
