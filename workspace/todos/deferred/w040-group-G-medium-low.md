wave: w040
group: G
date: 2026-08-19

## Findings

### RT-001
- severity: medium
- file: DESIGN.md
- description: Neither route's behavior change is recorded in the SDK's ground-truth docs. DESIGN.md:274's error table still lists -32004 as 'unsupported blocking, any unimplemented method' — terminal-task resume, the entire subject of GH-144, is absent, and the interrupt/resume paragraph at :266-268 says only 'terminal state -> error' with no code. DESIGN.md:351 still describes GET /mcp as returning text/event-stream with heartbeats and never mentions the 429 cap; agent_sdk/routes/mcp.py:8-9's module docstring verb summary likewise says only 'Returning 405 here breaks Claude.ai Desktop — never'. REVIEWS.md:452-453 (Round 10 rows 1 and 2) still read 'DEFER to a future wave ... Tracked for the next /gh-review triage cycle' for both issues this wave closed. LRN-118's Prevention clause explicitly requires DESIGN.md and REVIEWS.md updated in the same commit as the code/docstring fix.
- fix: Add the terminal-task trigger to DESIGN.md's -32004 table row and name the code in the interrupt/resume paragraph; add the GET /mcp 429 cap (constants, 429-reject strategy, global + per-identity) to DESIGN.md §5.5 and to mcp.py's module-docstring GET bullet; mark REVIEWS.md Round 10 rows 1-2 resolved with GH-143/GH-144 references.
- sdkCandidate: true

### RT-002
- severity: medium
- file: docs/protocols.md
- description: docs/protocols.md:20 states 'terminal-task resume or cancel -> 409 -32002'. Terminal-task resume has never returned 409/-32002: it returned -32004/501 on message/send and -32001/404 on message/stream, and now returns -32004/501 on both. GH-144's AC-3 required the stale in-code comment be corrected, but the user-facing page carrying the identical stale claim was left untouched, so docs/protocols.md is now the only place in the tree asserting a wrong code for the exact condition this wave normalized. A client implemented against this page will branch on 409 and never match.
- fix: Split the clause at docs/protocols.md:20 into 'terminal-task cancel -> 409 -32002; terminal-task resume (taskId on message:send or message:stream) -> 501 -32004'.
- sdkCandidate: true

### RT-003
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: The new 429 branches at mcp.py:745-763 emit Retry-After: 5, but agent_sdk/common/cors.py:28 sets _EXPOSE_HEADERS = b"WWW-Authenticate, Mcp-Session-Id, X-A2A-Extensions" — neither Retry-After nor MCP-Protocol-Version is exposed. A cross-origin browser MCP client (Claude.ai web, a first-class target of this SDK) therefore cannot read the backoff hint and will retry immediately, defeating the backpressure the cap exists to provide. This is the LRN-004 failure class (a header emitted but never exposed to the browser) applied to a newly added header.
- fix: Add Retry-After to _EXPOSE_HEADERS in agent_sdk/common/cors.py:28 and extend the CORS preflight/expose-headers test to assert its presence.
- sdkCandidate: true

### RT-004
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: MCP Streamable HTTP requires the server to either return Content-Type: text/event-stream on GET or else return HTTP 405 (harness/reference/mcp-protocol.md:266, harness/reference/mcp-claude-platforms.md:87,298). The new 429 at mcp.py:745-763 is a third outcome. The pre-existing 400 on this verb carries an explicit §10 spec citation and a GH-111 rationale; the 429's comment block at :109-124 justifies the strategy (reject vs evict) but cites no spec text for emitting a status the GET contract does not enumerate, and DESIGN.md records no deviation. Every other deliberate deviation in this codebase (void-result parity, two-value audience set, serverInfo.title gating) is explicitly documented as such.
- fix: Add a spec citation plus deviation rationale to the _MAX_GET_STREAMS comment block at mcp.py:109-124, and record the deviation in DESIGN.md §5.5 in the same shape used for the §5.6 void-result parity deviation.
- sdkCandidate: true

### RT-005
- severity: low
- file: agent_sdk/routes/mcp.py
- description: Neither 429 branch at mcp.py:745-763 logs anything, although mcp.py logs every other rejection class via logger.warning at :442, :456, :464, :476 and :543. An operator hitting the global cap — or a permanently leaked one per RT-001 — gets no signal at all; the symptom presents as 'Claude.ai stopped connecting' with nothing in the logs and no way to distinguish saturation from leak.
- fix: Add logger.warning("mcp get stream cap reached scope=%s open=%d", scope, len(streams)) to both branches, emitting only a static scope label ('global'/'identity') and the count — never the identity key, per the todo's SI-2 annotation.
- sdkCandidate: true

### RT-006
- severity: low
- file: agent_sdk/routes/mcp.py
- description: _get_streams at mcp.py:185-196 returns an OrderedDict, but nothing ever calls popitem or move_to_end — ordering is never read. It directly contradicts the strategy comment at :110-122 ('429-reject, NOT evict-oldest'), and its docstring cites _sse_queues() as the pattern it mirrors, which is a plain dict. Separately, owner_count = sum(1 for v in streams.values() if v == owner) at :755 is an O(n) scan over up to 500 entries on every GET /mcp.
- fix: Use a plain dict[str, str] plus a Counter/defaultdict(int) of per-owner counts kept in sync at register and release, giving O(1) per-identity admission; keep OrderedDict only if RT-001 is resolved by adopting eviction, in which case make the eviction call site explicit.
- sdkCandidate: true

### RT-007
- severity: medium
- file: template/.claude/skills/acceptance/SKILL.md
- description: Only harness/skills/acceptance/SKILL.md (the authoring source) was updated for GH-144. Two other tracked copies of the same multi-turn A2A contract still carry the pre-LRN-103 instruction: template/.claude/skills/acceptance/SKILL.md:188-193 and .claude/skills/acceptance/SKILL.md:188-192 both say 'For turns 2–N (up to maxTurns), send the follow-up message in the same task context by including the taskId from the prior response', with no completed-vs-interrupted split at all. That is the exact driver pattern LRN-103 exists to prevent, and after GH-144 it now fails 501/-32004 on every turn after the first instead of 404/-32001 — so every multi-turn acceptance run following these docs breaks. template/.claude/skills/ is the peer-repo runtime copy that /acceptance actually executes for downstream agents (LRN-071, LRN-085), and LRN-086 explicitly requires the companion SKILL.md to move in the same change as the wire contract it documents.
- fix: Port the harness copy's completed-vs-interrupted split (interrupt states → send taskId; terminal states → send contextId with no taskId, else 501/-32004) verbatim into .claude/skills/acceptance/SKILL.md and template/.claude/skills/acceptance/SKILL.md. The template copy lands via commit+push to wailuen/a2a-agent-template per LRN-071; verify with `diff harness/skills/acceptance/SKILL.md template/.claude/skills/acceptance/SKILL.md` and `git -C template/ log --oneline -1`.
- codify: When a wave edits one copy of a mirrored SKILL.md, diff every tracked sibling copy (.claude/, template/.claude/) in the same change — updating only the authoring source leaves the copy that actually executes documenting the pre-fix wire contract.
- sdkCandidate: true

### RT-008
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: GET /mcp can now return HTTP 429 (lines 777-796), a third outcome beyond the two the MCP 2025-06-18 Streamable HTTP GET contract enumerates ('the server MUST either return Content-Type: text/event-stream ... or else return HTTP 405'). Neither the module docstring (lines 8-9: 'GET /mcp — server→client SSE channel, held open with heartbeats. Returning 405 here breaks Claude.ai Desktop (pitchbook LRN-053) — never.') nor DESIGN.md:351 ('returns text/event-stream with heartbeats') was updated, so the SDK's own stated invariant for this verb is now false in both places. This breaks the file's own convention: the pre-existing non-SSE path on this verb (the 400 for a present-but-unrecognized MCP-Protocol-Version) IS documented in both, and its code comment cites the spec section (GH-111 / §10). The 429 branch cites only 'GH-143' — no spec citation for why a third status is admissible. Relatedly, Retry-After is hardcoded to '5' while a slot leaked past layers 1-2 only clears after _GET_STREAM_TTL_SECONDS (60s), so a client obeying Retry-After retries 12x before capacity can possibly return.
- fix: Add the 429 admission-control outcome to the mcp.py module docstring's GET bullet and to DESIGN.md §5.5's GET /mcp bullet, stating it is a load-shedding response outside the spec's SSE-or-405 pair and that 405 is still never returned. Cite the spec section the deviation departs from in the code comment at line 769, matching the GH-111/§10 citation style used at line 756. Set Retry-After coherently with the actual worst-case recovery window rather than a fixed 5.
- codify: A new non-conforming status on a protocol verb must update that verb's documented invariant (module docstring + DESIGN.md) and carry a spec citation for the deviation in the same change — a bare issue-number comment is not a spec citation.
- sdkCandidate: true

### RT-009
- severity: medium
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: GH-143's SI-2 annotation mandates that _identity_key()'s value (an OAuth subject or API-key id), the Authorization header, and Mcp-Session-Id must never appear in the cap-rejection response body, and that the emitted 429 must be a static message. No test asserts anything about the 429 body — all four live tests assert only status_code == 429 (lines asserting `r3.status_code == 429`, `r_a2.status_code == 429`, `r_c.status_code == 429`, `r_full.status_code == 429`). Per LRN-128 an SI-tagged AC must land with a test asserting the AC's literal scenario, not a same-topic substitute. Separately, the entire RT-001 layer-3 mechanism (_prune_get_streams and _GET_STREAM_TTL_SECONDS) has zero direct coverage — which is why the cap bypass in RT-001 shipped green.
- fix: Add a test that mints an identity with a recognizable subject, drives the per-identity 429, and asserts the subject string, the bearer token, and any Mcp-Session-Id are absent from r.text and from caplog for agent_sdk.routes.mcp. Add direct coverage of _prune_get_streams: assert it does NOT reclaim an entry whose stream is still open (the RT-001 case), and that the number of still-open GET /mcp responses never exceeds _MAX_GET_STREAMS across a sequence of admissions spanning the TTL.
- codify: An SI-2-annotated AC about response-body content needs a test that greps the actual emitted body and logs for the forbidden value — asserting only the status code leaves the invariant unenforced.
- sdkCandidate: true

### RT-010
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: GH-144's stated root cause is that message/stream carries its own terminal check that diverged from _resume_or_error's. The landed fix keeps both checks and duplicates the literal error message: `record.task.status.state in TERMINAL_STATES` plus 'task is in a terminal state and cannot accept new messages' now appears at :335-341 (message_stream) and again at :199-204 (_resume_or_error), so the structural cause — two independent terminal predicates on the same logical condition — survives and can diverge again on the next edit. No test asserts parity between the two methods: test_send_terminal_taskid_returns_unsupported and test_stream_terminal_taskid_returns_unsupported each assert the constant independently, so a future one-sided change to either code or message stays green.
- fix: Hoist the terminal predicate and its message into one helper (e.g. `_terminal_reject(record) -> JSONResponse | None`) called by both paths, so message_stream can reject before _open_stream without a second copy of the literal. Add a parity test that drives the identical terminal-task input through both /v1/message:send and /v1/message:stream and asserts the two responses have the same status_code, the same error.code, and the same error.message.
- codify: Reconciling two diverged error paths by duplicating the predicate leaves the divergence possible — extract one shared check and lock it with a cross-method parity test asserting identical status, code, and message.
- sdkCandidate: true

### RT-011
- severity: medium
- file: CHANGELOG.md
- description: No entry exists for GH-143 or GH-144, and the file has no '## [Unreleased]' section — its newest heading is '## [0.6.0] — 2026-08-18', while the todo targets v0.6.1. GH-144 changes a live A2A RPC's consumer-visible outcome for message/stream from HTTP 404 / -32001 to HTTP 501 / -32004; any consumer branching on 404-means-gone now sees 501. Per DESIGN.md §4.0 this needs an explicit entry, and the wire-shape conformance exemption cannot be cited for it (that exemption requires the changed shape to live in models/ — this is route behavior in routes/a2a.py). LRN-145 requires such entries land under Unreleased, never inside an already-tagged release section.
- fix: Add a '## [Unreleased]' section above [0.6.0] with an entry for GH-144 under a behavior/breaking heading stating both directions (emit: message/stream terminal-taskId now 501/-32004; consumer impact: clients matching on 404/-32001 must add -32004), and an entry for GH-143 describing the new GET /mcp concurrency caps and the 429 response.
- codify: A change to a live RPC's emitted HTTP status or error code is consumer-visible and needs its own CHANGELOG entry under Unreleased, with both emit and consume impact stated, even when no models/ type changed.
- sdkCandidate: true

### RT-012
- severity: low
- file: workspace/todos/active/w040-gh-issues.md
- description: Both todos declare only '(modifies agent_sdk/routes/<file>.py)' as Creates:, but the wave's working tree also modifies two tracked files declared in neither todo: harness/skills/acceptance/SKILL.md (a wire-contract doc, changed as part of GH-144) and uv.lock (agent-sdk 0.5.44 -> 0.6.0, an unrelated leftover from the v0.6.0 release commit which forgot to regenerate it). LRN-168 requires every tracked file a wave touches to carry its own Creates:/Modifies: line; LRN-160 requires paths named only in SI:/Reuses: prose to be promoted onto those lines. The undeclared SKILL.md is exactly the file whose sibling copies were then missed (RT-003) — undeclared scope is why the mirror sweep never happened.
- fix: Add 'Modifies: harness/skills/acceptance/SKILL.md' plus the two sibling copies (.claude/skills/acceptance/SKILL.md, template/.claude/skills/acceptance/SKILL.md with the LRN-071 peer-repo annotation) to the GH-144 todo. Either declare the uv.lock refresh explicitly or revert it out of this wave and land it as its own release-hygiene fix.
- sdkCandidate: false

### RT-013
- severity: low
- file: REVIEWS.md
- description: REVIEWS.md:449-452 (Round 10's 'Deferred (not fixed in this release)' table) still records both findings as 'DEFER to a future wave ... Tracked for the next /gh-review triage cycle' with no resolution marker, even though this wave is that cycle and both are now fixed. The document therefore reports outstanding work that no longer exists — the same contradictory state signal LRN-100 was codified to prevent ('the deferred marker must be relocated once findings are resolved; deferred/ must only ever contain files with at least one OPEN finding').
- fix: Annotate both Round 10 deferred rows as RESOLVED, naming the wave (w040), the issues (GH-143, GH-144), and the guarding tests (tests/test_gh143_mcp_get_stream_cap.py, tests/test_w017_gh51_multiturn.py::test_stream_terminal_taskid_returns_unsupported), so the durable disposition record matches the landed code.
- sdkCandidate: false

### RT-014
- severity: medium
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: test_prune_never_evicts_a_still_open_stream_regardless_of_elapsed_time (line 321) claims to prove a wall-clock TTL can never reclaim a live slot, but at lines 347-348 it monkeypatches time.monotonic on the stdlib time module (verified: mcp_module.time is time -> True) while agent_sdk/routes/mcp.py never calls time.monotonic — it uses time.time() only, at lines 168, 187, 192, 733. The guard is therefore not exercised: a regression reintroducing a time.time()-based TTL prune would pass this test unchanged, and its remaining assertions merely duplicate test_global_cap_rejects_once_reached_across_identities. Worse, asyncio.base_events.BaseEventLoop.time() resolves time.monotonic() through that same module attribute (verified by source inspection), so the patch shifts the event-loop clock by +10,000s for the remainder of the test, instantly expiring every timer scheduled before it — including t1's already-running asyncio.sleep(_HEARTBEAT_SECONDS) and httpx/anyio internal timeouts. That is a latent flake in a test whose whole subject is timing.
- fix: Remove the global time.monotonic patch. Assert the invariant directly instead: call _prune_get_streams() on a dict seeded with a sentinel asyncio.Task that is not done() and assert the entry survives, then let the task complete and assert it is reclaimed. If a wall-clock guard is genuinely wanted, patch mcp_module.time.time (what the module actually reads) rather than mutating the stdlib clock asyncio depends on.
- sdkCandidate: true

### RT-015
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: GET /mcp now has a third response shape — 429 with an application/json body (lines 779-798) — that contradicts the repo's own protocol references and is documented nowhere. harness/reference/mcp-protocol.md:266 enumerates exactly two legal outcomes ('server returns text/event-stream or 405 if none offered'), and harness/reference/mcp-claude-platforms.md:87 and :298 repeat it ('GET <mcp-path> returns text/event-stream or 405 (never 200+JSON/HTML)'). More pointedly, mcp-claude-platforms.md:44 and P8 debug checklist item 1 name a 429 on the MCP path as a known Claude.ai 'Couldn't connect' failure mode — the SDK is now itself the thing emitting it, on a route whose own module docstring (mcp.py:8-9) declares connection-criticality ('Returning 405 here breaks Claude.ai Desktop (LRN-053) — never'). No documentation was updated: mcp.py:8-9, DESIGN.md:351, and docs/protocols.md's MCP section (lines 73-80) all still describe GET /mcp as unconditionally text/event-stream. This is asymmetric with the GH-144 half of the same wave, which updated DESIGN.md, docs/protocols.md, LRN-103 and added static doc-pinning tests (tests/test_gh144_terminal_resume_error_docs.py).
- fix: Document the cap and its rejection status in mcp.py's module docstring, DESIGN.md section 5.5 line 351, and docs/protocols.md's MCP section, each with a citation justifying the deviation from the two-outcome rule in harness/reference/mcp-protocol.md:266. Consider 503 + Retry-After instead of 429: it carries the same semantics without matching the CDN/WAF rate-limiter signature that harness/reference/mcp-claude-platforms.md:44 and P8 item 1 flag as an un-debuggable Claude.ai connect failure. Add a doc-pinning test mirroring tests/test_gh144_terminal_resume_error_docs.py so the code and docs cannot drift.
- sdkCandidate: true

### RT-016
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: Both cap-rejection branches (lines 779-787 and 790-798) return with no log line, no counter, and no metric, and the caps are hard-coded module constants (lines 124-125) with no AGENT_SDK_-prefixed setting. Cap exhaustion therefore presents to the user as an opaque Claude.ai 'Couldn't connect' with nothing in the server logs to distinguish it from an auth, CORS, or network fault — while harness/reference/mcp-claude-platforms.md P8 makes 'is something returning 403/429 on the MCP path?' the very first debug question. There is also no operational escape hatch: an operator who hits the per-identity limit of 8 cannot raise it without a code change and redeploy, unlike comparable safety bounds which are settings (AGENT_SDK_INTERRUPT_TTL, AGENT_SDK_MAX_INTERRUPTED per DESIGN.md:299). The todo's own SI-2 annotation anticipated a rejection log line ('must never appear in ... any eviction/rejection log line'), implying one was expected to exist.
- fix: Add logger.warning at each rejection with the scope and current depth only — e.g. logger.warning('mcp get stream cap reached scope=%s open=%d', 'global', len(streams)) — never the identity key or any header value (SI-2). Promote _MAX_GET_STREAMS and _MAX_GET_STREAMS_PER_IDENTITY to AGENT_SDK_-prefixed settings on BaseAgentSettings with the current values as defaults.
- sdkCandidate: true

### RT-017
- severity: medium
- file: harness/skills/acceptance/SKILL.md
- description: The wave edited the harness authoring copy at line 200 (404 / -32001 -> 501 / -32004) but neither runtime delivery copy was updated: .claude/skills/acceptance/SKILL.md and template/.claude/skills/acceptance/SKILL.md both still teach the old behavior. LRN-085's rule applies by construction (harness/ is the authoring source; template/.claude/ is the runtime copy /acceptance actually executes, landing via commit+push to wailuen/a2a-agent-template per LRN-071) even though LRN-085's literal text scopes itself to harness/workflows/*.js. Scoping note to avoid over-attribution: both runtime copies were ALREADY far staler than this change — they predate w026/GH-90 entirely and still instruct the driver to resend taskId on turns 2+ with no contextId branch at all — so w040 did not create the drift. It did make the consequence worse: an acceptance run off the runtime copy now receives 501/-32004, a code that appears in none of the runtime docs and that the driver has no handling for, where it previously received the 404/-32001 those docs at least named.
- fix: Re-sync the whole file (not just the changed line) from harness/skills/acceptance/SKILL.md into template/.claude/skills/acceptance/SKILL.md and commit+push to wailuen/a2a-agent-template per LRN-071, then refresh .claude/skills/acceptance/SKILL.md. Extend LRN-085's Prevention clause to cover harness/skills/**/SKILL.md, not just harness/workflows/*.js, so future waves list the peer-repo copy as an explicit deliverable.
- sdkCandidate: true

### RT-018
- severity: low
- file: agent_sdk/routes/mcp.py
- description: Bare `assert owning_task is not None` at line 805 sits on the live request path. Under python -O asserts are stripped, so a None would be stored as (owner, None) at line 806 and the next request's _prune_get_streams (line 224, rec[1].done()) would raise AttributeError: 'NoneType' object has no attribute 'done' — turning every subsequent GET /mcp into a 500, i.e. a hard connector failure on the route the module docstring calls connection-critical. asyncio.current_task() cannot in practice be None inside a running coroutine, so this is defensive-only, but the failure mode chosen is the worst available one.
- fix: Replace the assert with an explicit branch: if owning_task is None, skip registration and serve the stream untracked (degrading the cap rather than breaking the route), or raise a typed RuntimeError at boot-visible severity. Reserve bare asserts for module-level invariants like the one at mcp.py:86.
- sdkCandidate: true

### RT-019
- severity: low
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: The todo's SI-2 annotation explicitly required that the emitted 429 be 'a static message' carrying no identity-derived value (_identity_key returns kind:subject — an OAuth subject or API-key id). The landed code satisfies this, but no test pins it: test_per_identity_cap_rejects_extra_stream (line 101) and test_global_cap_rejects_once_reached_across_identities (line 160) assert only status_code == 429. A future edit adding the identity or session id to the rejection body or a Retry-After-adjacent header for 'better diagnostics' would pass the whole suite.
- fix: Add an assertion to both 429 tests that the response body and headers contain neither _identity_key(identity) nor the identity's subject/api-key id, mirroring the SI-2 regression tests already present in tests/test_rt001_mcp_body_validation_error_log_leak.py.
- sdkCandidate: true

### RT-020
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: `release()` is defined as a plain `def` (mcp.py:824-828, mcp.py:940-944) and passed to `BackgroundTask` (mcp.py:850, mcp.py:967). Starlette 1.3.1's `BackgroundTask.__call__` dispatches non-async callables via `run_in_threadpool`, so the concurrency limiter's slot release mutates event-loop-owned state (`app.state.mcp_get_streams`, `app.state.mcp_sse_queues`) from an anyio worker thread and queues behind the default 40-thread limiter — precisely under the mass-teardown burst the cap exists to bound, lengthening the 429 lockout window.
- fix: Change both `def release()` declarations to `async def release()`. Starlette then awaits them directly on the event loop, keeping the mutation on-loop and deterministic within the response cycle. No other change required.
- codify: A Starlette BackgroundTask wrapping a plain `def` runs in a threadpool — lifecycle hooks that mutate event-loop-owned state must be declared `async def`.
- sdkCandidate: true

### RT-021
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: The ~22-line stream-admission block (prune, global cap check, `_identity_key` + per-identity count, uuid + current_task registration) is copy-pasted verbatim between `mcp_get` (mcp.py:790-822) and `mcp_sse` (mcp.py:914-934), and the two copies have ALREADY diverged: `mcp_get`'s 429 responses carry the `MCP-Protocol-Version` header while `mcp_sse`'s do not. The capability is not registered in workspace/components/README.md despite being reusable admission control (Dimension 8: unregistered reusable utility).
- fix: Extract `_admit_stream(app, identity, *, headers: dict[str, str]) -> tuple[str, asyncio.Task[Any]] | JSONResponse` (or a small register/release context manager) covering prune + both cap checks + registration, call it from both routes with the route-appropriate headers, and register it in workspace/components/README.md as a new C-NNN.
- codify: Two routes enforcing one shared budget must share one admission helper — a copy-pasted limiter drifts on the details (here, a missing MCP-Protocol-Version header) before the first review.
- sdkCandidate: true

### RT-022
- severity: medium
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: No test anywhere asserts that `GET /mcp` returns 200 with `content-type: text/event-stream`. Every GET /mcp test asserts 403 (tests/test_gh110_origin_allowlist.py:300), 429 (this module), or uses the `_still_streaming()` helper (tests/test_gh143_mcp_get_stream_cap.py:39-49), which only proves the request did not complete and never inspects `status_code` or headers. The route just gained two new 429 exit branches, and mcp.py:9 declares the 200/text-event-stream invariant load-bearing ('Returning 405 here breaks Claude.ai Desktop (pitchbook LRN-053) — never'). A regression turning the admitted path into a non-200 or non-SSE response would pass the entire 2058-test suite.
- fix: Add a happy-path test driving GET /mcp through a raw ASGI scope with a send-capture (the pattern already used at tests/test_gh143_mcp_get_stream_cap.py:252-278) asserting `http.response.start` carries status 200 and a `content-type: text/event-stream` header plus the first padding-comment body chunk; add the equivalent for GET /mcp/sse asserting the `event: endpoint` first frame.
- codify: When a route gains rejection branches, its happy path needs an explicit status+content-type assertion — 'the request did not complete' is not proof it returned 200 SSE.
- sdkCandidate: true

### RT-023
- severity: medium
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: `test_prune_never_evicts_a_still_open_stream_regardless_of_elapsed_time` (line 348) patches `mcp_module.time.monotonic`, but agent_sdk/routes/mcp.py never calls `time.monotonic` — it uses `time.time()` exclusively (lines 177, 196, 201, 748). The test's stated invariant ('a still-open slot must never be reclaimed by wall-clock pruning') is therefore unguarded: reintroducing a `time.time()`-based TTL would leave the test green. Separately, `mcp_module.time` IS the stdlib `time` module, so the patch shifts asyncio's own event-loop clock (BaseEventLoop.time() -> time.monotonic()) by +10,000s process-wide for the test's duration, firing every pending timer immediately.
- fix: Patch `mcp_module.time.time` (the clock the module actually reads) rather than `time.monotonic`, or drop the clock patch entirely and assert the invariant structurally — e.g. `assert 'time.' not in inspect.getsource(mcp_module._prune_get_streams)` — so a future TTL reintroduction on any clock is caught.
- codify: A test that patches a clock the module under test never reads asserts nothing; assert against the exact time source the code calls, or assert structurally that no time source is referenced.
- sdkCandidate: true

### RT-024
- severity: medium
- file: CHANGELOG.md
- description: The GH-143 MCP change is client-visible — `GET /mcp/sse` drops from 500 concurrent sessions with no per-identity limit to 8 per identity, and both GET routes can now return 429 where a well-formed authenticated request previously always returned 200 text/event-stream — yet it is filed only under the `🟠 Security` heading with no Migration callout, while the strictly smaller GH-144 A2A error-code change in the same wave received a dedicated `🔴 Breaking changes` heading plus Migration callout plus docs/protocols.md and DESIGN.md updates. docs/protocols.md's MCP section (lines 74-80) still documents only auth, tools/list Tier-1 exposure, and Mcp-Session-Id — the admission cap, the 429 status, and the Retry-After header appear nowhere in the public protocol docs.
- fix: Add the 429 + `Retry-After: 5` admission cap and the per-identity limit to docs/protocols.md's MCP bullet list, and add a Migration callout to the CHANGELOG entry naming the `_MAX_GET_STREAMS_PER_IDENTITY = 8` default so operators whose clients hold more than 8 concurrent streams under one identity can react before upgrading.
- codify: A change that can turn a previously-always-200 protocol route into a rejection needs the same Breaking-changes + Migration + protocol-docs treatment as a wire-shape change, regardless of which CHANGELOG heading it feels like it belongs under.
- sdkCandidate: true

### RT-025
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: `_MAX_GET_STREAMS = 500` and `_MAX_GET_STREAMS_PER_IDENTITY = 8` (mcp.py:133-134) are hard-coded module privates with no `BaseAgentSettings` override, unlike the comparable `rate_limit_per_minute` / `unauth_rate_limit_per_minute` knobs at agent_sdk/config.py:107-108. In the common deployment where every caller presents the same API key, `_identity_key()` collapses all of them onto one owner string, so the whole process is capped at 8 concurrent MCP streams — a 98% cut from the previous 500 — with no supported way to raise it short of monkeypatching a private module attribute.
- fix: Expose both caps as `BaseAgentSettings` fields (e.g. `AGENT_SDK_MAX_MCP_STREAMS`, `AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`) read from `request.app.state.settings` at admission time, keeping 500 / 8 as defaults so existing behavior is unchanged.
- codify: A hard-coded admission cap on an authenticated route needs a Settings override — an operator whose legitimate load exceeds the default otherwise has no path but monkeypatching a private.
- sdkCandidate: true

### RT-026
- severity: low
- file: agent_sdk/routes/mcp.py
- description: `assert owning_task is not None` (mcp.py:821 and mcp.py:933) is used as request-path control flow purely to narrow the mypy type of `asyncio.current_task()`. Under `python -O` the assert is stripped, `(owner, None)` is stored in `_get_streams()`, and the next request's `_prune_get_streams` raises `AttributeError: 'NoneType' object has no attribute 'done'` inside the list comprehension at mcp.py:239 — before any `streams.pop()` executes — so the poisoned entry is never removed and every subsequent GET /mcp and GET /mcp/sse returns 500 for the remaining process lifetime.
- fix: Replace the asserts with explicit handling: `owning_task = asyncio.current_task()` then `if owning_task is None: return JSONResponse(status_code=503, content={'error': 'stream unavailable'})`; and/or make the prune tolerant with `if rec[1] is None or rec[1].done()` so a malformed entry is reclaimed rather than poisoning the loop.
- sdkCandidate: true

### RT-027
- severity: low
- file: agent_sdk/routes/mcp.py
- description: `_get_streams()` (mcp.py:206-235) is annotated and constructed as an `OrderedDict` but no ordering semantics are ever used — there is no `popitem(last=False)` and no `move_to_end`, unlike `_sessions()` which genuinely needs LRU ordering. The type is vestigial from the evict-oldest design that mcp.py:124-132 explicitly rejected, and it invites a future contributor to reintroduce the eviction that comment forbids.
- fix: Change the structure and its annotations to a plain `dict[str, tuple[str, asyncio.Task[Any]]]` in `_get_streams`, `_prune_get_streams`, and the module-level type comments, so the reject-not-evict intent is expressed in the type itself.
- sdkCandidate: true

### RT-028
- severity: low
- file: agent_sdk/routes/a2a.py
- description: The literal `"task is in a terminal state and cannot accept new messages"` is now duplicated verbatim at a2a.py:204 (`_resume_or_error`, message/send) and a2a.py:341 (`message_stream`'s new terminal branch). The whole point of GH-144 was to make the two methods report the identical failure identically, but the tests assert only the numeric code (-32004) and HTTP status, so the two strings can silently drift apart again.
- fix: Hoist the string to a module-level constant (e.g. `_TERMINAL_TASK_MESSAGE = "task is in a terminal state and cannot accept new messages"`) referenced from both sites, and add an assertion in tests/test_w017_gh51_multiturn.py that message/send and message/stream return byte-identical `error.message` for the same terminal task.
- sdkCandidate: true

### RT-029
- severity: low
- file: workspace/todos/active/w040-gh-issues.md
- description: Both todos declare scope as `Creates: (modifies agent_sdk/routes/a2a.py)` / `(modifies agent_sdk/routes/mcp.py)` (lines 17 and 29) and name no test files, yet four new untracked test files landed with the wave: tests/test_gh143_mcp_get_stream_cap.py, tests/test_rt001_mcp_sse_stream_cap.py, tests/test_gh144_terminal_resume_error_docs.py, tests/test_changelog_gh143_gh144_wire_changes.py. Per LRN-053 (wave scope must union Creates: AND Modifies:) and LRN-121 (pre-archive `??` gate), files a todo produces must appear in its scope declaration.
- fix: Update both todo entries' `Creates:` lines to name the test files each produced before archiving w040, so downstream scope derivation and the pre-archive untracked-file gate see the full change set.
- sdkCandidate: false

### RT-030
- severity: medium
- file: DESIGN.md
- description: GH-143 adds a new wire-visible response (429 + Retry-After) to two protocol routes, but the SDK's own spec surfaces were not updated. DESIGN.md:351 still reads "`GET /mcp` — server->client SSE channel: returns `text/event-stream` with heartbeats" with no mention of the cap or 429; DESIGN.md:355 describes the legacy SSE pair without noting it now shares the same budget; DESIGN.md:396's "Rate limiting — two layers" is now three layers. docs/protocols.md's MCP section (lines 73-81) documents no 429 at all. The GH-144 half of the same wave did update both DESIGN.md:277 and docs/protocols.md:19-24, so the omission is asymmetric within one wave.
- fix: Add the shared admission cap and the 429/Retry-After response to DESIGN.md §5.3's GET /mcp and legacy-SSE bullets and to §6's rate-limiting paragraph (now three layers), and add a corresponding line to docs/protocols.md's MCP section.
- sdkCandidate: true

### RT-031
- severity: medium
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: The new 429 responses introduce three headers/body facts that no test asserts. tests/test_gh143_mcp_get_stream_cap.py:115,138,183,211,359 and tests/test_rt001_mcp_sse_stream_cap.py:99,132,169,214 assert only `status_code == 429`. Nothing asserts `Retry-After: 5` (agent_sdk/routes/mcp.py:843,854,965,973), nothing asserts mcp_get's rejections carry MCP-Protocol-Version (mcp.py:844,855), and nothing asserts the body carries no identity-derived value — the explicit SI-2 requirement in the todo at workspace/todos/active/w040-gh-issues.md:40, since _identity_key() returns an OAuth subject / API-key id. LRN-001 (severity high) requires TestClient-level header assertions for any wave touching a protocol route. A regression dropping Retry-After, dropping the version header, or interpolating _identity_key(identity) into the rejection message would pass green.
- fix: Extend both cap test modules to assert `r.headers['Retry-After'] == '5'`, assert `MCP-Protocol-Version` is present on mcp_get's 429 (and document its deliberate absence on mcp_sse's), and add an assertion that the 429 body text contains neither identity.subject nor the bearer token.
- sdkCandidate: true

### RT-032
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: _MAX_GET_STREAMS = 500 and _MAX_GET_STREAMS_PER_IDENTITY = 8 (agent_sdk/routes/mcp.py:133-134) are hard-coded module constants with no AGENT_SDK_* override, unlike every comparable operational bound (agent_sdk/config.py:102-109: AGENT_SDK_INTERRUPT_TTL, AGENT_SDK_MAX_INTERRUPTED, AGENT_SDK_TASK_TTL, AGENT_SDK_RATE_LIMIT, AGENT_SDK_UNAUTH_RATE_LIMIT). Because the per-identity budget of 8 is now shared between GET /mcp and GET /mcp/sse, a deployment following the documented P9.7 dual-transport workaround (harness/reference/mcp-claude-platforms.md:355-358) or hitting claude.ai web bug #291 ("GET polls ~5s", :271) can saturate one OAuth subject's 8 slots and then receive 429 instead of text/event-stream — the failure mode DESIGN.md:351 records as breaking the Claude.ai connector. An operator hitting this has no knob and no recovery other than waiting.
- fix: Expose both caps as settings (e.g. AGENT_SDK_MAX_MCP_STREAMS / AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY in agent_sdk/config.py) read at request time, and add a note to mcp_get's docstring tying the 429 path back to the LRN-053/Claude.ai-connector constraint so the tradeoff is visible at the call site.
- sdkCandidate: true

### RT-033
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: The admission block — _get_streams + _prune_get_streams + global cap + per-identity `sum(1 for rec in streams.values() if rec[0] == owner)` + two 429 JSONResponse bodies — is duplicated verbatim between mcp_get (agent_sdk/routes/mcp.py:833-856) and mcp_sse (agent_sdk/routes/mcp.py:959-976), including the two identical rejection message strings. The two copies have already diverged: mcp_get's 429s carry MCP-Protocol-Version, mcp_sse's do not. Dimension 8: a second implementation of a registered capability. Any future indefinite-stream route on this router will be a third copy.
- fix: Extract `_admit_stream(request, identity, *, extra_headers) -> tuple[str, Callable[[], None]] | JSONResponse` performing prune, both cap checks, slot-id generation, owning-task capture and slot registration, returning either the (stream_id, release) pair or the 429 response; call it from both routes and register it in workspace/components/README.md so the next stream route reuses it.
- sdkCandidate: true

### RT-034
- severity: low
- file: agent_sdk/routes/mcp.py
- description: `assert owning_task is not None` at agent_sdk/routes/mcp.py:864 and :978 establishes the _StreamRecord type invariant with a bare assert. Under `python -O` the assert is stripped, a None owner is stored in _get_streams(), and _prune_get_streams's `rec[1].done()` then raises AttributeError on every subsequent admission for BOTH routes; because the exception escapes before `streams.pop(sid, None)`, the poison record is never cleared, permanently 500-ing GET /mcp and GET /mcp/sse with no self-heal. agent_sdk/tasks/memory.py:86-89 handles the identical asyncio.current_task() case defensively (`owner_task is None` -> never reaped), so the two halves of the same fix disagree on hardening.
- fix: Replace the asserts with the memory.py treatment: allow a None owner in _StreamRecord (`asyncio.Task[Any] | None`) and have _prune_get_streams skip records whose task is None, so a slot that cannot be liveness-keyed is simply never auto-reaped instead of poisoning the reaper.
- sdkCandidate: true

### RT-035
- severity: low
- file: agent_sdk/tasks/memory.py
- description: The reap at agent_sdk/tasks/memory.py:80-85 drops orphaned Subscription objects out of record.subscriptions without calling sub.close(), so a reaped subscription's queue never receives the _CLOSE sentinel. Every other removal path in this file closes first (close_streams at :117-121, evict at :212-214). The asymmetry is currently harmless (a reaped orphan by definition has no live reader, since its owning task is done) but makes the removal contract inconsistent and would silently strand any future caller that holds a Subscription across tasks.
- fix: Call `s.close()` on each subscription filtered out by the reap before rebinding record.subscriptions, matching close_streams() and evict().
- sdkCandidate: true

### RT-036
- severity: low
- file: agent_sdk/routes/a2a.py
- description: The a2a layer-3 backstop only runs inside InMemoryTaskStore.subscribe for the record being subscribed to, so an orphan left by a hard-cancelled /v1/tasks/{id}:subscribe on a task that is never re-subscribed persists until that task is evicted (AGENT_SDK_TASK_TTL, default 1h). Meanwhile the still-running worker's store.publish walks that orphan for every frame and fills its 256-slot queue until it self-kills. The memory.py:76-77 comment claims the list is "bounded here", which is true only per re-subscribed task, not per task.
- fix: Either sweep dead-owner subscriptions in publish()/touch() as well as subscribe(), or narrow the memory.py comment to state the bound is per-task-on-next-subscribe so the residual window is documented rather than implied away.
- sdkCandidate: true

## Instruction

Non-blocking — these did not block w040's archive. Address opportunistically or fold into a future wave.
