---
id: LRN-256
title: Wave run on a branch behind origin re-fixes shipped issues
category: ops
severity: critical
source: redteam
date: 2026-09-03
---

## What happened
Local main was 5 commits ahead / 14 behind origin/main. Origin already
tagged v0.7.0 with an independent fix for the same GH issue this wave
re-fixed, plus a differently-scoped wave sharing the same name — both
lineages rewrote the same eight files, creating a hard-to-reconcile fork.

## Root cause
The wave's Implement phase never checked the branch against origin/main
before starting, so it planned and executed against a stale base as if it
were current.

## Check
Before Implement, run `git fetch && git rev-list --left-right --count
origin/main...HEAD` and fail/pause the wave if the branch is behind
(right-count > 0). Verify no wave proceeds past todos-redteam with a nonzero
behind-count unresolved.

## Prevention
When planning a wave, add a mandatory pre-Implement step: fetch origin and
confirm HEAD is not behind origin/main (or the reconciliation is explicit and
approved) before touching any scope file. Never let a wave's release version
skip ahead of what a merge with origin would actually justify.
