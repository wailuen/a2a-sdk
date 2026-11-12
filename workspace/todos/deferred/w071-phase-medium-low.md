# w071 — phase redteam: deferred medium/low findings

- Wave: w071
- Scope: phase
- Date: 2026-11-10

Non-blocking — these did not block w071's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — `harness/workflows/wave-cycle.js:1039`

> `if (!/^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+$/.test(id) || !/\d/.test(id)) continue`

- Description: [SDK] The new dangling-depends check only looks at backticked tokens shaped like `AB-12`. deriveGroupDeps still honours unbackticked ids (`Depends: P0-01`, the form most files in workspace/todos/completed/ use), so a mistyped unbackticked id, or a backticked id without a hyphen (`T1`, `GH278`), is still dropped without any warning. That is the GH-279 root cause, left open for those formats. The same line is in .claude/workflows/sdk-wave.js:1046 and the byte-identical wave-cycle.js copies.
- Fix: Find dependency ids the same way deriveGroupDeps does. For each todo that will still run, take every token in its Depends: text that looks like an id, backticked or not (for example `\b[A-Za-z]+\d*(?:-[A-Za-z0-9]+)+\b`, minus `(none)`), and stop with dangling-depends when the token is not a known live id. If that is too strict, stop with dangling-depends on any Depends: line that has text but no backticked id. Add a test with an unbackticked missing id and a hyphen-free id, run against every runner in RUNNERS.
- Codify: A dependency check has to cover every id format the dependency resolver accepts; otherwise the silent-drop bug survives for the formats it skips.
- SDK candidate: yes

## RT-002 (medium) — `harness/workflows/wave-cycle.js:517`

> `'    out.append([cur["id"],cur["grp"],cur["skip"],dep])',`

- Description: [SDK] The freeze fingerprint leaves out each todo's HUMAN GATE / Release state. A HUMAN GATE marker added to the wave file mid-run, which is the only way a person can stop a todo, is ignored without any warning. It does not trip wave-file-changed, the hold was computed once at Parse, and the wave can go on to archive past the new gate (on the tier-loop, auto-resume and resumeAt paths). This is the GH-279 'mid-run edits silently ignored' problem, applied to holds.
- Fix: Add the held flag (GATE matched and REL not matched, the same expression TODO_SCAN_PY uses) to each FREEZE_SCAN_PY tuple in every runner copy. Adding or releasing a gate mid-run then stops the run with wave-file-changed, and the next run picks up the new state. Update the GH-279 AC/SKILL.md text and add a test (14) case: adding a HUMAN GATE line changes the hash.
- Codify: A mid-run freeze must cover every wave-file field that decides whether work may proceed, including HUMAN GATE holds, not only the fields that decide scheduling.
- SDK candidate: yes

## RT-003 (medium) — `harness/workflows/wave-cycle.js:1171`

> `if (RESUME_AT === 'archive' || allTodosDone(preflight.todoFacts)) {`

- Description: [SDK] The auto-resume and resumeAt paths skip the Creates: deliverable gate completely, but the partial-resume path does gate done groups (deliv:tier<N>:done). Picture a wave whose previous run was blocked because a group's Creates: files were missing (deliverablesBlocked), even though its todos were ticked [x]. On re-run it resumes at archive, and no step checks that those files exist: the archive-commit gate only checks that scope files are committed. SKILL.md:133 says the archive gates still check [x] paths, which this path does not do.
- Fix: On the resume path, before freeze:pre-archive, run `checkDeliverables(wave.groups.filter(g => !groupIsHeld(g)), 0, 'deliv:resume')` through the same CREATES_GATE. If any group fails, add it to failedGroups and set deliverablesBlocked and protocolBlocked, so archive is skipped as in the tier loop. Add a test: all-[x] wave with a missing concrete Creates: file is not archived, for every runner in RUNNERS. Since the GH-278 ruling lists only the pre-archive gate, the archive-commit gate and archive, raise this with the maintainer rather than overriding the ruling.
- Codify: Resume shortcuts must keep every fail-closed deliverable check the normal path applies to the same done work, or a previously blocked wave archives on re-run.
- SDK candidate: yes

## RT-004 (low) — `harness/workflows/wave-cycle.js:1176`

> `for (const hg of wave.groups.filter(groupIsHeld)) await holdGroup(hg)`

- Description: [SDK] On the resume path the freeze:pre-archive check runs before the holdGroup deferNote agents, and runArchive(true) then skips its own freeze check. Agents are dispatched between the freeze check and gate:pre-archive, so the check is not 'right before gate:pre-archive' as the GH-279 AC says, and an edit made during that window is not caught. The freeze agent also inherits phase 'Parse' from lastDispatchedPhase.
- Fix: Run the holdGroup loop first. Then call runArchive() without the freezeChecked flag, so its own checkFreeze('freeze:pre-archive') runs right before gate:pre-archive on every path. After that, remove the freezeChecked parameter.
- Codify: A freeze check promised to run right before a gate must have no agent dispatch between it and that gate.
- SDK candidate: yes

## RT-005 (low) — `tests/test_gh152_idp_off_regression.py:122`

> `assert sorted(body) == GOLDEN_TOKEN_KEYS`

- Description: [SDK] GH-277 test (6) is meant to show that token response bytes are unchanged with IdP off. It only compares the key set and checks that the word 'label' is absent. A change to token_type, expires_in, a header, or the value encoding would still pass.
- Fix: Pin the full response shape: token_type == 'Bearer', expires_in equals the configured access TTL, both tokens are non-empty strings, and the content-type and cache-control headers (no-store) match their values before the change.
- SDK candidate: yes

## RT-006 (low) — `CHANGELOG.md:10`

> Files: `harness/workflows/wave-cycle.js` and its two byte-identical copies, `.claude/workflows/sdk-wave.js`, the three `wave` `SKILL.md` copies.

- Description: [SDK] The wave header requires every changed agent_sdk/ or harness/ file to be named by full repo path. The GH-278/GH-279 bullets instead say 'the three wave SKILL.md copies' and 'the three planner.md copies', so harness/skills/wave/SKILL.md and harness/agents/core/planner.md (and the .claude/ copies) are never named.
- Fix: List harness/skills/wave/SKILL.md, .claude/skills/wave/SKILL.md, harness/agents/core/planner.md, .claude/agents/core/planner.md and .claude/workflows/wave-cycle.js by full path in the GH-278/GH-279 bullets.
- SDK candidate: yes

Resolved 2026-11-12: all findings fixed by hand before release.
