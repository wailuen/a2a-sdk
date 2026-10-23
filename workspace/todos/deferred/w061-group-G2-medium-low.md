# w061 — unit:G2 — deferred medium/low findings

- Wave: w061
- Scope: unit:G2
- Date: 2026-10-23

Non-blocking — these did not block w061's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — harness/workflows/wave-cycle.js:515 — sdkCandidate

Quote: `  'BOUND=r"\\s*(?:[-*]\\s*)?(?:#{1,6}\\s|\\[.\\])"',`

[SDK] The new per-todo scan (TODO_SCOPE_SCAN_PY) only starts a new todo on a '-' or '*' checkbox line. TODO_SCAN_PY also accepts a '+' bullet (`^\s*[-*+]\s*\[(.)\]`). So for a todo written as `+ [ ] `B-1``, the per-todo scan gives every one of B-1's paths to the todo before it. Confirmed: a fixture with A-1, then `+ [ ] `B-1`` declaring src/b_plus.py, returns {todoId: 'A-1', path: 'src/b_plus.py'}, while TODO_SCAN_PY lists B-1 as its own todo. rescanScope would then quietly put a path added mid-run into A's group — the exact wrong-group bug GH-228 fixes; the AC says such paths are 'never folded into the PREVIOUS todo'. Same code in .claude/workflows/sdk-wave.js and the .claude/ and template/ copies of wave-cycle.js.

Fix: In TODO_SCOPE_SCAN_PY, check TODO.match(l) (accepts [-*+]) before the BOUND test. A matching '+' checkbox line flushes the buffer and sets cur to its id, but leaves skip unchanged (keeps the path set equal to SCOPE_SCAN_PY, whose BOUND does not reset on '+' lines). Add a '+ [ ] `B-1`' case to the _OWNER_WAVE fixture in tests/test_wave_scope_extraction.py and assert the path's todoId is 'B-1'. Same change in sdk-wave.js; sync .claude/ and template/ copies.

Codify: The per-todo owner scan must use the same todo-start regex as TODO_SCAN_PY, or Parse's todo ids and the scan's owners drift apart and paths go to the wrong group.

## RT-002 (medium) — harness/workflows/wave-cycle.js:2447 — sdkCandidate

Quote: `    log('Archive SKIPPED — wave ' + wave.waveId + ' blocked by the protocol audit or the commit check (see BLOCKED lines above)')`

[SDK] When finalScopeRescan fails (at final-pre-audit or final-pre-archive), it sets protocolBlocked but no flag of its own. The archive-skipped summary then reaches this catch-all else branch, telling the developer the protocol audit or commit check blocked the wave and to run /agent-verify — the wrong remedy. The comment above this block says 'Name the actual cause; a misdirected remedy wastes developer time'. Same in .claude/workflows/sdk-wave.js.

Fix: Add a `scopeRescanBlocked` flag next to the other block flags; set it in finalScopeRescan when the result is not true. Add a summary branch: 'Archive SKIPPED — final scope re-scan (scan:scope:final-pre-audit|final-pre-archive) returned no trustworthy result; see the scope re-scan lines above, fix the wave file's Creates:/Modifies: lines, re-run /wave <id>'. Extend test_gh228_untrustworthy_final_rescan_blocks_archive to assert that line appears and the /agent-verify line does not. Same in sdk-wave.js; sync copies.

Codify: Every new archive-blocking cause needs its own flag and summary branch, or the catch-all branch reports a misleading cause.

## RT-003 (medium) — harness/workflows/wave-cycle.js:1284 — sdkCandidate

Quote: `      log('scope re-scan: path ' + p + ' has no owning todo — wave BLOCKED' +`

[SDK] In the per-round rescans (unit and phase loops), an unowned path or a flat/per-todo mismatch gives the same answer every round: no fix agent runs between rounds (the round is skipped before review), so the wave file cannot change. Yet redteamFixLoop retries the scan up to UNIT_MAX_ROUNDS per group (PHASE_MAX_ROUNDS for phase), spending agent calls each time, then records outcome 'unknown', writes a '-rt-null-budget.md' note, and the final summary says 'redteam never returned a trustworthy verdict (persistent null response or findingsCount mismatch)'. The real reason appears only in repeated per-round log lines. Same in .claude/workflows/sdk-wave.js.

Fix: Have rescanScope return a reason, e.g. {ok:false, reason:'unowned'|'mismatch'|'null'}. In redteamFixLoop, 'unowned' or 'mismatch' ends the loop at once: set protocolBlocked and a scope-specific flag, write a deferred note naming the path or mismatch. Do not retry to budget or route through the rt-null-budget note/summary. Add behaviour tests asserting the scan runs once and the summary names the unowned path.

Codify: A fail-closed check whose input cannot change between rounds should stop the loop at once with its own reason, not retry to budget and get reported as a null redteam.

## RT-004 (medium) — harness/workflows/wave-cycle.js:1293 — sdkCandidate

Quote: `      const mine = t.kind === 'create' ? t.g.creates : t.g.modifies`

[SDK] rescanScope now adds new paths to g.creates, g.modifies, wave.allCreates and wave.allModifies, but nothing reads those lists after the first rescan. The only reader of g.creates is checkDeliverables, called only inside the Implement tier loop (line 1434), before any rescan. So a Creates: path declared mid-run, or found by the two final rescans, is never checked to exist. The create/modify choice has no visible effect, and no test checks which list a path lands in. The GH-228 AC 'rescanScope also widens g.creates, wave.allCreates and wave.allModifies' is met only as unused state. Same in .claude/workflows/sdk-wave.js.

Fix: In finalScopeRescan, run checkDeliverables over groups that gained create paths; a missing file sets protocolBlocked, same rules as Implement. Add a behaviour test: a final-pre-archive rescan adds {path, kind:'create'} for a nonexistent file and the archive is blocked by the deliverable check; a kind:'modify' row for the same path does not block. If no reader is wanted, drop the bucket code and amend the AC.

Codify: A list a fix widens must have a reader after the point where it is widened, and a test that observes it; otherwise the AC is met only on paper.

## RT-005 (low) — harness/workflows/wave-cycle.js:535 — sdkCandidate

Quote: `  '        cur=None if re.match(HEAD,l) or not m else m.group(2).strip()',`

[SDK] A nested checklist line inside a todo body, such as `  - [x] AC: sub step done`, sets the owner to null for the rest of that todo, while TODO_SCAN_PY treats it as body. Confirmed: in a fixture where `C-1` has a nested `- [x]` line then `- Modifies: src/c_late.py`, the path gets todoId null, so a mid-run path after any nested checkbox is 'unowned' and the whole wave blocks. The AC text ('any checkbox line') asks for this, but conflicts with the same AC's 'TODO_SCAN_PY todo boundaries'.

Fix: Only reset the owner on a checkbox line not indented more than the current todo's checkbox line, or one TODO.match() accepts (keeps the reset for a top-level `- [ ] GH-300`). A nested sub-item keeps `cur` (may still update `skip` for parity with the flat scan). Add a nested-checkbox case to _OWNER_WAVE. Or record a maintainer ruling that nested checkboxes block on purpose.

## RT-006 (low) — harness/workflows/wave-cycle.js:617 — sdkCandidate

Quote: `SCOPE_RESCAN_SCHEMA.required = ['paths', 'rows']`

[SDK] SCOPE_RESCAN_SCHEMA is an object literal with `required: ['paths']` and no `rows` field; two statements later the code replaces `required` and adds `properties.rows`. A reader of the literal sees the wrong contract; no test depends on the old literal. Same in .claude/workflows/sdk-wave.js.

Fix: Put `required: ['paths', 'rows']` and the `rows` property inside the literal; delete the two mutating statements. Sync sdk-wave.js and the .claude/ and template/ copies.

## RT-007 (low) — harness/workflows/wave-cycle.js:1254 — sdkCandidate

Quote: `async function rescanScope(base, round, group, phaseName) {`

[SDK] rescanScope no longer uses its `group` parameter (its own comment says so), yet the unit-loop caller passes `group` and finalScopeRescan passes `null`. A reader might think the calling group still affects which group gets a new path, which GH-228 deliberately removed. Same in .claude/workflows/sdk-wave.js.

Fix: Remove the `group` parameter from rescanScope and all three callers (unit rescan, phase rescan, finalScopeRescan), and the 'group is unused' comment. Sync every copy.
