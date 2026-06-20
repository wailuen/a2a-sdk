---
id: LRN-068
title: Phase redteam scores ACs against unimplemented wave targets
category: testing
severity: high
source: redteam
date: 2026-06-18
---

## What happened
Wave w020 was presented for phase review with all four Creates/Modifies targets unedited — `git diff` between the reference commit and the working tree showed zero changes to those files. The worktree branches pointed to a stale older commit (3c25ab4 vs the expected HEAD 2fb22cb), and no AC from GH-70a/b/c/d was satisfied in the landed code. The wave was nonetheless processed through a phase gate without being rejected.

## Root cause
The phase redteam did not compare the wave's Creates/Modifies set against actual landed diffs before scoring ACs. An empty or stale diff was treated as a valid implementation surface rather than as an automatic gate failure.

## Check
Before scoring any AC, run: `git diff <baseline-commit>..HEAD -- <each Creates/Modifies file>`. If every file in the wave's Creates/Modifies set returns an empty diff, the gate must fail unconditionally. Verify no wave archive step is reached while this condition holds.

## Prevention
When planning phase redteam steps, ensure the first step is a diff-presence check across all files listed under Creates and Modifies in the active todo. An empty diff against any target file is an automatic gate failure — the redteam must halt, report the gap, and block archiving until `/implement` is re-run and diffs land.
