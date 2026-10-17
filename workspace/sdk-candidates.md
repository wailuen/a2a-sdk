# SDK issue candidates — w054 (2026-10-17)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: RT-001: The [Unreleased] CHANGELOG block has no GH-185 entry. The new public agent_sdk.auth.current_identity, its module auth/context.py, the bind sites (routes/a2a.py, routes/ag_ui.py, routes/mcp.py) and the ruling URL are all missing. tasks/memory.py and tasks/store.py are not named in the GH-187 Fixed entry.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: The SDK's own release notes miss a new public API and changed SDK files. This is release and build hygiene for the SDK, not agent code.

## Candidate 2: RT-002: The identity binds around _resume_or_error (A2A interrupt resume) and _open_stream (tasks/resubscribe) do nothing. deliver_resume hands work to a worker that is already running and kept the original submitter's context. So tools that run after a resume see the original submitter, not the caller who resumed. The test only checks the variable inside the route, never what a tool sees.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: This is the SDK's A2A route doing identity handoff wrong. Every agent built on the SDK will mislabel who resumed a task, for example when an admin key resumes another identity's task.

## Candidate 3: RT-003: The template copies of the add-tool and add-source SKILL.md files match the harness versions but are not committed or pushed in the template repo. The last template commit is 387dc73. Agents built from the template will not get the current_identity usage note.
- Severity: high
- Component: harness/template
- File: template/.claude/skills/add-tool/SKILL.md
- Rationale: The template scaffold is SDK-level delivery. The new guidance does not reach downstream agents until the template repo has the commit.

## Candidate 4: RT-001 (tests): GH-185 tests required by the plan are missing. (1) No test checks that a rejected or unauthenticated request leaves no bound identity (SI-5). (2) The leak checks run in the test's own context, so they pass whether or not the app unbinds, and A2A and AG-UI have no back-to-back request isolation test. (3) AG-UI resume and A2A message:stream resume binding are never tested.
- Severity: high
- Component: security
- File: tests/test_gh185_current_identity.py
- Rationale: These are SDK test gaps for an identity-isolation (security) feature, not agent tests. With the current tests, a leak of one caller's identity into the next request would go unnoticed.

## Candidate 5: RT-001 (race): When two callers resume at once, the loser wipes the winner's identity. _resume_or_error (a2a.py:537-540) and the AG-UI resume branch (ag_ui.py:723-729) set record.resume_identity before deliver_resume, then clear it to None if delivery fails. A losing second resumer clears the winner's identity, so the worker falls back to the original submitter. This was reproduced with two admin keys resuming at the same time.
- Severity: high
- Component: security
- File: agent_sdk/routes/a2a.py
- Rationale: This is a race in the SDK's A2A and AG-UI routes. Work gets credited to the wrong identity, which breaks the GH-185 ruling. It affects every agent.

## Candidate 6: RT-002 (store): The new public field TaskRecord.resume_identity is written on whatever object store.get() returns. The TaskStore contract allows a durable store whose get() returns a fresh copy each time. With such a store, the resume identity is silently lost. DESIGN.md section 5 does not say whether subclasses must keep this field.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/store.py
- Rationale: TaskRecord and TaskStore are exported SDK internals. Agents that plug in a durable store will silently lose the resume identity.

## Candidate 7: RT-003 (scope): runner.py changed (bind_identity import and the rebind in wait_resume), but the GH-185 todo lists it only under Reads, not Creates/Modifies. The G1 review scope and the CHANGELOG entry leave it out. The four existing tests changed for GH-187 are not declared in the GH-187 todo either.
- Severity: high
- Component: harness/workflow
- File: agent_sdk/agent/runner.py
- Rationale: This is a gap in how the SDK wave tracks scope. Changed SDK files escape review scope and release notes. The fix belongs in the wave planning and redteam process.

## Candidate 8: RT-004: The maintainer ruling (issues/185#issuecomment-6217407102) says tasks/resubscribe binds the caller's identity. The code (a2a.py:1122-1123) and the CHANGELOG skip it on purpose, because no tool runs on that path. The wave made this choice itself and the maintainer has not approved it.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: The SDK's A2A route departs from a recorded maintainer ruling. Under the self-signoff rule, the user must approve this before release. Otherwise the code must follow the ruling.
