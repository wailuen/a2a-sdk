---
id: LRN-072
title: git add on a directory containing .git creates a gitlink (mode 160000), not file tracking
category: ops
severity: high
source: manual
date: 2026-06-19
---

## What happened
`git add template/` appeared to succeed but only staged a gitlink entry
(`create mode 160000 template`) — a submodule SHA pointer. None of the actual
files inside `template/` were staged or committed to a2a-sdk. The gitlink
silently passed `git status` checks (no `??` output) but the release commit
contained no template file content.

## Root cause
Git treats any directory with a `.git` subdirectory as a nested repository.
`git add <nested-repo>/` does not recurse into the tree — it creates a 160000
"gitlink" object pointing to the nested repo's current HEAD SHA. This is Git's
submodule mechanism operating without a `.gitmodules` registration. Files are
only tracked directly if the nested `.git` is removed first (making it a plain
directory), which severs the nested repo's own history and remote.

## Check
```bash
git ls-files --stage template/      # 160000 mode = gitlink; 100644 = real file
git ls-files template/ | wc -l     # 0 = no files tracked; 1 = gitlink only
ls template/.git                    # exists = nested repo; absent = plain dir
```

## Prevention
Before adding any subdirectory to a2a-sdk's index, check whether it contains
`.git` (`ls <dir>/.git`). If it does, do NOT run `git add <dir>/` — the result
will be a gitlink, not file tracking. Decide first: (a) keep it as a peer repo
and push changes via its own git, or (b) remove its `.git` to track files
directly (irreversibly severs the peer-repo history). Document the choice in
`.gitignore` and a comment. See [[template-is-peer-repo-not-submodule]].
