# w020b — modify-only workflow/config hardening (covering todo)

RT-006 (2026-06-18): a set of modify-only infrastructure changes landed in the
working tree with NO covering todo — w020's scope was only the three
`harness/skills/*/SKILL.md` files. Per LRN-053, modify-only scope that slips
through un-reviewed is exactly the failure mode the Creates ∪ Modifies scope rule
exists to prevent. This todo captures those changes with explicit `Modifies:`
paths so they pass through todos-redteam, unit/phase redteam, and the protocol
audit before the wave archives.

All paths confirmed git-tracked (LRN-052). Run in parallel (group:G).

---

- [x] `WH-1` Reconcile the two wave-cycle.js copies into a single byte-identical superset and add a CI sync-check ‖ group:G
  - Modifies: `.claude/workflows/wave-cycle.js`, `harness/workflows/wave-cycle.js`
  - Creates: `tests/test_workflow_sync.py`
  - Reads: `.claude/workflows/wave-cycle.js`, `harness/workflows/wave-cycle.js`
  - Severity: critical
  - Root cause: `.claude/workflows/wave-cycle.js` was a stale fork of `harness/workflows/wave-cycle.js` — it lacked every fail-closed/null-gate hardening (RT-001 archive null-gate guard, RT-002 recheck `if (!protocolBlocked)` guard, deferred notes, `testsBlockedArchive` on null protoFixGate, null-round budget cap, circular-dep deferred note) while uniquely carrying the archive plan.md row-append handling. Whichever copy runs, some fix was silently un-applied.
  - AC:
    - The archive plan.md "append-new-row-if-missing" handling is folded into the harness copy (superset)
    - `diff .claude/workflows/wave-cycle.js harness/workflows/wave-cycle.js` is empty
    - `tests/test_workflow_sync.py` asserts the two copies are byte-identical and fails on any future drift
  - Resolves: RT-001, RT-002, RT-003

- [ ] `WH-2` Review the landed sdk-wave.js scope-union + redteam-dimension changes ‖ group:G
  - Modifies: `.claude/workflows/sdk-wave.js`
  - Reads: `.claude/workflows/sdk-wave.js`, `.claude/agents/core/redteam.md`
  - Severity: high
  - Root cause: the LRN-053 Creates ∪ Modifies union fix and the GH-65 Dimension-5 redteam-prompt fix landed in `sdk-wave.js` outside any todo. They need a formal todos-redteam + unit/phase-redteam pass.
  - AC:
    - `grep -nE 'allCreates|group\.creates' .claude/workflows/sdk-wave.js` returns only schema / parse-prompt / derivation-block lines
    - The unit AND phase redteam prompts each carry an explicit Dimension 5 (no stubs/placeholders/unmet ACs)

- [ ] `WH-3` Review the .gitignore worktrees + ADR-glob additions and the harness/CLAUDE.md reduction ‖ group:G
  - Modifies: `.gitignore`, `harness/CLAUDE.md`
  - Reads: `.gitignore`, `harness/CLAUDE.md`, `template/CLAUDE.md`
  - Severity: medium
  - Root cause: `.gitignore` gained worktree + ADR-credential globs and `harness/CLAUDE.md` was reduced (delegating the SI table / credential model to `template/CLAUDE.md`) outside any todo.
  - AC:
    - `.gitignore` carries both `workspace/adr/ADR-000-*-credentials.md` and `workspace/adr/ADR-001-*-credentials.md` globs
    - `harness/CLAUDE.md` no longer duplicates the SI table / credential model; `template/CLAUDE.md` remains the single source of truth
    - No credential file is committable: `git check-ignore -v workspace/adr/ADR-001-dev-credentials.md` returns a match
