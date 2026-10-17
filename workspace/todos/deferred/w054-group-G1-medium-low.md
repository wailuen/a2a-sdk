wave: w054
group: G1
date: 2026-10-17

Non-blocking — these did not block w054's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.
All findings are SDK-level (sdkCandidate: true). Context: GH-185 (request-scoped `agent_sdk.auth.current_identity()`,
bound on A2A/AG-UI/MCP routes and rebound to the resuming caller) and GH-187 (contextId continuation selects
COMPLETED tasks only, so a retry after a FAILED/CANCELED turn starts clean).

Note on ordering: later rounds show the resume hand-off moved to a `ResumeEnvelope` passed through
`deliver_resume` (agent_sdk/auth/context.py, unwrapped in runner.py wait_resume). RT-007 and RT-010 below were
raised against the earlier `TaskRecord.resume_identity` design; check whether that field still exists before
acting on them.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/tasks/store.py (also DESIGN.md, docs/tools.md, docs/deployment.md, agent_sdk/tasks/memory.py, agent_sdk/routes/ag_ui.py, workspace/components/README.md)
- description: Raised in all four rounds. GH-187 changed context_messages()/context_reusable_messages() to select COMPLETED tasks only, but contract and rationale text still says candidates come from TERMINAL_STATES / "every terminal task", or that a CANCELED task becomes a continuation candidate (now false). Stale places: store.py class docstring ~:143-149 (a CANCELED status not persisted means the TERMINAL_STATES filter never finds it), persist_messages ~:356-361, persist_status ~:446-455, "Returns an empty list when no prior terminal task exists" (both methods), the context_reusable_messages body ("scans every terminal task"); memory.py ~:296-299 (the "hit max_turns" fallback example ends FAILED and is never selected now); DESIGN.md §5.2 :309, :311, :317, :493-495; docs/deployment.md "Custom TaskStore durability" :69-74 and :114-122; docs/tools.md :237-263; routes/ag_ui.py comment ~:741; the C-005 registry entry in workspace/components/README.md. The "override persist_messages and persist_status together" rationale now gives durable-store authors a false reason.
- fix: Change every listed passage to "most recent COMPLETED task" / "COMPLETED tasks only (GH-187)". Restate the persist_status rationale around COMPLETED (a durable store that never learns a COMPLETED transition never seeds continuation; the durable status must also be right after restart) and drop the CANCELED example. Replace the max_turns example in memory.py with a COMPLETED-task case that has no turn boundary.
- codify: A change to which tasks a TaskStore read selects must grep DESIGN.md, docs/ and store.py docstrings for the old filter name (TERMINAL_STATES near context_messages) and update every hit in the same wave — the rationale for other hooks often depends on it.

### RT-002
- severity: medium
- file: CHANGELOG.md (also docs/deployment.md, workspace/components/README.md)
- description: Raised in two rounds. The TaskStore contract change (context_messages/context_reusable_messages must now filter to COMPLETED) is filed under `### Fixed` with no note for external durable TaskStore subclasses (e.g. agent-repo AzureTableTaskStore). A subclass that overrides these methods inherits nothing and silently keeps the GH-187 bug. The ruling says every TaskStore implementation, in-memory and durable, must change; external stores can only learn this from CHANGELOG and docs. C-005 itself sets the "Note for TaskStore subclassers" precedent.
- fix: Add a "Note for TaskStore subclassers" line (or a Behavior changes entry, per this CHANGELOG's heading convention) to the GH-187 entry: custom `context_messages`/`context_reusable_messages` overrides must filter on `TaskState.COMPLETED`, not `TERMINAL_STATES`. Add the same rule to docs/deployment.md "Custom TaskStore durability" and to the C-005 registry entry.

### RT-003
- severity: medium
- file: tests/test_rt002_context_messages_max_turns_cliff.py (also CHANGELOG.md, DESIGN.md, docs/deployment.md)
- description: Raised in two rounds. A task that runs out of max_turns ends as DoneEvent(ok=False, summary=...), committed as FAILED (runner.py:1433-1443, loop.py:1812 "max turns exceeded"). Under GH-187 its whole multi-turn transcript, and the summary the user saw, is dropped from contextId continuation. The CHANGELOG trade-off names only "a model 429 after a tool round" and a bare "try again"; it does not say a "continue" after a max-turns stop now starts from nothing. The RT-002 test hides this: `_complete()` (~line 72) now stamps a run_loop-exhausted transcript (2*max_turns+2 messages, ok=False) as COMPLETED, a state production never produces for that shape, while its docstring still describes "a task that never finishes". DESIGN.md:317 and docs/deployment.md:114-131 still tell operators who raise AGENT_SDK_MAX_TURNS to expect the fallback warning routinely, which is now wrong guidance.
- fix: Add a second sentence to the CHANGELOG GH-187 trade-off: tasks that fail by exhausting AGENT_SDK_MAX_TURNS (including their summary) are no longer carried into the next turn. Rebuild the RT-002 fixture as a realistic COMPLETED long task (more than 24 tool rounds, then a final assistant reply, so the only user boundary is still index 0), or say in the helper's docstring that the state is synthetic. Update the test docstring, DESIGN.md §5.2 :317, docs/deployment.md and the memory.py/store.py RT-002 docstrings to name that shape and to say max_turns-exhausted tasks are FAILED and never seeded. If the maintainer did not mean to drop max-turns runs, raise it on GH-187 for a ruling. Do not self-ratify it.
- codify: When a selection filter narrows, re-check every test fixture that forces a status by hand: if the forced status no longer matches what production produces for that transcript shape, the test pins an unreachable scenario.

### RT-004
- severity: medium
- file: DESIGN.md
- description: Raised in three rounds. The new public API agent_sdk.auth.current_identity() (exported in agent_sdk/auth/__init__.py __all__, the reason this release is 0.16.0) is missing from DESIGN.md. It has no §4.0 stability tier, and neither §4 Public API nor §6 / §5.5 auth record: request-scoped via ContextVar; bound only after Depends(require_identity) on message:send, message:stream, /ag-ui/run, POST /mcp and /mcp/messages; rebound to the resuming caller on resume (ResumeEnvelope rebind in wait_resume); not bound on tasks/resubscribe; None outside a request (admin try-tool, scheduler, commitments, sync_reply); never logged (SI-2).
- fix: Add a §4 Public API entry for `agent_sdk.auth.current_identity() -> Identity | None` with its §4.0 tier, plus a §6 (Auth and credentials) bullet covering the bind sites, resume semantics, None cases and the never-logged rule.
- codify: Every new symbol added to a public __all__ needs a DESIGN.md §4 entry and §4.0 tier line in the same wave (extends LRN-293).

### RT-005
- severity: medium
- file: agent_sdk/routes/admin.py (also docs/tools.md, harness/skills/add-tool/SKILL.md, harness/skills/add-source/SKILL.md)
- description: Raised in two rounds. POST /admin/api/tools/{name}/try (~line 572-592) runs a tool through `entry.invoke_any` inside an authenticated admin request but never binds the identity, so `current_identity()` returns None there — contradicting docs/tools.md ("returns the caller's frozen Identity inside a tool ... or None outside a request"). The same holds for the contrib commitments executor firing per-owner commitments (contrib/commitments/executor.py:140), the scheduler, and the A2A sync_reply hook. Meanwhile the documented example (docs/tools.md:94-95: `owner = who.principal_key if who else "anonymous"`) and the add-tool/add-source SKILL notes teach a fail-open fallback, so per-user scoping built from it puts every such call into one shared "anonymous" bucket.
- fix: Bind the admin Identity around `invoke_any` in try_tool (resolve it with `Depends(require_admin)` as a parameter, bind, unbind in finally, as the MCP route does). Change the docs and skill example to fail closed: raise AgentError(ErrorCategory.AUTH, ...) when current_identity() is None and per-user scoping is required. List the remaining None paths explicitly in docs/tools.md and DESIGN.md §6.
- codify: A request-scoped identity accessor's doc example must fail closed on None, and must list every SDK path that runs tool code without a bound identity.

### RT-006
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: After a resume, wait_resume (runner.py:1251-1254) rebinds current_identity() to the resumer, but forwarded credentials stay bound from the original submit (a2a.py:461-465, forwarding.bind in _start_worker). TaskStore.get gives an admin api_key access to any identity's task (memory.py:185), and test_resume_binds_resuming_caller exercises an admin resume. In that case tools after the resume see identity=admin while calling upstream with user X's forwarded vendor key: per-user audit charges a paid call to the wrong principal, and per-user data written after the resume lands in admin's scope for a task owned by X. Neither docs/tools.md nor the CHANGELOG states this split.
- fix: Document the identity/credential split in docs/tools.md, the CHANGELOG entry and the _start_worker comment. Raise it to the maintainer for a ruling on whether an admin resume should also rebind forwarded credentials, or keep the submitter's identity for attribution. Do not self-ratify.
- codify: When two request-scoped context values are carried into a worker, any rebind path must rebind both together or document the mismatch.

### RT-007
- severity: medium
- file: agent_sdk/routes/a2a.py (also agent_sdk/routes/ag_ui.py)
- description: Raised against the earlier design (see ordering note). record.resume_identity was set BEFORE deliver_resume and reset to None when delivery failed (a2a.py:537-540, ag_ui.py:723-729). Race: caller A delivers a resume; before the worker runs, caller B passes the INTERRUPT_STATES check, sets resume_identity=B, deliver_resume returns False, and B resets resume_identity to None, wiping A's value. The worker wakes in wait_resume, sees None, skips the rebind, and tools after the resume see the original submitter instead of the resuming caller.
- fix: Confirm the ResumeEnvelope change (identity carried inside the value handed to the resume future, unwrapped in wait_resume) fully replaced the staged field and the reset-on-failure branch in both routes. If any staging remains, write it only after deliver_resume returns True and delete the reset branch. Add a concurrent-resume test (see RT-012).
- codify: Never stage per-request data on a shared record before a racy hand-off and then "undo" it on failure; a losing racer's undo clobbers the winner — write it only after the hand-off succeeds or pass it through the hand-off itself.

### RT-008
- severity: medium
- file: agent_sdk/tasks/store.py
- description: The abstract TaskStore.deliver_resume(task_id, value) contract (store.py:273) changed in practice. A2A and AG-UI resumes now pass a ResumeEnvelope dataclass instead of a bare str or dict, and runner.py wait_resume unwraps it only via isinstance. The ABC docstring, DESIGN.md and the CHANGELOG do not mention this. ResumeEnvelope lives in agent_sdk/auth/context.py and is not exported. An external durable store that serializes or validates the resume value breaks (the dataclass is not JSON-serializable); one that reconstructs a plain value silently loses the resumer-identity rebind.
- fix: Document in the deliver_resume docstring, DESIGN.md §5.2 and the CHANGELOG Added entry that the value may be a ResumeEnvelope and must reach the resume future unchanged (same object). If cross-process stores are supported, give ResumeEnvelope a documented, serializable shape.
- codify: Changing the runtime type that flows through an abstract TaskStore method is a contract change for external subclasses and must be documented on the ABC method and in the CHANGELOG.

### RT-009
- severity: medium
- file: agent_sdk/agent/runner.py (also agent_sdk/tasks/store.py, CHANGELOG.md, todo files)
- description: Scope and CHANGELOG drift (LRN-168/202/207 Check clauses fail). runner.py is modified (the wait_resume rebind, ~1251-1254) but is listed only under Reads: in the GH-185 todo, missing from this group's scope list, and not named in the CHANGELOG file list. store.py's GH-185 change (TaskRecord.resume_identity, or its ResumeEnvelope successor) is declared only under GH-187. Four existing tests were modified without being declared: tests/test_rt002_context_messages_max_turns_cliff.py, tests/test_rtb002_cancel_repair_failure_still_publishes_final.py, tests/test_rtb003_taskstore_persist_status_hook.py, tests/test_rtb007_persist_status_ordered_after_repair.py.
- fix: Add runner.py and store.py to the GH-185 todo's Modifies line, and the four tests to the GH-187 todo's Modifies line. Name runner.py and store.py in the GH-185 CHANGELOG entry's file list.
- codify: Every dirty path in `git status --short` must map to a todo Creates:/Modifies: line and to the CHANGELOG file list, including Reads: files that ended up edited and existing tests whose assertions were flipped.

### RT-010
- severity: medium
- file: agent_sdk/tasks/store.py
- description: Raised against the earlier design (see ordering note). TaskRecord is public (exported in agent_sdk.tasks.__all__) and a non-kw_only dataclass. The new resume_identity field was inserted mid-class (~line 95, between resume_future and spent_tokens), shifting positions of spent_tokens, messages, pending_tool_results and date_line; an external store rebuilding TaskRecord positionally would silently misassign values. It was also not added to DESIGN.md §5.2's runtime-only (never serialized) list, so a durable subclass serializing all fields would write a caller Identity to storage.
- fix: If the field still exists, move it to the end (after date_line) and document it as runtime-only/never serialized in DESIGN.md §5.2 and docs/deployment.md "Custom TaskStore durability". If ResumeEnvelope replaced it, confirm the field is gone.
- codify: New fields on a public non-kw_only dataclass go at the end, and runtime-only fields must be added to the documented never-serialize list in the same change.

### RT-011
- severity: medium
- file: agent_sdk/auth/context.py
- description: The new public, reusable request-scoped helper `current_identity`/`bind_identity`/`unbind_identity` (same ContextVar bind pattern as credentials/forwarding.py) is not registered in workspace/components/README.md. A later transport or route could add a second bind mechanism without knowing this one exists (Dimension 8: unregistered reusable utility).
- fix: Register a new C-NNN entry for agent_sdk/auth/context.py. List its bind sites (a2a._start_worker, ag_ui._start_worker, mcp_post, mcp_messages, runner.wait_resume) and the rule: bind only after require_identity has resolved, unbind in finally.

### RT-012
- severity: medium
- file: tests/test_gh185_current_identity.py
- description: Raised in two rounds. Required tests are missing or too weak. (a) The SI-5 annotation requires a test that an unauthenticated or rejected request never leaves a bound identity behind; there is no 401/403/429 or bad-token case. (b) The legacy MCP bind site (routes/mcp.py:1196, POST /mcp/messages) is never exercised; the isolation test covers POST /mcp only. (c) No check that AG-UI leaves nothing behind after the request ends. (d) The overlap wait swallows asyncio.TimeoutError after 2s (~lines 55-58), so if the two `whoami` requests never overlap the test still passes without proving isolation. (e) No concurrent-resumer test (RT-007) and no resume test against a copy-on-get TaskStore. (f) test_identity_is_frozen_and_only_identity (~169-172) checks the Identity dataclass, not what current_identity() returns.
- fix: Add bad/missing bearer token requests to /v1/message:send, /ag-ui/run and /mcp, asserting `current_identity() is None` and no tool ran. Add a legacy SSE session (GET /mcp/sse, then POST /mcp/messages?session_id=...) running `whoami` for two identities, reading results from the SSE channel. Add a follow-up AG-UI run by bob after alice, asserting bob's tool sees only bob. Assert `_both.is_set()` after the wait. Add a concurrent-resume test with two resuming identities on A2A and AG-UI, and a resume test against an InMemoryTaskStore subclass whose get() returns a copy. Assert the object returned by current_identity() inside a tool `is` the route-resolved Identity.

### RT-013
- severity: low
- file: tests/test_gh185_current_identity.py
- description: `test_no_identity_value_logged` (~line 294) checks only the label "alice" in log output. It never checks subject (key id), principal_key, or the OAuth `user` field, so the SI-2 extension ("no Identity field in exception text, error envelopes or logs") is only partly tested.
- fix: Assert that none of identity.subject, identity.label, identity.principal_key (and user for an OAuth identity) appear in caplog messages or in any error response bodies collected during the test.

### RT-014
- severity: low
- file: tests/test_gh187_retry_after_failed_task.py
- description: Raised in two rounds. Some assertions prove nothing. `test_retry_after_failed_turn_runs_tool_again` never checks that turn 2 actually ran `demo_kpis` before failing, so the "no toolResult in turn 3 seed" check can pass vacuously. In `test_only_non_completed_prior_tasks_give_empty_seed`, the context_reusable_messages()==[] assertion would also pass on pre-fix code because the fixtures hold no __resolved__ marker. `test_reusable_markers_skip_non_completed` patches `memory.extract_resolved_markers` by hand instead of via `monkeypatch`, and ends with `assert ok is not bad`, which can never fail.
- fix: After turn 2, read `app.state.task_store.get(r2_id)` and assert its messages contain a toolResult for demo_kpis. Seed a real __resolved__ marker into the FAILED/CANCELED/REJECTED fixtures and assert it is absent from the result. Switch to `monkeypatch.setattr(memory, "extract_resolved_markers", ...)` and drop `assert ok is not bad`.

### RT-015
- severity: low
- file: tests/test_rtb003_taskstore_persist_status_hook.py (also tests/test_rtb002_cancel_repair_failure_still_publishes_final.py, tests/test_rtb007_persist_status_ordered_after_repair.py)
- description: GH-187 rewrote existing tests so they prove nothing on this path. The old checks that context_messages() replays a repaired, non-dangling transcript were replaced by `context_messages(...) == []`, which is true for any canceled task whether or not the repair or persist hooks ran. The rtb003 second test (~269-274) also dropped its _ends_on_dangling_tool_use check.
- fix: Keep the new `== []` assertions and restore the repair checks on the durable record itself, e.g. `assert not _ends_on_dangling_tool_use(store.get(task_id).messages)` in rtb003 and rtb007, so each test still guards the invariant its name describes.

### RT-016
- severity: low
- file: agent_sdk/auth/context.py
- description: `bind_identity`/`unbind_identity` are public names in an importable module. The AC says the API is read-only, but any tool or adapter can import bind_identity and set any Identity for the rest of its task, faking attribution for later tool calls in the same worker. `contextvars.Token` is also untyped.
- fix: Rename to `_bind_identity`/`_unbind_identity` (only routes/a2a.py, ag_ui.py, mcp.py and runner.py import them), or add `__all__ = ["current_identity"]` and a docstring marking them SDK-internal. Type them as `contextvars.Token[Identity | None]`.

### RT-017
- severity: low
- file: agent_sdk/tasks/memory.py
- description: The COMPLETED-only candidate filter is copied in both `context_messages` (~:301-306) and `context_reusable_messages` (~:331-336). Two copies invite the next state-rule change to update only one — the same drift GH-187 had to fix in both.
- fix: Extract `_continuation_candidates(context_id, identity)` in InMemoryTaskStore applying the context, `TaskState.COMPLETED` and identity-binding checks, and call it from both methods.

### RT-018
- severity: low
- file: agent_sdk/routes/a2a.py
- description: Comments are misleading. _start_worker (~461-464) says "a later resume runs in the worker's context, not the resume request's", but identity IS now rebound to the resume caller. The module docstring (~:35, :295, :322) says _start_worker binds forwarding only and does not mention identity binding.
- fix: Update the _start_worker comment: forwarded credentials stay bound to the original submit, while identity is rebound on resume (ResumeEnvelope). Mention bind_identity next to forwarding.bind in the module docstring. Coordinate wording with RT-006's ruling.

### RT-019
- severity: low
- file: agent_sdk/routes/a2a.py
- description: The tasks/resubscribe bind (~1122-1126) has no effect. It wraps only _open_stream, which subscribes and snapshots without running tool or adapter code; the SSE generator runs after unbind and the existing worker keeps its own context. The CHANGELOG still claims "tasks/resubscribe is also bound", and test_resubscribe_still_streams asserts only a 200.
- fix: Either remove the bind and record in the CHANGELOG that resubscribe runs no tool code, or keep it with a comment that it is a deliberate no-op kept to satisfy the ruling. Do not claim an observable binding.

### RT-020
- severity: low
- file: harness/skills/add-tool/SKILL.md
- description: The template peer-repo mirror (template commit 06d23a2, already pushed to origin) tells agents to `from agent_sdk.auth import current_identity` before any SDK release has that symbol. An agent scaffolded now pins the released SDK (0.15.1) and gets an ImportError if it follows the skill.
- fix: Release 0.16.0 before (or together with) the template sync, or gate the skill note with "requires agent-sdk >= 0.16.0". Likely resolved once the 0.16.0 release ships; confirm.
