---
id: LRN-527
title: Multi-file CHANGELOG bullets must name every changed file by path
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The G2 bullets (GH-257, GH-259, GH-251) in CHANGELOG [Unreleased] did not name runner.py, redact.py, forwarding.py, mcp.py, store.py or a2a.py. The LRN-491 basename grep returned 0 for most of them.

## Root cause
Multi-file items were summarised by feature, not by file, so the per-file path list was never written.

## Check
For each changed agent_sdk/ file in `git diff --name-only`, run `grep -c <basename> CHANGELOG.md` over the [Unreleased] section and confirm it is >= 1.

## Prevention
When planning a multi-file item, require its CHANGELOG bullet to end with a per-file repo-path list. Re-run the LRN-491 basename loop before closing the group.
