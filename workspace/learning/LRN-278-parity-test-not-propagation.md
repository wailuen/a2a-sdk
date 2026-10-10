---
id: LRN-278
title: Passing in-repo parity test mistaken for template propagation
category: ops
severity: high
source: redteam
date: 2026-10-09
---

## What happened
GH-152-E's template deliverables (wave-cycle.js AUTH_SURFACE member, setup SKILL.md Entra section) stayed uncommitted. `git -C template status -sb` showed `main...origin/main [ahead 2, behind 4]` plus a 1,483-line uncommitted wave-cycle.js diff, while in-repo parity tests passed.

## Root cause
Parity tests compare working files only. They cannot show that the peer repo has the commit on origin, and the template was also out of sync with origin.

## Check
Run `git -C template fetch && git -C template log origin/main -- .claude/workflows/wave-cycle.js .claude/skills/setup/SKILL.md` and confirm this wave's commit appears.

## Prevention
When a wave's Modifies list includes template/, require reconcile with origin first, then hunk-level staging, commit and push. Block archive until origin has the commit or the closing note lists both files as open.
