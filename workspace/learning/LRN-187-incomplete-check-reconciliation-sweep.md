---
id: LRN-187
title: Same-wave Check reconciliation sweeps miss sibling LRNs
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
A wave repointed six sibling LRN Checks after rewriting an invariant, but
missed three (LRN-028/036/037) grepping the same old pattern — one Check's
stated pass count is now unsatisfiable, the spelling is gone.

## Root cause
LRN-133's same-wave reconciliation has no completeness step: a wave
repoints the LRNs it recalls touching, not every LRN grepping the exact
pattern rewritten.

## Check
Before/after a pattern rewrite, diff
`grep -rl '<old-pattern>' workspace/learning/LRN-*.md` — post-wave result
must be empty (or only `superseded_by:` files). Nonzero = partial sweep.

## Prevention
When a wave rewrites/removes a pattern an existing Check pins, grep ALL
learning Checks for it first to get the full sibling list, then repoint
every match in the same commit — never rely on memory.
