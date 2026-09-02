---
id: LRN-137
title: Unit Redteam reviewed groups one at a time despite planner-guaranteed disjoint scope — run concurrently with a gate mutex
category: harness
severity: medium
source: manual
date: 2026-09-02
---

## What happened
Multi-group waves were slow for a second, independent reason from LRN-136. Unit
Redteam's `for (const group of wave.groups) { while (true) {...} }` reviewed each
group's multi-round fix loop strictly one after another, even though groups are
guaranteed to touch non-overlapping files (the planner groups conflicting todos
together — the same guarantee the earlier `Implement` phase already relies on to run
independent groups concurrently via `parallel(readyGroups.map(makeGroupThunk))`). A
group needing 5 rounds fully blocked every other group from even starting its first
review, in both `wave-cycle.js` and `.claude/workflows/sdk-wave.js`.

## Root cause
Unit Redteam never got the same tier-parallel treatment Implement already uses. The
one real obstacle: each round's pytest gate (`python -m pytest -q`) reads the WHOLE
repo, not just one group's files — if two groups' fix batches landed at the same
moment, one group's gate could grade a neighbor's half-edited file and misattribute
the failure (LRN-017: the gate's `exitCode` must be the sole, unambiguous authority on
repo state, never uncertain about what it graded).

## Fix
In both `wave-cycle.js` (+ its two byte-identical mirrors, `.claude/workflows/` and
`template/.claude/workflows/`) and `.claude/workflows/sdk-wave.js`:
- The per-group loop body became `runUnitRedteamForGroup(group)`, fanned out via
  `parallel(wave.groups.map(...))` — mirroring Implement's own `makeGroupThunk` idiom.
- A promise-chain mutex (`gateLock` / `withGateLock(fn)`) serializes only the
  mutate-and-verify section of each round — debug → per-file fix agents → gate →
  (if red) fix-tests → re-gate — across all groups. The read-only redteam review call
  stays outside the lock, so one group can review while another is mid fix-and-verify.
  A stale review read of a neighbor's file mid-edit (via "transitive callers") is the
  same self-correcting risk Implement's tier-parallelism already accepts today — it
  produces a finding re-checked next round, never a wrong gate verdict.
- A disjointness guard runs before the parallel fan-out: every pair of groups' `scope`
  is checked for a shared path. If the planner's invariant is ever violated for a given
  wave, the guard logs a warning naming the groups and paths and falls back to the old
  one-group-at-a-time order for that wave, rather than trusting an unenforced
  assumption. (`sdk-wave.js`'s guard additionally treats a directory-prefix match as an
  overlap, matching the archive-commit gate's own three-way rule; `wave-cycle.js`'s
  guard checks exact-path equality only — sufficient today since `Creates:`/`Modifies:`
  entries are always file paths in this repo's wave-file convention, but the two
  guards are not identically strict. Worth tightening `wave-cycle.js`'s guard to match
  if that convention ever changes.)
- Round budgets (5), the round-4+/stall debug-escalation rule, and the gate always
  being a separate dedicated `agent()` call (never a fix agent's self-report) are
  unchanged — only the outer "one group at a time" → "concurrent, mutex-gated" fan-out
  and the disjointness guard are new.
- A group whose thunk throws mid-round now resolves to `null` under `parallel()`
  (matching how Implement already treats a failing group thunk) instead of aborting
  the whole phase; the fan-out logs a warning naming the aborted group so it is not
  mistaken for a clean exit.

Separately, `Codify`'s per-finding LRN-write fan-out (one dedicated agent per deduped
high/critical finding) was batched to ~5 findings per agent — each finding still gets
the exact `lrnBase + <its original index in toCodeify>` ID it would have received
one-per-agent, computed before batching so numbering never depends on batch position.

## Check
```bash
grep -n "withGateLock\|findScopeOverlaps\|scopeOverlaps" harness/workflows/wave-cycle.js .claude/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js .claude/workflows/sdk-wave.js
```
Each file must show the mutex and the disjointness guard immediately before Unit
Redteam's group fan-out, and `diff harness/workflows/wave-cycle.js
template/.claude/workflows/wave-cycle.js` must be empty (LRN-075).

## Prevention
A per-group review/fix loop must run concurrently across groups whenever the planner
already guarantees disjoint file scope for those groups — serializing it "to be safe"
just adds wall-clock with no added coverage, matching LRN-136's finding at the
whole-wave level. The only step that ever needs cross-group serialization is one that
reads or grades repo-wide state (a full-suite gate) — scope the lock to exactly that
step, never to the read-only review or the round budget/debug/stall logic (LRN-017,
LRN-076), and never trust the disjointness assumption without a runtime guard that
degrades to the old sequential order when it's violated.
