---
id: LRN-546
title: Harness and template skill edits missing from Unreleased bullet
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-266 changed line 311 of `harness/skills/acceptance/SKILL.md`, `.claude/skills/acceptance/SKILL.md` and the peer-repo `template/.claude/skills/acceptance/SKILL.md` (0c6ce94). No [Unreleased] bullet named any of these paths. LRN-532 Check failed.

## Root cause
The wave bullet described the wire change but not the harness/template copies it also touched.

## Check
For each harness/, .claude/skills/ or template/ path in `git diff --name-only`, `grep -n "<path>" CHANGELOG.md` must match inside [Unreleased].

## Prevention
When planning a wave that edits skill copies, add an AC that the CHANGELOG bullet lists each changed path in full, including peer-repo paths with commit SHA.
