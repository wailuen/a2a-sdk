---
id: LRN-056
title: Wave todo path under gitignored/untracked tree is silently undeliverable
category: ops
severity: high
source: redteam
date: 2026-06-18
---

## What happened
Wave GH-70d planned a `Modifies: template/Dockerfile` change inside `a2a-sdk`. The `template/` tree is listed in `.gitignore` (line 38) and has been fully untracked since commit e7bf0a1 — `git ls-files template/` returns nothing. The canonical Dockerfile lives in the separate `wailuen/agent-template` repo, so the deliverable can never be committed from this repo.

## Root cause
The planner did not verify git-tracked status of every `Creates:`/`Modifies:` path before finalising the wave plan. Gitignored and multi-repo-split paths are indistinguishable from in-repo paths at a glance.

## Check
For every todo path: `git ls-files <path>` must return at least one line. An empty result means the path is outside this repo's tracked tree and must not appear as a wave deliverable here.

```
git ls-files template/   # must be non-empty for any todo targeting template/
```

## Prevention
When planning any wave, run `git ls-files <path>` for every `Creates:`/`Modifies:` path before accepting the todo. If the output is empty, re-file the todo against the correct repo (or mark `[~]` out-of-repo with target repo noted) — never mark it `[x]` done from this repo. See also LRN-052 (same class, canonical record).
