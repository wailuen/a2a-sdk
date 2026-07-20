wave: w034
group: G
date: 2026-07-10
round_count: 5
status: budget-exhausted

## Findings

### RT-001
- severity: medium
- file: agent_sdk/agent/loop.py
- status: FIXED (2026-07-14)
- description: The RT-001 cross-surface DeferredResult unification is incomplete: loop.py's async-generator tool branch (elif entry.decl.is_generator, ~lines 454-483) drains invoke_gen and sets result = terminal value but NEVER runs the isinstance(result, DeferredResult) handoff that the coroutine branch does at loop.py:491-497. So an async-generator tool whose final yield is a DeferredResult is not detected as deferred (no DeferredEvent emitted); deferred stays None, no ArtifactEvent is produced (DeferredResult is not an emits type), and at loop.py:572/579 the raw DeferredResult is yielded on ToolResultEvent(result=...) (-> AG-UI TOOL_CALL_RESULT wire) and folded via _fold_result_content -> str(DeferredResult(handle=<coroutine object ... at 0x...>)) into the model conversation. The handle is never awaited (the long-running job never runs; ResourceWarning: coroutine never awaited). The SAME tool over MCP is handled correctly because invoke_any drains invoke_gen and routes the terminal value through resolve_deferred_result (registry.py:502) - a transport contract drift on the live A2A/AG-UI streaming path, the exact class of repr leak GH-120/GH-121 just closed on the coroutine surfaces.
- fix: Applied the identical handoff used in the coroutine branch (loop.py:491-497) to the is_generator branch: after the drain sets the terminal `result`, `if isinstance(result, DeferredResult): deferred = result; result = None` before the result_cache write. See agent_sdk/agent/loop.py:473-484. Added tests/test_rt001_gen_tool_terminal_deferred_result.py, mirroring test_rt001_deferred_nesting_parity.py, with an async-generator tool that yields a DeferredResult as its terminal item — covers (1) run_loop emits a DeferredEvent (never leaks the raw DeferredResult onto ToolResultEvent), (2) run_task_worker resolves the task to COMPLETED and actually runs the deferred handle's side effect, and (3) parity between the MCP tools/call surface and the runner surface for the identical tool contract. Verified regression: reverting the loop.py fix makes all three new tests fail (confirmed via git stash before/after).
- codify: DeferredResult detection must live on every tool-result path (coroutine AND async-generator terminal yield), not just the coroutine branch, or long-running generator tools leak the unawaited handle repr onto the wire and drift by transport.
- sdkCandidate: true

### RT-002
- severity: low
- file: agent_sdk/agent/runner.py
- status: FIXED (2026-07-14)
- description: In _run_deferred_background's success path, record.task.artifacts is mutated to append the artifact (runner.py:329) BEFORE TaskArtifactUpdateEvent(...).wire() serializes the frame (runner.py:330-335). If .wire() (or the subsequent publish) raises, the except branch (runner.py:355-364) transitions the task to FAILED via _fail(), but the just-appended artifact remains on the now-FAILED task record - a FAILED deferred task retains a half-delivered artifact that was never emitted on any stream. This mirrors the identical append-then-wire order in the synchronous run_task_worker ArtifactEvent branch (runner.py:455-463), so it is a consistent pre-existing pattern rather than a regression, but it means the 'deterministic FAILED + streams closed' guarantee the RT-001 guard advertises is not a fully clean FAILED.
- fix: Reordered both call sites to build and serialize the TaskArtifactUpdateEvent frame BEFORE mutating record.task.artifacts / task.artifacts, so a serialization failure can no longer strand a half-delivered artifact on a FAILED task — applied identically to _run_deferred_background's success path (runner.py ~320-336) and run_task_worker's ArtifactEvent branch (runner.py ~454-463). Added tests/test_rt002_failed_task_no_stranded_artifact.py: forces TaskArtifactUpdateEvent.wire() to raise via monkeypatch.setattr (real attribute swap, not a Mock) on an otherwise successful artifact build, and asserts the FAILED task's artifacts list is empty for BOTH the deferred-background path and the synchronous ArtifactEvent path. Verified regression: reverting the runner.py fix makes both new tests fail (confirmed via git stash before/after).
- codify: Append to task.artifacts only after the artifact frame has been serialized and is about to be published, so a serialization failure cannot strand a half-delivered artifact on a FAILED task.
- sdkCandidate: false

## Instruction

Fix remaining findings, then re-run /wave w034.
