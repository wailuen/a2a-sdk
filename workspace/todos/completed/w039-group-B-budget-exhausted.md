wave: w039
group: B
date: 2026-09-03
round_count: 5
status: budget-exhausted

## Findings

### RT-001
- severity: high
- file: agent_sdk/agent/runner.py
- description: run_task_worker's terminal `except AgentError` (line 1375) and `except Exception` (line 1413) handlers have no already-terminal guard, so an exception escaping run_loop after a concurrent tasks_cancel has committed CANCELED overwrites it with FAILED, durably persists FAILED over CANCELED via set_task_status(store=store), and publishes a second terminal frame onto streams the canceller already closed — contradicting the HTTP 200 `"state": "canceled"` the client was already given.
- fix: Add the same entry guard `_run_deferred_background._fail` carries at runner.py:816 (`if record.task.status.state in TERMINAL_STATES: return`) to both terminal except-handlers, before the repair/set_task_status/publish/close_streams sequence. The top-of-loop guard at runner.py:1202 only covers events yielded by run_loop; it cannot see an exception raised between a tool await and the next yield (e.g. jsonable_reuse_value at loop.py:1131, or fold_result_content at loop.py:1191). Reproduced end-to-end: a tool that swallows CancelledError and returns Reusable(value=<object whose __str__ raises>) makes POST /v1/tasks/{id}:cancel return 200 canceled, after which GET /v1/tasks/{id} reports failed with -32603. Extend tests/test_rtb102_worker_terminal_race_guard.py with the exception variant alongside its existing DoneEvent variant.
- codify: Every terminal-state writer must carry the already-terminal bail-out, including catch-all exception handlers — a guard placed only on the event-consumer loop cannot see a raise that escapes the generator between yields.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: message:send (line 357) and message:stream (line 449) call `_echo_extensions` with the full activatable set unconditionally, before the request body is parsed and before the resume-vs-new-task branch is known — so the resume branch (which calls neither `_capabilities()` nor `forwarding.bind`) and every error return echo `X-A2A-Extensions: <credential-forwarding URI>` as ACTIVATED when nothing was forwarded, the exact false-activation signal the module docstring (lines 19-46) declares forbidden and that RT-002 stripped from tasks/cancel and tasks/resubscribe in this same change.
- fix: Defer the echo on both routes until the branch is resolved: echo the full `_ECHO_EXTENSION_URIS` set only on the fresh-task path that actually reaches `_capabilities()` + `_start_worker`; on the resume branch and on parse/config/not-found error returns echo nothing (or A2UI only, via `_echo_a2ui_if_present`, when the returned Task genuinely carries an A2UI part — the helper tasks_get and tasks_cancel already use). Update tests/test_rtb011_extensions_echo_gaps.py:181 and :193, which currently pin the false-activation behaviour under names asserting the opposite.
- codify: X-A2A-Extensions must be emitted from the code path that actually activated the extension, not from a route-entry prologue that runs before the request branch is known.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/agent/runner.py
- description: `repair_dangling_tool_use`'s `store=` parameter (line 478, flushed at line 627-628) has zero call sites left in the SDK after RT-007 moved the flush into set_task_status, yet its own docstring (lines 556-566) still calls it "the single flush point for every caller", TaskStore.persist_messages' docstring (store.py:205-212) still describes repair callers double-flushing the hook, and C-018's registry contract (workspace/components/README.md:99, :103) instructs any sixth writer of record.messages to pass `store=`. Following that documented contract reintroduces the double synchronous persist_messages write per terminal transition that RT-007 removed — on a hook whose durable write blocks the event loop.
- fix: Either delete the `store` parameter from `repair_dangling_tool_use` and migrate tests/test_rt005_gh150_taskstore_persist_messages_hook.py onto set_task_status, or keep it and rewrite all three contracts to say set_task_status is the sole flush point and that new callers must NOT pass `store`. Whichever is chosen, runner.py:556-566, store.py:205-212 and workspace/components/README.md:99/:103 must state the same thing — they currently contradict repair_dangling_tool_use_safe's own docstring (runner.py:679-700) inside the same module.
- codify: When a redteam round moves a flush out of a helper, delete or re-document the helper's now-dead hook parameter in the same change — a live parameter plus a stale registry contract is an instruction to reintroduce the bug.
- sdkCandidate: true

### RT-004
- severity: low
- file: workspace/components/README.md
- description: C-005's registry row (line 36) says persist_status was "wired into tasks_cancel right after the CANCELED assignment", which RT-004 replaced — tasks_cancel no longer touches persist_status at all, it routes through set_task_status (a2a.py:601). The same row's "Key public methods" list omits `context_reusable_messages` and the `persist_every_status` class attribute, both new public contract surface an external durable subclass must implement or opt into. DESIGN.md:307 cites `store.py:223` for persist_every_status; it is at store.py:275.
- fix: Update the C-005 row to name set_task_status (C-019) as the only caller of persist_status/persist_messages, add `context_reusable_messages` and `persist_every_status` to the key-public-surface list with their default-behaviour consequences for subclassers, and drop or correct the DESIGN.md:307 line-number citation (symbol names, per C-017's own note about pinned line numbers rotting).
- sdkCandidate: true

### RT-005
- severity: low
- file: agent_sdk/agent/runner.py
- description: `repair_dangling_tool_use_safe` documents its return as "whether record.messages is now in a state that is SAFE TO PERSIST" (line 671-677), but it only reports whether an exception was raised. The RT-B-008/RT-001 hardening in `close_dangling_tool_use` (loop.py:367-380) makes a malformed dangling tail — a non-dict tail entry, a non-list `content`, a `toolUse` value that is not a dict, or one missing `toolUseId` — degrade to "nothing to repair" and return False without raising, so the wrapper returns True and set_task_status durably flushes the still-unrepaired transcript plus the terminal status over it. bridge_context_messages (loop.py:441) re-asserts the invariant through the same helper, so the read side has the identical blind spot.
- fix: Have `close_dangling_tool_use` distinguish "no toolUse tail" from "toolUse tail present but unreadable" (e.g. return a tri-state or raise a typed error on the malformed case), and have repair_dangling_tool_use_safe return False for the unreadable case so set_task_status's `repaired` gate skips both durable flushes — the fail-closed outcome its docstring already promises. Add a regression test with a loosely-deserialised malformed tail asserting repaired is False and neither persist hook fires.
- sdkCandidate: true

## Instruction

Fix remaining findings, then re-run /wave w039.
