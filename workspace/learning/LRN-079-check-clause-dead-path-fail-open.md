---
id: LRN-079
title: LRN Check clause grepping non-existent path is a fail-open guard
category: testing
severity: high
source: redteam
date: 2026-06-19
---

## What happened
LRN-073's second `grep` in its `## Check` clause targeted `.claude/workflows/acceptance-api.js`, a path that does not exist in this repo — `acceptance-api.js` is propagated only to `template/.claude/workflows/` and has no runtime copy under `.claude/workflows/`. Because `grep` on a missing file exits non-zero but produces no match output, the check silently "passes", making the codified guard against `filter(Boolean)` regression a dead no-op. The correct path is `template/.claude/workflows/acceptance-api.js`.

## Root cause
The Check clause was written without verifying the target path resolves to a real file (`ls`). Files that live only in a peer/template directory have no presence under the expected runtime path, so any grep against the wrong location fails open — the regression it guards never fires.

## Check
For every `## Check` grep in `workspace/learning/LRN-*.md`, verify the target path exists:
```
grep -h 'grep.*\.js\|grep.*\.py\|grep.*\.ts' workspace/learning/LRN-*.md | \
  grep -oE '[a-zA-Z0-9_./-]+\.(js|py|ts)' | sort -u
```
Then confirm each extracted path resolves: `ls <path>` must succeed. A missing path is a fail-open guard that must be corrected.

## Prevention
When writing or reviewing an LRN `## Check` clause that includes a `grep` against a file path, run `ls <path>` before finalising. If the file lives only in a peer/template directory (e.g. `template/.claude/workflows/`), use that canonical path — never an assumed runtime location. Flag any existing Check that greps a path not present in the repo as severity-high and update it immediately.
