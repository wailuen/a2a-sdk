---
id: LRN-332
title: Template mirror pushed while SDK-side change was lost
category: ops
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-164 existed in the pushed template repo (commit 8502301) but not in the SDK tree: `_looks_like_path` still rejected uv.lock, .env.example, .gitignore, and no Creates:/Modifies: scan existed. `cmp` of the two wave-cycle.js copies differed, breaking the byte-identical AC (LRN-085).

## Root cause
The peer-repo mirror was pushed and the group closed without comparing the SDK copy to the template copy.

## Check
`cmp harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js` exits 0; `pytest tests/test_wave_scope_extraction.py` passes with GH-164 cases.

## Prevention
When planning a group that mirrors files to a peer repo, add a closing step: cmp SDK vs template copies before closing. A pushed mirror with no SDK diff means the SDK change was lost.
