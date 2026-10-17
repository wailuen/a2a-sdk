wave: w055
group: A3
date: 2026-10-17

Non-blocking — these did not block w055's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group A3. Findings raised in more
than one round are merged into one entry; the original per-round IDs are listed under "rounds". All
findings are SDK-level (sdkCandidate: true). Context: GH-189 (A2A `configuration.blocking: true`
on message:send waits for final, using the shared stream admission slots).

## Findings

### RT-001
- severity: medium
- file: agent_sdk/routes/a2a.py
- rounds: round 1 RT-002, round 2 RT-001
- description: `_wait_blocking` (a2a.py ~702-723, called from message_send at ~651 and ~692) only waits for `final`, StreamTerminated, `None` or the cap. Nothing watches for the client hanging up. uvicorn does not cancel a non-streaming handler when the client disconnects (checked with a uvicorn + FastAPI probe: the handler ran to the end). So a dropped blocking send keeps its admission slot and its record.subscriptions entry for up to min(task deadline, 120 s). That slot comes out of the stream budget shared by message:stream, tasks/{id}:subscribe and /ag-ui/run (200 per identity, 500 in total). A client that keeps sending blocking requests and dropping them can fill that budget with dead waits. The release in `finally` and the `prune_finished` backstop only run once the handler task actually ends. The CHANGELOG claim 'always releases its subscription, including on client disconnect' and the GH-189 AC / SI-5 note are only proven for httpx ASGITransport task cancellation, which does not happen in production.
- fix: In `_wait_blocking`, race `drain()` against a disconnect watcher — either `await request.receive()` returning `{'type': 'http.disconnect'}` (the body is already read) or a loop polling `request.is_disconnected()` with a short sleep. Use `asyncio.wait(..., timeout=cap, return_when=FIRST_COMPLETED)`, cancel the loser, and return as soon as the client has gone so the caller's `finally` releases the slot at once. Add a raw-ASGI test whose receive() returns http.disconnect without cancelling the request task; assert `_a2a_streams(app)` and record.subscriptions are both empty before the tool finishes.
- codify: A non-streaming handler that holds a capacity slot while it waits must watch for http.disconnect itself; ASGI servers do not cancel it, and httpx ASGITransport cancellation is not a stand-in for a real disconnect.

### RT-002
- severity: medium
- file: tests/test_gh189_blocking_send.py
- rounds: round 1 RT-003, round 2 RT-006
- description: `test_blocking_disconnect_leaks_no_subscription` does not test its AC ('Client disconnect during the wait leaks no subscription'). It calls `gate['release'].set()` before checking `_open_subs(bs_app) == 0`, so a slot freed on completion looks the same as one freed on disconnect; the test passes whether or not disconnect handling works. It relies on httpx.ASGITransport cancelling the handler, which uvicorn never does (see RT-001). The disconnect and cap tests only check len(_a2a_streams(app)), never record.subscriptions, which is the list the AC is about. Missing cases: the task-deadline side of min(task deadline, cap); the auth-required stop; a blocking resume of a non-interrupt task returning its error and freeing its slot.
- fix: Assert `_open_subs(bs_app) == 0` and `task_store.get(id).subscriptions == []` right after the cancelled request or cap, before `gate['release'].set()`. Add a raw-ASGI test that delivers `{'type': 'http.disconnect'}` from `receive()` while the handler keeps running, and assert the slot is freed while the tool is still blocked. Add a case with task_deadline_seconds below blocking_send_max_seconds, an auth-required interrupt case, and a blocking resume on a completed task that expects -32004 and `_open_subs == 0`.

### RT-003
- severity: medium
- file: docs/protocols.md
- rounds: round 1 RT-005, round 2 RT-003
- description: A blocking message:send now takes a slot from the shared A2A stream admission budget (`_admit` at a2a.py ~643 and ~679), so it can return 429 -32000 + Retry-After. The docs do not say so. The 'Concurrent-stream cap' section (protocols.md ~49-68) lists only message:stream, tasks/{id}:subscribe and /ag-ui/run, and the 429 entry ('too many concurrent streams') reads as if it covers SSE endpoints only. DESIGN.md ~375 still calls POST /v1/message:send an 'uncapped-by-design' route and leaves it out of the A2A budget list. Only the CHANGELOG mentions it. No test covers a 429 on a blocking send, or shows that it creates no task (the admit-before-mutation rule).
- fix: Add blocking message:send (fresh and taskId resume) to the shared-budget list and error table in protocols.md and to DESIGN.md §375. State that only blocking:true is admitted and non-blocking stays uncapped, and that it counts against the per-identity, per-task and global caps. Add a test that fills the per-identity budget, then checks a blocking send returns 429 -32000 with Retry-After and creates no TaskRecord.
- codify: When an existing non-stream route starts taking a stream admission slot, update every place that lists the shared budget's routes and add a 429 + no-task test for that route.

### RT-004
- severity: medium
- file: docs/deployment.md
- rounds: round 2 RT-002 (also round 1 RT-005, deployment part)
- description: The new default AGENT_SDK_BLOCKING_SEND_MAX=120 s is longer than common reverse-proxy idle timeouts. The nginx example in docs/deployment.md (~17-22) uses the default proxy_read_timeout of 60 s, and cloud load balancers often default to 60 s. A blocking send to a slow task then gets a 504 from the proxy, the response holding the Task id is lost, and the client cannot poll tasks/get; it usually retries, creating a duplicate task. docs/deployment.md lists other AGENT_SDK_* settings (~106-111) but has no entry for AGENT_SDK_BLOCKING_SEND_MAX; the todo asked for it to be updated if it lists settings.
- fix: Add an AGENT_SDK_BLOCKING_SEND_MAX bullet to docs/deployment.md (default 120, must be > 0, bounded by AGENT_SDK_TASK_DEADLINE, must stay below the front proxy's read/idle timeout). Add proxy_read_timeout to the nginx example, or lower the default below 60 s (e.g. 55 s), and record the choice in CHANGELOG.
- codify: Any new server-side wait on a plain HTTP response needs its cap documented against the proxy idle timeouts in the deployment guide, because a proxy 504 drops the only copy of the task id.

### RT-005
- severity: low
- file: agent_sdk/routes/a2a.py
- rounds: round 1 RT-004, round 2 RT-004
- description: The blocking resume branch (a2a.py ~642-648) calls `_admit` (which can raise 429) and subscribes before `_resume_or_error` checks the task state. With the budget full, a blocking resume of a terminal task, a working task or a contextId mismatch gets 429 -32000 instead of the documented 501 -32004 or 400 -32602, so the error order depends on load. It also briefly subscribes to a terminal task. message_stream rejects a terminal task before opening a subscription (A2A-F1, ~990-998), so the two resume paths order their errors differently.
- fix: Run the side-effect-free checks from `_resume_or_error` first: state in INTERRUPT_STATES, terminal state gives -32004, contextId match, and `_resume_value`. Only then call `_admit` and `subscribe`, keeping `deliver_resume` after `subscribe` so no frame is missed. Add a test with the budget full and a terminal task that asserts -32004.

### RT-006
- severity: low
- file: docs/protocols.md
- rounds: round 2 RT-005
- description: protocols.md line 12, the CHANGELOG GH-189 entry and DESIGN.md line 272 all say a blocking send waits for 'terminal or input-required'. The code stops on any final frame, and the runner publishes one for AUTH_REQUIRED too (runner.py ~1407-1426); the ruling also names auth-required. The spec citation is inconsistent: the CHANGELOG and test docstring say §7.1, DESIGN.md says §7.1.1.
- fix: Say 'terminal, input-required or auth-required' in all three places, and use one spec section reference (§7.1.1 MessageSendParams / MessageSendConfiguration.blocking) everywhere.

### RT-007
- severity: low
- file: CHANGELOG.md
- rounds: round 1 RT-006
- description: The new public setting `blocking_send_max_seconds` / `AGENT_SDK_BLOCKING_SEND_MAX` is missing from '### Added', where the other items list their new settings (GH-194, GH-196, GH-188). There is a stray blank line between the GH-189 and GH-193 bullets under '### Changed'. The tests also miss three paths: tasks/{id}:cancel during a blocking wait, a blocking resume that hits a second interrupt, and the 429 admission path for blocking sends.
- fix: Add '- GH-189: `blocking_send_max_seconds` setting (`AGENT_SDK_BLOCKING_SEND_MAX`, default 120 s).' under Added and remove the blank line. Add tests for cancel during a blocking wait (expect 200 with canceled), a blocking resume that ends in input-required again, and a blocking send with the stream budget full (expect 429 -32000 plus Retry-After, and no task created).
