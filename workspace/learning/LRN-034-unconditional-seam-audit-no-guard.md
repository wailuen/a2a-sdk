---
id: LRN-034
title: Unconditional seam audit fires on every protocol wave
category: ops
severity: high
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` line 739, the seam audit advisor task is pushed unconditionally for every protocol wave. When a wave creates no route files, the seam audit still fires, producing empty or vacuous findings that inflate the issue list and waste an agent call.

## Root cause
No guard derives which files in the `creates` list are route files before scheduling the seam advisor. The harness version (RT-005) uses `SEAM_ROUTE_MARKERS` to derive `seamPaths` from `allCreates` and skips the push when `seamPaths.length === 0`.

**Superseded by w036/GH-123/LRN-132 (2026-07-21):** the `seamPaths.length > 0` guard this learning asked for was deliberately REMOVED in w036 (GH-123), across `.claude/workflows/wave-cycle.js`, `harness/workflows/wave-cycle.js`, and `template/.claude/workflows/wave-cycle.js`. `SEAM_ROUTE_MARKERS` has no auth-path fragment, so a wave touching only an `AUTH_SURFACE` member not matched by any marker (e.g. `src/auth/middleware`, `src/auth/identity`) sets `runProtocol=true` — dispatching a2a-advisor/mcp-advisor/ag-ui-advisor — while `seamPaths` comes back empty. Gating the seam push on `seamPaths.length > 0` therefore skipped the one leg that checks "Auth mode enforced uniformly: no surface accepts a token type another rejects" for exactly the class of change most likely to violate it — the occasional wasted agent call on a genuinely route-free wave (the cost this learning was written to avoid) is the accepted, documented tradeoff (`sdk-wave.js` already dispatched the seam task unconditionally, so this brings wave-cycle.js to parity). `seamPaths` is still computed and passed into the prompt to narrow the "files to audit" hint, it just no longer gates dispatch. Do not re-add this guard — see LRN-066/LRN-131 on the oscillation risk of "fixing" an intentionally-reversed decision back to its prior state.

## Check
```bash
grep -n 'seamPaths\|SEAM_ROUTE_MARKERS' .claude/workflows/wave-cycle.js harness/workflows/wave-cycle.js
test -d template/ && grep -n 'seamPaths\|SEAM_ROUTE_MARKERS' template/.claude/workflows/wave-cycle.js
grep -n 'proto:seam\|proto:recheck:seam' .claude/workflows/sdk-wave.js
```

RT-002 (round-7 fresh-lens debug) — corrects an RT-005/RT-014 rewrite that dropped
the `template/` copy on the justification that "`test_workflow_sync.py`'s
harness↔template axis already keeps the two byte-identical whenever it is checked
out". That axis runs **nothing** in a checkout without `template/`:
`HARNESS_TEMPLATE_SHARED` comes from `TEMPLATE_DIR.glob("*.js")` and is empty, so the
identity test is parametrized over zero cases and both presence guards are
`xfail(strict=True)`. A Check may only delegate its coverage to a test that actually
runs. The template line is restored, guarded INLINE per LRN-054 (same line — a guard
on its own line is still a dead-path guard).

The `template/` copy of `wave-cycle.js` is also currently KNOWN divergent (see
`workspace/todos/deferred/w039-group-G-budget-exhausted.md` RT-001) — so the `test -d
template/ &&` branch above is expected to fail this Check in the only checkout it can
currently run in, until RT-001 is closed. That is a real, visible failure to fix, not
a reason to drop the branch.

For the three `wave-cycle.js` copies: must return the `SEAM_ROUTE_MARKERS` constant definition and the `seamPaths` derivation. The seam advisor task push (`advisorTasks.push(...)` containing `'proto:seam'`) and the seam recheck push (`recheckTasks.push(...)` containing `'proto:recheck:seam'`) must NOT be wrapped in an `if (seamPaths.length ...)` guard of any spelling — both must sit at the same indentation as their unconditional sibling statements (`const seamPaths = wave.allScope.filter(...)` / `const recheckTasks = []`). Pinned by `tests/test_workflows.py::test_rt001_seam_task_not_gated_on_seam_route_markers` and `::test_rt001_seam_recheck_task_not_gated_on_seam_paths`, which assert this structurally (indentation parity), not just via substring absence.

`sdk-wave.js` has no `seamPaths`/`SEAM_ROUTE_MARKERS` of its own — it never had this gating bug, so it dispatches `proto:seam`/`proto:recheck:seam` unconditionally by construction. That runner is pinned separately by `tests/test_workflows.py::test_rt001_sdk_wave_seam_task_not_gated_on_seam_route_markers` and `::test_rt001_sdk_wave_seam_recheck_task_not_gated_on_seam_paths`, which compare the `advisorTasks.push`/`recheckTasks.push` indentation against the unconditional `const advisorTasks = []` / `const recheckTasks = []` sibling statements — added because prior to that, sdk-wave.js's unconditional push had zero regression coverage of its own (only the wave-cycle.js mirrors were checked).

Name ALL FOUR runners (sdk-wave.js + the three wave-cycle.js copies at `.claude/workflows/`, `harness/workflows/`, `template/.claude/workflows/`) when extending this check — a "dispatch unconditionally" invariant is only as strong as its weakest unpinned runner. The three wave-cycle.js copies are additionally held byte-identical by `tests/test_workflow_sync.py`, so a guard re-added to one copy but not the others would fail that sync test too.

> **Consolidation (2026-07-21):** LRN-038 ("Unconditional seam audit dispatch on empty seam paths") was merged into this record — it codified the same invariant from the A2UI-only-wave angle and, after the w036 reversal, had become byte-identical to this one in the README index. LRN-038 is now a one-line redirect stub pointing here. This is the single canonical record for the "seam audit dispatches unconditionally" invariant.

## Prevention
Before scheduling any cross-cutting advisor (seam, security, schema) whose scope depends on a derived path subset, check whether the marker set used to derive that subset covers EVERY array that can set the enclosing trigger flag true. If a protocol-surface member (e.g. an `AUTH_SURFACE` file) can be absent from the audit's own marker list, gating dispatch on that marker list silently drops coverage for that member's changes — dispatch unconditionally instead, and use the derived subset only to narrow what the prompt asks the agent to look at, not whether it runs at all. Mirror any push/guard decision identically across ALL byte-identical copies (`.claude/workflows/`, `harness/workflows/`, `template/.claude/workflows/`) so they never diverge from each other, regardless of which direction the guard goes.
