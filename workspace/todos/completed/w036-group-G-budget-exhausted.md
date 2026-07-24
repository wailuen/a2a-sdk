wave: w036
group: G
date: 2026-07-21
round_count: 5
status: resolved
resolved_date: 2026-07-21

## Resolution

All three round-5 group-G findings below were fixed in later rounds of the same
w036 run and are landed in the working tree. This note is retained for history;
it is NOT an open work item. Do NOT re-run /wave w036 on account of this note —
its findings are closed (evidence per finding below). Verified by the phase
fresh-lens debug pass (round 6).

## Findings

### RT-001 — RESOLVED
- severity: medium
- file: template/.claude/workflows/wave-cycle.js
- description: The template mirror (AC #2 deliverable) is edited on disk but UNCOMMITTED in its nested git repo (`git -C template status` shows ` M`; template HEAD still lacks AUTH_SURFACE), and the main-repo archive-commit gate cannot detect this: sdk-wave.js/wave-cycle.js list `template/.claude/workflows/` in offendingHarnessPaths, but template/ is gitignored in the main repo (.gitignore:38, a nested peer repo with 0 files tracked by the outer repo), so the gate's `git status --short` (run in the SDK repo) can never surface those paths — the watch entry is a dead guard.
- resolution: The archive gate now runs step 4b (`git -C template status --short`) and folds dirty `.claude/workflows/` paths from the nested repo into offendingHarnessPaths — present in both runners (`grep -c 'git -C template status --short'` returns 3 in each of sdk-wave.js and wave-cycle.js). The template mirror is committed and clean in its nested repo (`git -C template status --short` is empty; `git -C template show HEAD:.claude/workflows/wave-cycle.js` contains AUTH_SURFACE). Pinned by tests/test_workflows.py::test_rt002_step4b_* (all green).

### RT-002 — RESOLVED
- severity: low
- file: tests/test_workflows.py
- description: The seam-ungating regression tests were pure negative substring assertions — they did NOT assert the seam `advisorTasks.push` is unconditional. A future refactor that re-gates the seam with different syntax would reintroduce the GH-123 seam-skip bug while both tests stay green.
- resolution: The seam tests now assert unconditional dispatch structurally (indentation parity of the `advisorTasks.push`/`recheckTasks.push` against their unconditional sibling statements), across all four runners. tests/test_workflows.py::test_rt001_seam_task_not_gated_on_seam_route_markers, ::test_rt001_seam_recheck_task_not_gated_on_seam_paths, and the sdk-wave.js variants — 11 seam tests green.

### RT-003 — RESOLVED
- severity: low
- file: .claude/workflows/sdk-wave.js
- description: agent_sdk/auth/identity.py is in the require_identity chain (both verify backends `from .identity import Identity` and return an Identity) but was omitted from AUTH_SURFACE, so a wave touching only identity.py dispatched no protocol advisor.
- resolution: `agent_sdk/auth/identity` (src/auth/identity in the wave-cycle.js dialect) is now in AUTH_SURFACE in both runners and all three wave-cycle.js mirrors (sdk-wave.js:57, wave-cycle.js:59, harness/workflows/wave-cycle.js:59). Parity pinned by tests/test_workflows.py::test_rt001_wave_cycle_auth_surface_parsed_set_equality_with_sdk_wave.

## Instruction

Relocated from `workspace/todos/deferred/` to `workspace/todos/completed/` per
LRN-100 (a budget-exhausted deferred marker must be removed or relocated the
moment its findings land, or it falsely reports the wave as incomplete) —
this file had sat in `deferred/` past its own `status: resolved` note.
