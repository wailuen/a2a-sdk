---
id: LRN-409
title: Template skill mirror edited but not committed in peer repo
category: ops
severity: high
source: redteam
date: 2026-10-17
---

## What happened
harness/skills/add-tool and add-source SKILL.md were updated for GH-185 and the template mirrors matched byte for byte. But `git -C template status --short` showed both files modified and uncommitted, so downstream agents would not get the current_identity note.

## Root cause
A matching local diff was treated as delivery; the template is a separate repo and needs its own commit and push.

## Check
Run `git -C template status --short .claude/skills` and confirm it prints nothing. Run `git -C template log -1 --format=%s` and confirm it cites the sdk GH number. Then `git -C template status -sb` and confirm it is not ahead of origin.

## Prevention
When planning harness skill edits, add a step to commit and push the template repo (per LRN-071, never `git add template/` from a2a-sdk) before /sdk-release. Otherwise list both files as unpropagated in the wave closing note.
