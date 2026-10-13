---
id: LRN-333
title: Deterministic cross-check diverges from AI parse rules
category: ops
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-164's inline Parse scope scan kept every backticked path on Creates:/Modifies: lines, including `template/...` mirror paths. The AI Parse prompt excludes other-repo paths, so `scopeMissedByParse` was non-empty and Parse aborted with `scope-scan-mismatch`. LRN-085 requires template mirrors in todos, so every harness workflow wave aborts.

## Root cause
The scan did not apply the same in-repo exclusion rule as the AI prompt.

## Check
Run the inline scan on a fixture wave file with a `template/.claude/...` Modifies entry; assert it is not reported as missed. Test must exist in tests/.

## Prevention
When adding a deterministic cross-check of an AI step, derive its inclusion and exclusion rules from the same prompt text and add a fixture test covering each exclusion.
