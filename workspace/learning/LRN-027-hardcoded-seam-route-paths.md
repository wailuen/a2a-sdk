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

**Superseded by w036/GH-123/LRN-132 (2026-07-21):** the Prevention clause below originally told planners to "skip seam audit entirely when `seamPaths.length === 0`." That guard was deliberately removed in w036 (GH-123): `SEAM_ROUTE_MARKERS` has no auth-path fragment, so an `AUTH_SURFACE`-only wave (e.g. touching only `src/auth/middleware`) sets `runProtocol=true` and dispatches the three per-protocol advisors, but `seamPaths` comes back empty — gating on it skipped the seam leg, the one check that verifies "Auth mode enforced uniformly: no surface accepts a token type another rejects," for exactly the class of change most likely to need it. The seam advisor (initial dispatch AND the recheck) now runs unconditionally whenever the enclosing `if (runProtocol)` block runs; `seamPaths` is still computed and used only to narrow the *prompt hint* text, falling back to a "(none matched by name...)" placeholder when empty. This does NOT reopen the defect this learning protects — the dynamic-derivation fix (Check below) is still required and still enforced; only the "skip when empty" Prevention advice is reversed. See LRN-034 / LRN-038, which codified the guard this note removes.

## Check
```
grep -n "agent_card.py\|src/routes/a2a.py" \
  .claude/workflows/wave-cycle.js
# Must return 0 lines — no hardcoded route filenames in the seam-audit prompt.
grep -n "seamPaths\|SEAM_ROUTE_MARKERS" \
  .claude/workflows/wave-cycle.js
# Must return matches confirming dynamic derivation is present.
# Do NOT also expect a `seamPaths.length > 0` guard around either push site — see
# the superseded note above; both pushes are unconditional by design (LRN-034/LRN-038).
```

## Prevention
When a dynamic-path mechanism is added to the harness, the corresponding template must be updated atomically in the same commit. Planner must gate template release on a grep confirming no hardcoded route filenames survive in seam-audit blocks. Do NOT gate the seam-audit dispatch itself on `seamPaths.length > 0` — w036/GH-123 deliberately removed that guard (see LRN-034/LRN-038): `SEAM_ROUTE_MARKERS` does not cover every protocol-surface member (e.g. `AUTH_SURFACE`'s `src/auth/middleware`), so gating dispatch on it silently skips the one leg that checks cross-surface auth-mode uniformity, for exactly the changes most likely to need it.
