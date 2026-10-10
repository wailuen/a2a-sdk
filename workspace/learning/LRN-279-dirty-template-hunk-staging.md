---
id: LRN-279
title: Dirty template tree blocks whole-file staging of wave hunks
category: ops
severity: high
source: redteam
date: 2026-10-09
---

## What happened
template/.claude/workflows/wave-cycle.js differed from template HEAD by about 1,483 lines belonging to other waves. The planned "stage only this wave's files" step could not work with a plain `git add`, so GH-152-E's AUTH_SURFACE and Entra setup changes never landed.

## Root cause
Earlier waves left template/ dirty, and the plan assumed a clean tree where file-level staging isolates one wave.

## Check
Run `git -C template diff --stat` before closing a wave. Confirm only this wave's hunks remain, or run `diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js` and confirm it is empty.

## Prevention
When planning template/ mirror steps, assume a dirty tree. Specify `git -C template add -p` for named hunks, and list unpropagated files in the closing note if blocked.
