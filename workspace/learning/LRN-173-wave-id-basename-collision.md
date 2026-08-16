---
id: LRN-173
title: Reused wave ID collides with completed/ basename and clobbers history
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
w036 was reused for a new GH-issue set while `workspace/todos/completed/w036-gh-issues.md` (GH-123, archived 2026-07-24) already existed under the same basename. The same collision hit `w036-group-G-budget-exhausted.md` in deferred/. Archiving the new wave (plain `mv` by basename) or running the LRN-100 relocation sweep silently overwrites the earlier wave's resolved record.

## Root cause
Wave IDs are assigned without checking uniqueness against `completed/`, and both the archive step and the LRN-100 sweep `mv` files by basename with no overwrite guard, so a duplicate ID destroys prior history with no error.

## Check
`for f in workspace/todos/active/*.md workspace/todos/deferred/*.md; do b=$(basename "$f"); [ -e "workspace/todos/completed/$b" ] && echo "COLLISION: $b"; done` must produce no output.

## Prevention
When planning a wave, assign IDs by scanning `active/`, `completed/`, and `deferred/` together for the next unused number, not just `active/`. Add a Parse-phase gate to wave-cycle.js/sdk-wave.js that fails fast if `completed/<basename>` already exists, and make archive/relocation `mv` refuse to overwrite an existing destination (`mv -n` or explicit pre-check).
