---
id: LRN-058
title: Duplicate LRN ID orphans one learning from the redteam check loop
category: ops
severity: high
source: redteam
date: 2026-06-18
---

## What happened
Wave w020 created two files both claiming ID LRN-051: `LRN-051-gitignored-path-cannot-land-in-wave-todo.md` (category=planning) and `LRN-051-uv-no-dev-silent-noop-on-extras-only-layouts.md` (category=ops). The README index registered only the ops file, leaving the planning file orphaned and unreachable by the redteam learning-check loop.

## Root cause
The codify step did not read `workspace/learning/README.md` to determine the current highest LRN number before assigning IDs, causing two files to receive the same monotonic ID in the same wave.

## Check
Run: `grep -h '^id:' workspace/learning/LRN-*.md | sort | uniq -d` — must return empty (no duplicate IDs). Also verify: `diff <(grep -h '^id:' workspace/learning/LRN-*.md | sort) <(grep -oP 'LRN-\d+' workspace/learning/README.md | sort | uniq) | grep '^<'` must return empty (every file ID has a README row).

## Prevention
When codifying any learning, read `workspace/learning/README.md` first, extract the highest existing LRN number, and assign the next integer. Never assign an ID without consulting the current index. After writing the file, verify the assigned ID does not already exist with `grep -l "^id: LRN-NNN" workspace/learning/`.
