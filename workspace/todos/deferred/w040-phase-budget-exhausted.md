wave: w040
scope: phase
date: 2026-08-19
round_count: 8
status: budget-exhausted

## Findings

### RT-001
- severity: high
- file: agent_sdk/tasks/memory.py
- description: Two stable-core behavior changes to InMemoryTaskStore landed with no CHANGELOG entry and no DESIGN.md 5.2 update: _evict_over_capacity now permanently skips records with live subscribers (memory.py:288-290) and publish() now delegates to touch(), which calls self._records.move_to_end(task_id) (memory.py:110, :62-66), changing which record overflow evicts on every published frame. DESIGN.md:295 still states 'LRU 1000' and lists 'interrupted' as the only eviction exclusion with its bound; the new exclusion appears only mid-paragraph inside 5.5's MCP stream-admission bullet (DESIGN.md:353). Worst-case occupancy is now capacity + max_interrupted + live A2A subscribers (1000 + 100 + 500). tests/test_rt001_r5_eviction_never_severs_live_streams.py is referenced nowhere in CHANGELOG.md. The wave's own Features preamble states the rule it breaks: 'documenting the behaviour in DESIGN.md does not discharge the SemVer accounting.'
- fix: Add a '### ⚠️ Behavior changes' CHANGELOG entry under [0.7.0] for both changes (live-subscriber eviction skip; publish() LRU refresh), naming agent_sdk/tasks/memory.py and tests/test_rt001_r5_eviction_never_severs_live_streams.py, and move the exclusion into DESIGN.md 5.2's lifecycle-rules list beside the `interrupted` one, restating the LRU 1000 bound as soft with its worst-case occupancy.
- codify: A change to _evict_over_capacity or LRU ordering is a stable-core behavior change requiring its own CHANGELOG entry and an update to the DESIGN.md section that states the invariant (5.2), not a clause buried inside another surface's section.
- sdkCandidate: true

### RT-002
- severity: medium
- file: agent_sdk/common/cors.py
- description: _EXPOSE_HEADERS at cors.py:28 is `WWW-Authenticate, Mcp-Session-Id, X-A2A-Extensions`. All six new 429 branches (mcp.py:885,896,1016,1024; a2a.py:466,473,480) emit `Retry-After: 5`, and docs/protocols.md now tells clients to 'retry after the advertised delay', but a cross-origin browser MCP/AG-UI client (Claude.ai web is a first-class target of this SDK) cannot read an unexposed header and will retry immediately, defeating the backpressure the cap exists to provide. MCP-Protocol-Version, newly added to mcp_get's 429s, is likewise unexposed. This is the LRN-004 failure class applied to newly added headers.
- fix: Add `Retry-After` (and `MCP-Protocol-Version`) to _EXPOSE_HEADERS in agent_sdk/common/cors.py:28 and extend the CORS preflight/expose-headers test to assert both are present on the 204 preflight and on a real 429.
- codify: Any response header a protocol client is instructed to act on must be added to Access-Control-Expose-Headers in the same change that starts emitting it.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: None of the six stream-admission 429 branches logs anything (mcp.py:883-902, :1013-1029; a2a.py:462-484), while every other rejection class in mcp.py logs via logger.warning (:575, :589, :597, :609, :676). harness/reference/mcp-claude-platforms.md:44 makes 'is something returning 403/429 on the MCP path?' the first P8 debug question, and the SDK is now the thing emitting it, so cap exhaustion presents to an operator as Claude.ai 'Couldn't connect' with an empty log, indistinguishable from an auth, CORS, or network fault. Flagged twice already in workspace/todos/deferred/w040-group-G-medium-low.md (RT-005, RT-016) and still absent.
- fix: Add logger.warning("stream admission cap reached scope=%s open=%d", scope, len(streams)) to each 429 branch in agent_sdk/routes/mcp.py and agent_sdk/routes/a2a.py::_admit, emitting only a static scope label ('global'/'identity'/'task') and the count — never _identity_key(identity), the Authorization header, or Mcp-Session-Id (SI-2).
- sdkCandidate: true

### RT-004
- severity: medium
- file: agent_sdk/common/admission.py
- description: resolve_per_identity_limit (admission.py:154-172) returns min(override, ceiling) where the ceiling is _MAX_GET_STREAMS = 500 (mcp.py:170) or _MAX_A2A_STREAMS = 500 (a2a.py:106) — neither has an AGENT_SDK_* setting. _MAX_A2A_STREAMS_PER_TASK = 16 (a2a.py:108) and InMemoryTaskStore(capacity=1000) (app.py:528-532 wires only task_ttl/interrupt_ttl/max_interrupted) are likewise hard-coded. DESIGN.md:353 justifies the low-hundreds per-identity default by saying it 'is operator-raisable without a code change', which is true only up to 500 — exactly the case an org-wide OAuth client (which collapses a whole org onto one identity_key per admission.py:96-107) is most likely to exceed. An operator there has no knob and no recovery.
- fix: Promote _MAX_GET_STREAMS and _MAX_A2A_STREAMS to BaseAgentSettings fields (AGENT_SDK_MAX_MCP_STREAMS / AGENT_SDK_MAX_A2A_STREAMS, ge=1, defaults 500) read at admission time so resolve_per_identity_limit's clamp ceiling moves with them, and wire InMemoryTaskStore(capacity=...) to a setting given RT-001's soft occupancy bound.
- sdkCandidate: true

### RT-005
- severity: medium
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: test_prune_never_evicts_a_still_open_stream_regardless_of_elapsed_time patches mcp_module.time.monotonic at lines 366-367, but agent_sdk/routes/mcp.py never calls time.monotonic — it uses time.time() exclusively (:246, :265, :270, :836). The test's stated invariant ('a still-open slot must never be reclaimed by wall-clock pruning') is therefore unguarded: reintroducing a time.time()-based TTL reaper leaves it green. Worse, mcp_module.time IS the stdlib time module and asyncio.base_events.BaseEventLoop.time() returns time.monotonic() resolved through that module attribute (verified via inspect.getsource), so the patch advances the event-loop clock by +10,000s for the remainder of the test, instantly firing t1's in-flight asyncio.sleep(_HEARTBEAT_SECONDS) and every anyio/httpx timer — a latent flake in a test whose whole subject is timing. Deferred as RT-014/RT-023 and unfixed.
- fix: Remove the global time.monotonic patch. Assert the invariant structurally instead: seed _get_streams() with a sentinel asyncio.Task that is not done(), call prune_finished and assert the entry survives, then let the task complete and assert it is reclaimed. If a wall-clock guard is genuinely wanted, patch mcp_module.time.time — the clock the module actually reads — rather than the stdlib clock asyncio depends on.
- codify: A test that patches a clock the module under test never reads asserts nothing; assert against the exact time source the code calls, or assert structurally that no time source is referenced.
- sdkCandidate: true

### RT-006
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: `assert owning_task is not None` is used as request-path control flow at a2a.py:492 and mcp.py:909 and :1031. StreamSlot.owning_task is typed non-optional (admission.py:87) and prune_finished calls slot.owning_task.done() unguarded (admission.py:136). Under python -O / PYTHONOPTIMIZE the asserts are stripped, a None owner is stored, and the next admission raises AttributeError BEFORE streams.pop(sid, None) (admission.py:138) — so the poisoned record is never cleared and every subsequent GET /mcp, GET /mcp/sse, POST /v1/message:stream, POST /v1/tasks/{id}:subscribe and POST /ag-ui/run returns 500 for the remaining process lifetime, with no self-heal, on routes the mcp.py module docstring calls connection-critical. The same wave handles the identical asyncio.current_task() case defensively one layer down (tasks/store.py:151-154), so the two halves disagree on hardening. Flagged four times across both deferred files.
- fix: Type StreamSlot.owning_task as `asyncio.Task[Any] | None`, have prune_finished skip records whose owning_task is None, and replace the three asserts with a plain assignment — a slot that cannot be liveness-keyed is simply never auto-reaped, matching tasks/store.py's treatment, instead of poisoning the reaper for both budgets.
- codify: A bare assert must never establish a type invariant on a live request path: python -O strips it, and here the resulting AttributeError escapes before the cleanup pop, permanently 500-ing every stream route.
- sdkCandidate: true

### RT-007
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: GH-144's stated root cause was two independent terminal predicates on one logical condition. The landed fix keeps both and duplicates the literal: `record.task.status.state in TERMINAL_STATES` plus 'task is in a terminal state and cannot accept new messages' now appears at a2a.py:352-356 (_resume_or_error, message/send) and again at a2a.py:632-638 (message_stream's new branch), so the structural cause survives and can diverge again on the next edit. No parity test exists (grep for 'parity' across tests/test_w017_gh51_multiturn.py and tests/test_gh144_terminal_resume_error_docs.py returns nothing): test_send_terminal_taskid_returns_unsupported (:128) and test_stream_terminal_taskid_returns_unsupported (:139) each assert the constant independently, so a one-sided change to either the code or the message stays green.
- fix: Hoist the message to a module-level _TERMINAL_TASK_MESSAGE constant and the predicate to one helper (e.g. `_terminal_reject(record) -> JSONResponse | None`) called by both paths, then add a parity test driving the identical terminal task through /v1/message:send and /v1/message:stream asserting the same status_code, error.code and error.message.
- codify: Reconciling two diverged error paths by duplicating the predicate leaves the divergence possible — extract one shared check and lock it with a cross-method parity test asserting identical status, code, and message.
- sdkCandidate: true

### RT-008
- severity: low
- file: agent_sdk/routes/ag_ui.py
- description: ag_ui.py:52 does `from .a2a import _admit as _admit_stream` — a route module depending on another route module's private symbol, placed mid-import-block before `..agent.events`. AG-UI therefore silently inherits A2A's cap constants and its HTTPException-shaped rejection, which docs/protocols.md then had to special-case ('on /ag-ui/run it is the bare {"detail": ...} shape'). The genuinely shared half already lives in agent_sdk/common/admission.py (registered C-024), so the private cross-route edge is avoidable.
- fix: Move _ClaimedSlot and _admit into agent_sdk/common/admission.py as a public helper parameterised by budget attr, cap constants and a rejection factory, or expose an `admit_a2a_stream()` on a non-route module that both routes/a2a.py and routes/ag_ui.py import; fix the import ordering while doing so.
- sdkCandidate: true

### RT-009
- severity: low
- file: agent_sdk/routes/ag_ui.py
- description: The comment at ag_ui.py:636 names `_prune_a2a_streams` as 'the liveness backstop', but no such symbol exists anywhere in the tree — the real one is common.admission.prune_finished, aliased in mcp.py as _prune_get_streams. tests/test_rt001_admission_before_mutation.py:238 also carries '_prune_a2a_streams' as a dead entry in _ADMISSION_MARKERS, so the completeness gate advertises a marker no handler can ever match.
- fix: Rename both references to `prune_finished` (agent_sdk/routes/ag_ui.py:636 and tests/test_rt001_admission_before_mutation.py:238) so the comment and the gate name symbols that actually exist.
- sdkCandidate: true

### RT-010
- severity: low
- file: agent_sdk/tasks/store.py
- description: reap_dead_subscriptions (store.py:113-118) drops orphaned Subscription objects out of record.subscriptions without calling sub.close(), so a reaped subscription's queue never receives the _CLOSE sentinel. Every other removal path in the class closes first — close_streams at memory.py:118-120 and evict at memory.py:217-219. Currently harmless (a reaped orphan's owning task is by definition done, so it has no live reader) but it makes the removal contract inconsistent across a newly-public base-class method and would silently strand any future caller holding a Subscription across tasks. Deferred as RT-009/RT-035 and unfixed.
- fix: Call s.close() on each subscription filtered out by the reap in TaskStore.reap_dead_subscriptions before rebinding record.subscriptions, matching close_streams() and evict().
- sdkCandidate: true

### RT-011
- severity: low
- file: agent_sdk/common/admission.py
- description: SlotTable is declared and constructed as an OrderedDict (admission.py:93, :110, :114) but no ordering semantics are ever used — `grep -n "move_to_end\|popitem"` across admission.py, routes/mcp.py and routes/a2a.py hits only _sessions() at mcp.py:250 and :271, which genuinely needs LRU. The type is vestigial from the evict-oldest design mcp.py:151-160 explicitly rejects and invites a contributor to reintroduce the eviction that comment forbids. Separately, count_for_owner and count_for_task (admission.py:141-151) are O(n) scans over up to 500 entries on every admission of every stream route.
- fix: Change the structure and its annotations to a plain dict[str, StreamSlot] in slot_table/prune_finished/count_for_owner/count_for_task so the reject-not-evict intent is expressed in the type, and keep per-owner and per-task counts in Counter/defaultdict(int) maps updated at register and release for O(1) admission.
- sdkCandidate: true

## Instruction

Fix remaining findings, then re-run /wave w040.
