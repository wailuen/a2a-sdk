---
id: LRN-027
title: Hardcoded seam-audit route paths bypass dynamic allCreates derivation
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
The wave-cycle template's seam audit hardcoded route paths (`src/routes/agent_card.py, src/routes/a2a.py, src/routes/mcp.py, src/routes/oauth.py`) in the audit prompt instead of deriving them from `wave.allCreates`. This is a regression from the harness fix in RT-005, which introduced a dynamic `seamPaths` array filtered by `SEAM_ROUTE_MARKERS`. When an agent's routes live at non-standard paths or have not yet been created, the hardcoded paths silently produce empty seam-audit results, yielding a false-green outcome.

## Root cause
Template and harness diverged: the harness received the dynamic-path fix (lines 809–832) but the template was not updated in sync, leaving it with static strings that cannot adapt to project-specific route layouts.

## Check
```
grep -n "agent_card.py\|src/routes/a2a.py" \
  template/.claude/workflows/wave-cycle.js
# Must return 0 lines after the fix is applied.
grep -n "seamPaths\|SEAM_ROUTE_MARKERS" \
  template/.claude/workflows/wave-cycle.js
# Must return matches confirming dynamic derivation is present.
```

## Prevention
When a dynamic-path mechanism is added to the harness, the corresponding template must be updated atomically in the same commit. Planner must gate template release on a grep confirming no hardcoded route filenames survive in seam-audit blocks; also skip seam audit entirely when `seamPaths.length === 0` rather than proceeding with an empty scope.
