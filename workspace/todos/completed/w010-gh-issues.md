# w010 — GitHub issues #19–#22

Sourced from open issues on wailuen/a2a-sdk. All items are coordinated changes
to `harness/workflows/wave-cycle.js` — pytest gate architecture. Run sequentially
(GH-19 lays the foundation; GH-20, GH-21, GH-22 build on it).
Target: v0.5.1.

---

## Group A — Pytest gate architecture

- [ ] `GH-19` Add GATE_SCHEMA and consume pytest gate results to block fix loops ‖ group:A
  - Creates: modifies `harness/workflows/wave-cycle.js`
  - Reads: `harness/workflows/wave-cycle.js`
  - Severity: critical
  - Root cause: The three centralized pytest gate `agent()` calls in the unit-redteam, phase-redteam,
    and (future) archive phases use no `schema`, so their return values are discarded. A red test
    suite is invisible to the control flow — the wave exits the fix loops solely on
    `rt.findingsCount === 0` and never checks whether the code compiles or tests pass.
  - Fix: Add `GATE_SCHEMA = { type: "object", properties: { exitCode: { type: "number" },
    passCount: { type: "number" }, failCount: { type: "number" },
    failures: { type: "array", items: { type: "string" } } }, required: ["exitCode"] }`.
    Add a gate agent call after each implement phase (unit, phase) with `schema: GATE_SCHEMA`.
    In each fix loop: if `gate.exitCode !== 0`, dispatch a targeted fix agent for the failing
    tests before the next redteam round. Track `testsRed` flag across the whole workflow.
  - AC: A pytest gate agent call uses `schema: GATE_SCHEMA` and its result is captured;
    when `exitCode !== 0`, a targeted fix agent is dispatched before the loop continues.
  - GH: https://github.com/wailuen/a2a-sdk/issues/19

- [ ] `GH-20` Add post-protocol-fix test gate before protocol recheck ‖ group:A
  - Creates: modifies `harness/workflows/wave-cycle.js`
  - Reads: `harness/workflows/wave-cycle.js`
  - Severity: high
  - Root cause: After the `proto:fix` agent edits protocol files, the workflow immediately
    runs the parallel advisor recheck with no test gate in between. A protocol fix that
    introduces a domain regression is never caught — the recheck is a conformance audit,
    not a test run. The Phase Redteam loop (last test gate) has already completed by this point.
  - Fix: Add a `gate:proto:fix` agent call with `GATE_SCHEMA` immediately after the
    protocol-fix `agent()` call and before the recheckTasks parallel dispatch. If
    `gate.exitCode !== 0`, set `testsRed = true`; the pre-archive gate (GH-22) then
    blocks archive.
  - AC: A test gate agent with `schema: GATE_SCHEMA` is dispatched after `proto:fix`
    and before the advisor recheck; when `exitCode !== 0`, `testsRed` is set.
  - GH: https://github.com/wailuen/a2a-sdk/issues/20

- [ ] `GH-21` Update implement prompts — allow scoped tests, prohibit full suite ‖ group:A
  - Creates: modifies `harness/workflows/wave-cycle.js`
  - Reads: `harness/workflows/wave-cycle.js`
  - Severity: high
  - Root cause: Implement-phase agent prompts say "Run: pytest -q after implementing" with no
    qualification. Parallel group agents that each run the full suite compete for the same
    test database/ports and produce misleading results. With centralized gates (GH-19), the
    full-suite run is already covered; per-agent full runs are redundant and harmful. However,
    RED→GREEN discipline requires that agents CAN run scoped single-test invocations to verify
    their own correctness before the gate fires.
  - Fix: Replace the current open-ended "Run: pytest -q after implementing" with:
    "You MAY run scoped tests (`python -m pytest -q tests/test_<specific>.py`) to confirm
    RED→GREEN for your own files. Do NOT run the full test suite — a centralized gate runs
    after all groups finish and will catch suite-wide regressions."
    Apply to both the solo-todo and parallel-group implement prompts.
  - AC: Both implement prompt strings (solo and parallel) contain the explicit scoped-OK /
    full-suite-prohibited distinction and the reference to the centralized gate.
  - GH: https://github.com/wailuen/a2a-sdk/issues/21

- [ ] `GH-22` Add pre-archive test gate — block archive when suite is red ‖ group:A
  - Creates: modifies `harness/workflows/wave-cycle.js`
  - Reads: `harness/workflows/wave-cycle.js`
  - Severity: medium
  - Root cause: There is no pytest gate at the start of the Archive phase. The last test
    gate that runs is the final Phase Redteam fix round, which occurs before the entire
    Protocol Audit phase. Protocol fixes or codify steps can introduce regressions that
    pass all redteam/protocol checks but leave the suite red — and archive proceeds anyway,
    marking the wave complete in `plan.md` with a broken codebase.
  - Fix: At the top of `phase('Archive')`, add a `gate:pre-archive` agent call with
    `GATE_SCHEMA`. If `gate.exitCode !== 0`: log a clear "Suite is RED — archive blocked.
    Fix the failing tests and re-run /wave w<NNN>." message; set `testsRed = true` and
    `protocolBlocked = true`; skip the archive agent and `plan.md` update entirely.
    Surface `testsRed` in the workflow return object alongside `protocolBlocked`.
  - AC: When the pre-archive gate returns `exitCode !== 0`, the archive agent is never
    dispatched, `plan.md` is not updated, and the return object includes `{ testsRed: true }`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/22
