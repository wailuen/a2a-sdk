---
id: LRN-532
title: CHANGELOG bullets must name harness and template paths in full
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-256 [Unreleased] bullet said "the acceptance skill" instead of naming the changed files. The edit touched `harness/skills/acceptance/SKILL.md`, `.claude/skills/acceptance/SKILL.md` and the peer-repo `template/.claude/skills/acceptance/SKILL.md` (commit 4ce9597).

## Root cause
The bullet used a nickname, and the peer-repo edit had no commit reference (same gap as LRN-505).

## Check
Run `grep -F harness/skills/acceptance/SKILL.md CHANGELOG.md` and confirm a match inside [Unreleased] when that file changed. Repeat for every changed harness/ and template/ path in `git diff --name-only`.

## Prevention
When planning a wave that edits harness/ or template/ files, require the CHANGELOG bullet to list each full repo path, plus the peer-repo commit SHA for template edits. Never use a skill nickname.
