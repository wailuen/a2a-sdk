# Deferred: w015 Group B — Budget Exhausted

- **Wave:** w015
- **Group:** B
- **Date:** 2026-06-15
- **Rounds completed:** 5 (budget exhausted)
- **Instruction:** Fix remaining findings, then re-run /wave w015

## Unresolved Findings

### WC-001 — high
**File:** harness/workflows/wave-cycle.js

Unit Redteam phase iterates groups sequentially (`for (const group of wave.groups)` at line 470) even though groups are independent after the Implement phase has already resolved their execution order. The design intent described in SKILL.md and the phase description is per-group zero-tolerance loops — there is no stated requirement that they run serially. Running N groups sequentially multiplies total redteam time by N with no correctness benefit, and the unit redteam explicitly scopes each loop to a single group's creates paths. The Implement phase already fans groups out by tier; the Unit Redteam should do the same for independent groups.

**Fix:** Replace the sequential `for` loop with a tier-based parallel dispatch that mirrors the Implement phase: collect groups with no unfinished peers (using `completedGroups` already tracked), run their unit-redteam loops concurrently via `parallel()`, then mark them done. For a first fix, wrapping the whole `for` loop in a single `parallel(wave.groups.map(...))` is safe because groups by definition operate on disjoint creates paths.

---

### WC-002 — high
**File:** harness/workflows/wave-cycle.js

Missing guard for `args.waveFile` being `undefined` or empty string at lines 19 and 253. When the caller omits the `waveFile` arg, `WAVE_FILE` is `undefined`, the parse agent receives `'Read the wave file at: undefined'`, and returns null. The error branch at line 274 logs `'could not parse wave file at undefined'` — a confusing message that obscures the root cause. The same problem affects `args.today` but that has a fallback. No validation is performed before the parse agent is dispatched.

**Fix:** Add an early guard immediately after lines 19-20: `if (!WAVE_FILE) { log('ERROR: waveFile arg is required — pass an absolute path to the active wave file'); return { error: 'missing-wave-file' } }`. This gives operators an actionable error instead of a silent parse failure.

---

### WC-003 — high
**File:** harness/workflows/wave-cycle.js

Critical/high findings are accumulated into `allHighFindings` (lines 579-582, 739-742) BEFORE the fix tasks are awaited and BEFORE the gate runs. If the gate fails and the unit or phase loop breaks early, findings that were already fixed (or partially fixed) in that round are still pushed into `allHighFindings` and will be codified as LRNs in phase 6. This produces duplicate or stale LRNs for findings that may have been resolved by the fix agent in the same round. The dedupe by `f.file + ':' + f.description` in phase 6 partially mitigates this but does not eliminate it — the same finding from multiple rounds accumulates once per unique key, even if it was resolved in round 1.

**Fix:** Move `allHighFindings.push.apply(allHighFindings, highFindings)` to AFTER `await parallel(fixTasks)` and AFTER a successful gate check. Only accumulate findings that survive at least one full fix+gate cycle without resolution. Alternatively, only accumulate findings from the final round (when `rt.findingsCount === 0` or budget exhausted), not from intermediate rounds that have already been fixed.

---

### WC-004 — high
**File:** harness/workflows/wave-cycle.js

Protocol audit recheck (lines 1077-1090) does not update `allHighFindings`. High-severity protocol findings discovered during the initial audit are pushed to `allHighFindings` via the map at lines 938-951 (only those with a `codify` field). But if the recheck (lines 1077-1090) surfaces new high-severity findings that were not in the initial audit, they are never accumulated and therefore never codified. `recheckResults` is used only to update `protoCritical` — the `protoHigh` equivalent is never computed from `recheckResults`, and `allHighFindings` is not extended with recheck findings.

**Fix:** After the `recheckResults` reduce at line 1078, add a parallel block to push recheck findings to `allHighFindings`: `const recheckHighFindings = recheckResults.reduce(...).filter(...codify...).map(...)` and `allHighFindings.push.apply(allHighFindings, recheckHighFindings)`. Also compute `recheckHigh` from `recheckResults` for logging.

---

### WC-005 — medium
**File:** harness/workflows/wave-cycle.js

The `testsBlockedArchive` flag is set to `true` at line 979 when `protoFixGate` returns null — a gate infrastructure failure, not a red test suite. But `testsBlockedArchive` is used at line 1287 to choose the archive-skip message: when true it says 'Fix failing tests and re-run'. A null gate response is not the same as a red test suite; the operator is told to fix failing tests when there may be no failing tests at all. The comment at line 972-974 acknowledges this issue but the message emitted at line 1292 (`'test suite RED'`) is still misleading when the root cause was a gate infrastructure failure.

**Fix:** Add a third flag `gateInfraBlocked` (or check `!preArchiveGate` in the archive block) to distinguish gate null-response from actual test failures. When `testsBlockedArchive` is true but `preArchiveGate` is null (or `protoFixGate` was null), emit `'archive BLOCKED — gate infrastructure failure (null response)'` instead of `'test suite RED'`. The existing `!preArchiveGate` branch at line 1289 already does this correctly for the pre-archive gate; the proto null-gate path at line 979 needs the same treatment.

---

### WC-006 — medium
**File:** harness/workflows/wave-cycle.js

The unit redteam loop does not set `testsRed = true` or block the pipeline when it exits via budget exhaustion (lines 532-543) or null-budget (lines 498-507). `testsRed` is only set when a gate returns non-zero or null. A group that exhausted 5 rounds with unresolved findings proceeds silently through Phase Redteam and Protocol Audit, and the wave can still archive if the phase redteam happens to return clean. The return object at line 1316 reports `testsRed: false` even though the unit redteam had unresolved findings — misleading the caller.

**Fix:** Set `protocolBlocked = true` (or introduce a new `unitRedteamExhausted` flag) when the unit redteam loop breaks via budget exhaustion or null-budget. Block archive in the same way critical protocol findings do, and include it in the return object. The deferred note is already written; the wave should not archive while known findings remain unresolved.

---

### WC-007 — medium
**File:** harness/workflows/wave-cycle.js

The `WAVE_SCHEMA` marks `lrnNext` as `required` and `type: 'integer'` but the parse agent prompt instructs `lrnNext: highest existing LRN number + 1` and `if none, lrnNext = 1`. An agent could return `lrnNext: 0` if no LRN files exist and it interprets `lrnNext = 1` incorrectly, or it could return the string `'1'`. The schema accepts any integer including 0. `lrnBase + i` with `lrnBase = 0` would generate `LRN-000` (padded to 3 digits). The schema should enforce `minimum: 1` to prevent `LRN-000` from being assigned.

**Fix:** Add `minimum: 1` to the `lrnNext` property in `WAVE_SCHEMA`: `lrnNext: { type: 'integer', minimum: 1 }`. Also add a runtime guard after the parse: `if (wave.lrnNext < 1) { log('WARNING: lrnNext=' + wave.lrnNext + ' is invalid — defaulting to 1'); wave.lrnNext = 1 }`.

---

### WC-008 — medium
**File:** harness/workflows/wave-cycle.js

The `redteam.md` agent specification (Dimension 1: Spec vs Code Alignment) requires reviewing `workspace/prd/` and `workspace/adr/` before starting. The unit redteam prompt at line 479 instructs the agent only to 'Run all 8 dimensions from agents/core/redteam.md' and provides the group's creates paths. It does not explicitly remind the agent to read CLAUDE.md, workspace/prd/, workspace/adr/, or workspace/learning/README.md before starting. The agent is expected to follow its own system prompt, but the wave-cycle prompt is the authoritative instruction at call time. The phase redteam at line 651 has the same gap. The implement prompt correctly reads CLAUDE.md and workspace/components/README.md first.

**Fix:** Prepend the redteam agent prompt with explicit read instructions: `'Before starting: read CLAUDE.md, workspace/prd/ (FRs for these creates paths), workspace/adr/ (accepted ADRs), workspace/learning/README.md (LRN checks), and workspace/components/README.md (component reuse check).'` This mirrors the redteam.md 'Before you start' section and ensures dimension 1, 7, and 8 are grounded in the project context.

---

### WC-009 — low
**File:** harness/workflows/wave-cycle.js

The `GATE_SCHEMA` uses `type: 'number'` (not `'integer'`) for `exitCode`, `passCount`, and `failCount` (lines 210-215). This allows fractional values (e.g. `exitCode: 0.5`, `failCount: 1.7`). The gate check at line 609 uses `!== 0` which is correct for non-integer exit codes, but `failCount` and `passCount` are presented as counts in log messages and a non-integer value would produce confusing output like '1.5 failing'. The `RT_SCHEMA` correctly uses `'integer'` for `findingsCount`.

**Fix:** Change `type: 'number'` to `type: 'integer'` for `exitCode`, `passCount`, and `failCount` in `GATE_SCHEMA`. This is a trivial schema tightening with no runtime impact on well-behaved agents, but it prevents confusing non-integer count values from slipping through schema validation.
