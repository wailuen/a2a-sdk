# SDK issue candidates — undefined ((see context date))

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: Wave w020 is entirely unimplemented: git diff shows no changes to any of the four Creates/Modifies targets, worktree branches point to a stale older commit, and no AC of GH-70a/b/c/d is satisfied in landed code.
- Severity: high
- Component: harness/workflow
- File: workspace/todos/active/w020-gh-issues.md
- Rationale: The finding is about the sdk-wave.js wave runner phase-review gate failing to detect an empty implementation diff — a harness/workflow invariant defect, not agent-domain logic.

## Candidate 2: template/Dockerfile build stage still uses bare pip install; uv is never installed; no COPY uv.lock exists; template/uv.lock is absent. The four GH-70 todos are a coupled dependency set that the wave header incorrectly marks as parallel-independent.
- Severity: high
- Component: harness/template
- File: template/Dockerfile
- Rationale: template/Dockerfile is the scaffold seed for every new agent — this is a harness/template issue, not an agent-specific implementation concern.

## Candidate 3: harness/skills/setup/SKILL.md Phase 5 step 1 runs uv sync --frozen (no --extra dev), then step 2 immediately runs pytest. The template's test deps live under [project.optional-dependencies].dev which uv sync does not install by default, so pytest is missing and the test step fails.
- Severity: high
- Component: harness/skill
- File: harness/skills/setup/SKILL.md
- Rationale: The setup skill is a harness/skill that scaffolds or configures agent repos; the missing --extra dev is a defect in the skill's install procedure, not in any agent's domain logic.

## Candidate 4: harness/skills/new-agent/SKILL.md Phase 5 step 1 runs uv venv --python 3.12 && uv sync --frozen (no --extra dev), then step 2 runs pytest. pytest/pytest-asyncio/httpx are only in the dev optional-dependency extra, so the green-baseline test step breaks on every freshly scaffolded agent.
- Severity: high
- Component: harness/skill
- File: harness/skills/new-agent/SKILL.md
- Rationale: new-agent is a harness/skill responsible for scaffolding new agents; the missing --extra dev is a defect in the skill's install step, not agent-domain code.

## Candidate 5: harness/.gitignore only matches paths relative to harness/ itself, not the agent repo root where /provision writes credential inventory files. The template/.gitignore seeded by /new-agent still lacks the ADR-001-*-credentials.md glob, so every scaffolded agent can silently commit credential files.
- Severity: high
- Component: security
- File: harness/.gitignore
- Rationale: Credential-protection gitignore globs are a security concern spanning scaffold skills (new-agent, setup) and the template seed; misplacement of the glob in harness/.gitignore leaves the real agent repos unprotected.

## Candidate 6: template/ is gitignored and fully untracked in a2a-sdk (commit e7bf0a1 stopped tracking it), so GH-70d's Creates/Modifies path under template/ can never be committed or propagated from this repo. The canonical Dockerfile lives in the separate wailuen/agent-template repo.
- Severity: high
- Component: harness/template
- File: template/Dockerfile
- Rationale: This is a wave-planning defect where the planner placed a todo target under a gitignored/untracked tree; it directly affects harness/template provenance and propagation, not agent-domain logic.

## Candidate 7: .claude/workflows/sdk-wave.js wave-parse prompt captures only Creates: paths into allCreates/group.creates. The empty-scope guard (line 267) false-aborts every legitimate modify-only wave, and unit/phase redteam scope plus protocol-audit detection are all derived from allCreates alone, silently skipping review for modify-only waves.
- Severity: critical
- Component: harness/workflow
- File: .claude/workflows/sdk-wave.js
- Rationale: sdk-wave.js is the SDK wave runner harness workflow; scope derivation from Creates-only is a structural defect in the wave orchestration engine.

## Candidate 8: .claude/workflows/wave-cycle.js and harness/workflows/wave-cycle.js both derive every scope set (unit/phase redteam, protocol detection, audit filters, seam paths, archive FR-map) from wave.allCreates/group.creates only, with no allModifies/allScope handling and no empty-scope guard. An edit-only agent wave lands with empty adversarial-review scope and no protocol audit — a silent gate bypass.
- Severity: critical
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: wave-cycle.js is the agent-wave counterpart to sdk-wave.js; the Creates-only scope defect is a harness/workflow structural issue that must be fixed in both runner copies.

## Candidate 9: harness/skills/setup/SKILL.md 'Create .gitignore (if absent)' block omits the workspace/adr/ADR-000-*-credentials.md and ADR-001-*-credentials.md globs mandated by LRN-050/GH-66, and has no git check-ignore verification probe. A clone whose .gitignore is missing the credential globs silently commits credential inventory files.
- Severity: critical
- Component: security
- File: harness/skills/setup/SKILL.md
- Rationale: Missing credential-protection globs in the setup skill's .gitignore block is a security defect in a harness/skill that must mirror the fix already applied to new-agent.

## Candidate 10: sdk-wave.js/wave-cycle.js archive step 2 only marks an existing plan.md row; when no row exists for the waveId (GH-issue waves have no pre-seeded row) the archive agent silently no-ops, leaving the wave invisible in the plan ledger. w020 is archived to completed/ but has no W20 row in plan.md.
- Severity: high
- Component: harness/workflow
- File: workspace/todos/plan.md
- Rationale: The archive step behaviour is defined inside sdk-wave.js and wave-cycle.js (harness workflows); the missing append-new-row logic is a defect in the wave runner's archive phase, not in agent-domain code.

## Candidate 11: .claude/workflows/wave-cycle.js null archive-commit gate response falls through to the else branch ('Commit check passed'), allowing wave archive even when the gate agent crashed and commit state is unknown — a fail-open regression of the null-gate fail-closed invariant. The harness copy already guards with if (!archiveIntent) { protocolBlocked = true }.
- Severity: critical
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Null-gate fail-open is a harness/workflow control-flow defect in the wave runner's archive gate; the fix must be ported from harness/workflows/wave-cycle.js to .claude/workflows/wave-cycle.js.

## Candidate 12: .claude/workflows/wave-cycle.js dispatches protocol recheck agents even after a red proto re-gate sets protocolBlocked=true, because there is no if (!protocolBlocked) guard around the recheck block at line 993. The harness copy correctly wraps the recheck in if (!protocolBlocked).
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Missing conditional guard around a protocol-recheck dispatch is a harness/workflow control-flow defect in the active wave runner.

## Candidate 13: The active runtime .claude/workflows/wave-cycle.js and template/distribution harness/workflows/wave-cycle.js have diverged across ~10 behaviours (null-gate hardening, deferred notes, recheck guard, archive row-append, etc.). Each copy has fixes the other lacks, making harness/CLAUDE.md's guarantee that harness/ is the propagation source false.
- Severity: high
- Component: harness/workflow
- File: .claude/workflows/wave-cycle.js
- Rationale: Divergence between the runtime and template wave-cycle.js copies is a harness/workflow maintenance defect; both are SDK-level orchestration files, not agent-domain code.
