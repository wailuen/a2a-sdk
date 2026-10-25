---
id: LRN-545
title: GH changelog bullets omit touched files
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
LRN-491 Check failed: agent/runner.py, routes/agent_card.py, app.py, tasks/store.py and models/errors.py were changed but absent from the [Unreleased] text. The GH-261 Fixed bullet named no file.

## Root cause
Bullets described behavior, not the files each item touched.

## Check
For every `git diff --name-only -- agent_sdk/`, `grep -c '<full path>'` over the [Unreleased] block must be >= 1.

## Prevention
When planning each GH item, require its changelog bullet to list every agent_sdk file it touches by full repo path, and run the diff-vs-changelog loop before archiving.
