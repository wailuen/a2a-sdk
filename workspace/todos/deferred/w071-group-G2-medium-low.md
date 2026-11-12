# w071 — deferred medium/low findings (unit:G2)

- Wave: w071
- Scope: unit:G2
- Date: 2026-11-10

Non-blocking — these did not block w071's archive. Address opportunistically or fold into a future wave.

## RT-001 — medium — harness/workflows/wave-cycle.js:1562

Quote: `  doneReady.forEach(function(g) { log('Group ' + g.label + ': all todos done — no implementer dispatched') })`

The GH-278 ruling (item 1) and the todo AC say skipped [x] todos are logged by id. The runner only does this for a mixed group (inside the dispatchReady map). A group whose todos are all [x] logs only its group label, and the auto-resume and resumeAt paths (line 1171) log no todo ids at all. Test (1) covers only the mixed case, so nothing guards the gap. The same gap is in .claude/workflows/sdk-wave.js:1557, .claude/workflows/wave-cycle.js and template/.claude/workflows/wave-cycle.js.

Fix: In the doneReady loop, also log `Todo <id> already done [x] — skipped, not re-implemented` for each todo in g.todos. In the resume block, log the same line for every live todoFacts entry with done === true. Make the change in all four runner copies. Add RUNNERS-parametrized tests for an all-[x] group and for both resume paths that assert each [x] id is logged with 'skipped'. The tests must fail if the per-id log is removed (LRN-560).

Codify: A ruling that says 'logged by id' must be tested on every path that skips work: mixed group, done group and resume. Testing one path is not enough.

SDK candidate: yes

## RT-002 — medium — harness/workflows/wave-cycle.js:1171

Quote: `if (RESUME_AT === 'archive' || allTodosDone(preflight.todoFacts)) {`

Auto-resume starts whenever every todo is [x] or [~]. On that path the only gates are the test suite (pre-archive) and the commit check (archive-commit). Implementers tick [x] during the run, so a wave whose earlier archive was blocked only by redteam or protocol-audit results (unitBudgetBlocked, phaseBudgetBlocked, redteamUnknownBlocked, fixLoopTestsBlocked, protocol findings) gets archived by a plain re-run. Nothing checks that the deferred -budget-exhausted.md, -rt-null-budget.md or -tests-red-*.md notes were fixed. Those 'Archive SKIPPED' messages tell the developer to 'fix ... then re-run /wave', and the re-run no longer checks the fix. The ruling allows skipping redteam, but the SKILL.md hunk does not warn about this, and no check stops a wave with open critical/high findings from closing. Same in .claude/workflows/sdk-wave.js:1166.

Fix: Do not change the ruled gate set without the maintainer. File a follow-up issue asking for a ruling on a deterministic pre-resume check. The check would refuse auto-resume (or keep protocolBlocked set) while workspace/todos/deferred/<waveId>-*-budget-exhausted.md, -rt-null-budget.md, -rt-mismatch-budget.md or -tests-red-*.md files with OPEN findings exist. Until then, add a sentence to the three wave SKILL.md hunks: a re-run after a redteam or protocol block archives without re-review, so fix and verify the deferred findings first.

Codify: A resume shortcut that skips review gates must check the deferred notes those gates left behind. If it does not, 're-run after fixing' turns into 're-run to bypass'.

SDK candidate: yes

## RT-003 — low — CHANGELOG.md:10

Quote: the GH-278 bullet ("- GH-278: a wave re-run after a blocked archive no longer re-implements `[x]` todos. ... Files: `harness/workflows/wave-cycle.js` and its two byte-identical copies, `.claude/workflows/sdk-wave.js`, the three `wave` `SKILL.md` copies. Tests: `tests/test_wave_cycle_behaviour.py`.")

The wave header requires each CHANGELOG entry to name every changed agent_sdk/ or harness/ file by full repo path (LRN-491). The GH-278 bullet names `harness/skills/wave/SKILL.md`, `.claude/skills/wave/SKILL.md`, `.claude/workflows/wave-cycle.js` and the template/ copies only as 'its two byte-identical copies' and 'the three wave SKILL.md copies'. The GH-279 bullet does the same.

Fix: Replace the collective phrases with full paths: `harness/workflows/wave-cycle.js`, `.claude/workflows/wave-cycle.js`, `template/.claude/workflows/wave-cycle.js`, `.claude/workflows/sdk-wave.js`, `harness/skills/wave/SKILL.md`, `.claude/skills/wave/SKILL.md`, `template/.claude/skills/wave/SKILL.md`. Do the same in the GH-279 bullet, adding the three planner.md paths.

SDK candidate: yes

## RT-004 — low — harness/workflows/wave-cycle.js:49

Quote: `if (RESUME_AT !== undefined && RESUME_AT !== 'archive') throw new Error('invalid arg — resumeAt (allowed: archive)')`

resumeAt is documented as optional, but an explicit `resumeAt: null` (common when a caller serialises an unset optional field in JSON args) fails fast as an invalid value. The documented 'absent' state only accepts undefined. Same in .claude/workflows/sdk-wave.js and the mirrors.

Fix: Treat null like undefined: `if (RESUME_AT !== undefined && RESUME_AT !== null && RESUME_AT !== 'archive') throw ...`. Keep the fixed no-echo error text. Update the C-069 guard-parity test so the line stays identical in every runner, and add a null case to test_bad_resume_at_fails_fast_without_echo's sibling.

SDK candidate: yes

## RT-005 — low — harness/workflows/wave-cycle.js:733

Quote: `    'defer:held:' + hg.label, 'Implement'`

holdGroup always tags the held-group deferred-note call with phase 'Implement'. The new resume paths call it from the Parse phase, before phase('Archive') runs, so on resume the -held.md write is shown under a phase that never ran. Same in .claude/workflows/sdk-wave.js:740 and the mirrors.

Fix: Pass the phase into holdGroup(hg, phaseName): 'Implement' from the tier loop and 'Archive' (or lastDispatchedPhase) from the resume block. Apply in all four runner copies.

SDK candidate: yes

Resolved 2026-11-12: all findings fixed by hand before release.
