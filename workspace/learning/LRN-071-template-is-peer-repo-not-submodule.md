---
id: LRN-071
title: template/ is a peer repo — wave todos must commit+push to wailuen/a2a-agent-template, not to a2a-sdk
category: ops
severity: high
source: manual
date: 2026-06-19
---

## What happened
A wave todo (GH-70d) modified `template/Dockerfile`. The wave committed the change
into the a2a-sdk working tree, but `template/` has its own `.git` pointing to
`wailuen/a2a-agent-template`. Adding `template/` to a2a-sdk's git creates a gitlink
(mode 160000) — only a SHA pointer, not the actual files. The files never land in
a2a-sdk's history, and `wailuen/a2a-agent-template` is never updated.

## Root cause
`template/` looks like a subdirectory but is an independent git repository with its
own remote. Downstream agents clone from `wailuen/a2a-agent-template` directly;
a2a-sdk is not in that delivery chain. Changes to template/ must be committed inside
`template/.git` and pushed to `origin` (wailuen/a2a-agent-template) to reach agents.

## Check
```bash
git -C template/ remote -v          # must show wailuen/a2a-agent-template
git ls-files template/ | wc -l      # must be 0 in a2a-sdk (no file tracking, only gitlink or nothing)
git -C template/ status --short     # shows uncommitted template changes
```

## Prevention
When planning todos that touch `template/`: treat it as an external repo delivery.
The todo's `Modifies:` path is `template/<file>` but the commit target is
`wailuen/a2a-agent-template`, not a2a-sdk. The wave implementer must run
`git -C template/ commit && git -C template/ push` as the final step for any
template/ change. Never run `git add template/` in the a2a-sdk context.
