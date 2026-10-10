---
id: LRN-271
title: Template mirror edited but never committed or pushed
category: ops
severity: high
source: redteam
date: 2026-10-09
---

## What happened
GH-152-E edited template/.claude/workflows/wave-cycle.js (new `src/auth/oidc` AUTH_SURFACE member) and template/.claude/skills/setup/SKILL.md (Entra section). Neither was committed or pushed to wailuen/a2a-agent-template; template HEAD stayed at ce6dbb5. Downstream clones miss both changes.

## Root cause
The todo named the mirror but had no explicit `git -C template commit && push` final step, and earlier waves' hunks were already bundled in the same unpushed file.

## Check
Run `git -C template status --short` and confirm no output for every template/ path the todo names. Otherwise the wave closing note must list the file as unpropagated (see LRN-071).

## Prevention
When planning a todo that names a template/ mirror, add a final step: stage this wave's hunks (`git -C template add -p`), commit, push. The todo is not done until that step is checked off or the closing note names the unpropagated files.
