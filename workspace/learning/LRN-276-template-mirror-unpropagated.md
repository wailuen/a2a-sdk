---
id: LRN-276
title: Template mirror edits left uncommitted in peer repo
category: ops
severity: high
source: redteam
date: 2026-10-09
---

## What happened
GH-152-E changed template/.claude/workflows/wave-cycle.js (new `src/auth/oidc` AUTH_SURFACE member) and template/.claude/skills/setup/SKILL.md. `git -C template status --short` showed both modified and template HEAD unchanged, so seeded agents got neither change.

## Root cause
The todo named template/ mirrors but had no explicit commit-and-push step in the peer repo; the in-repo edit was treated as done.

## Check
Run `git -C template status --short` and confirm no output for each template path listed in the todo's Modifies list, or that the closing note names them as unpropagated.

## Prevention
When planning a todo that mirrors into template/, add a final step: `git -C template add -p <paths>`, commit, push. Do not allow archive until it is clean or the files are named as open deliverables.
