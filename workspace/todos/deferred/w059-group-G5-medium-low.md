# w059 — Group G5 deferred medium/low findings

- Wave: w059
- Scope: unit:G5
- Date: 2026-10-22

Non-blocking — these did not block w059's archive. Address opportunistically or fold into a future wave.

## RT-007 (medium) — harness/workflows/wave-cycle.js

- SDK candidate: yes
- Finding: Unit redteam skips held and pruned groups (unitGroups, line 1485), but Phase redteam (line ~1584) still reviews wave.allScope, which includes those groups' never-implemented paths. The phase redteam will report their absent files as critical gaps. Phase fix agents may then build the pruned work, which bypasses the prune and the HUMAN GATE hold, and the rounds are wasted.
- Fix: Build the phase scope from groups that are not held or pruned (and run rescan additions through the same filter), or skip Phase Redteam with a log line when deliverablesBlocked is set. Add a test that a held group's paths are absent from the rt:phase prompt.

## RT-008 (low) — harness/workflows/wave-cycle.js

- SDK candidate: yes
- Finding: When the scope re-scan fails on every round, redteamFixLoop writes its budget note as '<stem>-rt-null-budget.md' (rt is null because the review was skipped). The note is labelled as a redteam failure when the real cause was the scope scan.
- Fix: Use a separate suffix and label for scan failures, e.g. '-scope-scan-null-budget.md' and 'defer:<base>:scope-scan-null-budget'.

## RT-009 (low) — CHANGELOG.md

- SDK candidate: yes
- Finding: The GH-208 entry says pattern paths 'need a match newer than Implement start'. That is not true in practice (see RT-002 and RT-003). The entry also does not name all the files changed: .claude/workflows/wave-cycle.js, .claude/agents/core/planner.md, .claude/skills/todos/SKILL.md, .claude/skills/wave/SKILL.md and the template mirrors (LRN-433).
- Fix: Correct the pattern-path claim once RT-002/RT-003 are fixed. List every changed path in the GH-208 bullet.
