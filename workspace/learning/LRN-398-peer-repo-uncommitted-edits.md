---
id: LRN-398
title: Template skill edits left uncommitted in peer repo
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-182 edited acceptance and agent-verify SKILL.md to mint a service key. The template peer repo copies showed `M` in `git status` and origin/main stayed at a6e3b29. Downstream agents seeded from the template kept the admin-key flow. Related: LRN-276, LRN-290, LRN-335.

## Root cause
The in-repo diff matched the template edit, so the mirror looked done, but the peer repo change was never committed or pushed.

## Check
Run `git -C template status --short` and confirm empty. Confirm `git -C template log origin/main -1` shows the GH-182 commit.

## Prevention
When planning a change to mirrored skills, add a final task: commit and push in template/ (wailuen/a2a-agent-template), then verify clean status and origin/main head. A matching in-repo diff is not propagation.
