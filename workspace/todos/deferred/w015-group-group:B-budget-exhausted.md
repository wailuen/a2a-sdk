# Deferred: w015 group:B — Budget Exhausted

- **Wave:** w015
- **Group:** group:B
- **Date:** 2026-06-15
- **Rounds completed:** 5 (budget exhausted)
- **Instruction:** Fix remaining findings, then re-run /wave w015

## Unresolved Findings

### WC-001 — high
**File:** harness/workflows/wave-cycle.js

LRN-012 Check clause fails: lines 887 and 889 still say 'Core 7 + Extended 11 = 18 total' in the A2UI advisor prompt, but DESIGN.md §5.4 and content_types.py define Core 6 + Extended 8 = 14 FROZEN + 4 RESERVED = 18 total. The wrong breakdown misleads the a2ui-advisor into checking for 7 core and 11 extended types instead of 6 and 8. LRN-012 was codified precisely to prevent this regression and its Check clause explicitly requires these three files to stay in sync.

**Fix:** Change line 887 comment to `// WC-RT-003: Core 6 + Extended 8 = 14 FROZEN; + 4 RESERVED = 18 total` and line 889 prompt text to `Core 6 + Extended 8 = 14 FROZEN Standard Profile types only (18 total including 4 RESERVED: TradeActivity, CompanyInfo, DealList, InvestorProfile — never emitted with an assumed shape)`. Apply identically to template/.claude/workflows/wave-cycle.js (which is byte-identical to harness).

**Codify:** LRN-012 Check clause must be run against harness/workflows/wave-cycle.js on every wave that touches the A2UI audit prompt; 'Core 7 + Extended 11' is the known-wrong formula — always verify against DESIGN.md §5.4.

**SDK Candidate:** yes

---

### WC-002 — high
**File:** harness/workflows/wave-cycle.js

Budget-exhausted break in both unit and phase redteam loops exits BEFORE accumulating the final round's critical/high findings into allHighFindings. Unit redteam: budget check at line 532 breaks before accumulation at line 579. Phase redteam: budget check at line 703 breaks before accumulation at line 739. As a result, when the fix-loop runs out of rounds, the last observed findings — the ones most likely to be hardest to fix — are silently dropped from the codify phase and never become LRN records. This is the pattern that caused GH #4–#8 regressions to slip through.

**Fix:** In both loops, move the allHighFindings accumulation block (the filter+push block) to immediately after curSigs and stalled are computed, before the budget-break check. The deferred-note write can remain where it is (after accumulation). Pattern: compute sigs → accumulate → budget-check → debug-escalate → fix → gate.

**Codify:** In wave-cycle.js fix loops, always accumulate critical/high findings into allHighFindings before any break path; budget exhaustion silently discards the final round's findings if accumulation is placed after the break check.

**SDK Candidate:** yes

---

### WC-003 — high
**File:** harness/workflows/wave-cycle.js

Phase redteam budget exhaustion (pRound >= 8, line 703–705) emits only a log message and breaks — no deferred note is written. Unit redteam budget exhaustion (uRound >= 5, lines 532–542) correctly writes a deferred markdown file to workspace/todos/deferred/ before breaking. This asymmetry means phase-level unresolved findings have no durable operator artifact; the only signal is a console log that is lost after the wave run. An operator resuming the wave has no record of what was unresolved at budget exhaustion.

**Fix:** After line 704 ('Phase round budget exhausted — continuing to Protocol Audit') and before the break, add an await agent() call that writes workspace/todos/deferred/{waveId}-phase-budget-exhausted.md including: waveId, date, pRound, the final rt.findings JSON, and the instruction 'Fix remaining findings, then re-run /wave {waveId}'. Mirrors the unit loop pattern at lines 535–541.

**Codify:** Phase redteam budget exhaustion must write a deferred note to workspace/todos/deferred/ — a console log is insufficient because it is not durable across wave retries.

**SDK Candidate:** yes

---

### WC-004 — medium
**File:** harness/workflows/wave-cycle.js

The findingsCount cross-validation guard (lines 516–519 and 687–689) only corrects the case where findingsCount=0 but findings.length > 0. The reverse case — findingsCount > 0 but findings.length = 0 (agent hallucinates a count without returning findings) — is not handled. In this case the loop does not break (findingsCount != 0), byFile is empty, fixTasks is empty, no fixes are dispatched, and the loop repeats with the same empty findings. Stall detection catches this at round 2 (empty sigs match), but wastes 2 rounds and one debug-agent call before escalating.

**Fix:** Add a guard after the existing WC-RT-004 check: `if (rt.findingsCount > 0 && rt.findings.length === 0) { log("WARNING: findingsCount=" + rt.findingsCount + " but findings array is empty — treating as empty"); rt.findingsCount = 0 }`. This prevents the spurious loop and expensive stall-detection cycle.

**SDK Candidate:** yes

---

### WC-005 — medium
**File:** harness/workflows/wave-cycle.js

WAVE_FILE (line 19) is assigned directly from args.waveFile with no null or undefined check. If the workflow is invoked without the waveFile argument (operator error, or a wave skill bug), WAVE_FILE is undefined. All subsequent uses in agent prompts produce the string 'undefined' — e.g. 'Read the wave file at: undefined'. The parse agent will likely return null (wave = null), triggering the early return at line 274, but the error log at line 275 will itself say 'could not parse wave file at undefined', which provides confusing operator diagnostics. The archive step at line 1301 would also embed 'undefined' in the archive instruction if somehow reached.

**Fix:** Add an early guard at line 19: `if (!WAVE_FILE) { log("ERROR: args.waveFile is required — provide an absolute path to the active wave file"); return { error: "missing-wave-file" } }`. This gives an actionable error before any agent is spawned.

**SDK Candidate:** no

---

### WC-006 — low
**File:** harness/workflows/wave-cycle.js

The early-exit return on parse failure (line 276) returns { error: 'parse-failed' } which has a different shape than the normal return at lines 1316–1328 (which includes waveId, totalTodos, lrnsCaptured, etc.). The /wave skill's execution step (Mode A step 3 in harness/skills/wave/SKILL.md) checks for protocolBlocked and sdkCandidates in the workflow result — these fields are absent from the error return. A caller that destructures the result without checking for error: first may silently misread a failed wave as having zero protocol findings and zero SDK candidates.

**Fix:** Either (a) return a full-shape object on parse failure with sentinel values (waveId: null, protocolBlocked: false, error: 'parse-failed') or (b) document in the SKILL.md that callers must check for result.error before reading other fields. Option (a) is safer.

**SDK Candidate:** no
