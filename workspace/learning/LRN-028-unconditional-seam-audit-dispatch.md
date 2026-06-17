---
id: LRN-028
title: Unconditional seam audit dispatch on empty seam paths
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
The wave-cycle template unconditionally pushes a seam audit task inside the `if (runProtocol)` block (line 739) without checking whether any seam-relevant creates paths exist in `wave.allCreates`. When a wave touches only A2UI surface files (e.g., `src/a2ui/`) with no route files, the seam agent runs against hardcoded paths that may not exist, returns stale or empty results, and those results are treated as passing. The seam recheck task has the same unconditional push.

## Root cause
The `seamPaths.length === 0` guard exists in the harness but was not mirrored into the template's push logic, so the template always dispatches regardless of whether there is anything to audit.

## Check
```
grep -n "seamPaths" template/.claude/workflows/wave-cycle.js | grep -E "push|recheck"
# expect: both push sites are guarded by seamPaths.length > 0
```

## Prevention
When generating or reviewing wave-cycle task-push blocks, verify every conditional task push (seam audit, seam recheck) is wrapped in `if (seamPaths.length > 0)` before the push call. Mirror harness lines 813–832 and 937–948 into the template verbatim.
