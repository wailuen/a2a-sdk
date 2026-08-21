wave: w040
scope: phase
date: 2026-08-19

## Findings

### RT-001
- severity: medium
- file: DESIGN.md
- description: GET /mcp's new 429 outcome is absent from every SDK ground-truth doc and carries no spec-deviation citation. DESIGN.md:351 still reads "GET /mcp — server->client SSE channel: returns text/event-stream with heartbeats"; DESIGN.md:355 (legacy SSE pair) does not note it now shares the same budget; DESIGN.md:396 still says "Rate limiting — two layers" when there are now three; docs/protocols.md's MCP section (line 73 onward) documents no 429, no Retry-After and no cap. harness/reference/mcp-protocol.md:265-266 enumerates exactly two legal GET outcomes ("server returns text/event-stream or 405 if none offered"), repeated at harness/reference/mcp-claude-platforms.md:87 and :298, and mcp-claude-platforms.md:44 names a 429 on the MCP path as a known Claude.ai "couldn't connect" failure mode. The pre-existing non-SSE outcome on this verb (the GH-111 400) cites its spec section at mcp.py:847-852; the 429 block cites only "GH-143". The GH-144 half of the same wave did update DESIGN.md:277 and docs/protocols.md:20 and pinned them with tests/test_gh144_terminal_resume_error_docs.py, so the omission is asymmetric within one wave. AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY is likewise absent from DESIGN.md, which documents the comparable AGENT_SDK_INTERRUPT_TTL / AGENT_SDK_MAX_INTERRUPTED at :299. Separately, `Retry-After: 5` is a fixed guess: recovery depends entirely on some other client disconnecting, not on elapsed time, so the hint is not coherent with the actual recovery window. Raised repeatedly across multiple redteam rounds and still unaddressed.
- fix: Add the shared cap and the 429 + Retry-After load-shedding outcome to DESIGN.md:351 and :355, state that 405 is still never returned, update DESIGN.md:396 to three layers, add the new setting near DESIGN.md:299, and add a 429 line to docs/protocols.md's MCP section. Cite harness/reference/mcp-protocol.md:266 in the code comment at mcp.py:860 as the rule the deviation departs from, in the same style as the GH-111 citation at mcp.py:847 — a bare issue-number comment is not a spec citation. Extend tests/test_gh144_terminal_resume_error_docs.py's doc-pinning pattern to cover the MCP half, and either justify Retry-After: 5 in a comment or derive it from something real.
- codify: A new non-conforming status on a protocol verb must update that verb's documented invariant (module docstring, DESIGN.md, docs/protocols.md) and carry a spec citation for the deviation in the same change — a bare issue-number comment is not a spec citation.
- sdkCandidate: true

### RT-002
- severity: medium
- file: docs/protocols.md
- description: The A2A admission cap is documented nowhere at all. POST /v1/message:stream and POST /v1/tasks/{id}:subscribe can now return HTTP 429 with error code -32000 (agent_sdk/routes/a2a.py:348-360, translated by app.py's _a2a_auth_envelope) where a well-formed authenticated request previously always returned 200 text/event-stream. docs/protocols.md:13 still describes message:stream as unconditionally SSE and its error table (:19-24) lists no 429 and no -32000; DESIGN.md:274's A2A error code table has no -32000 row at all; neither _MAX_A2A_STREAMS, _MAX_A2A_STREAMS_PER_TASK nor Retry-After appears in any doc. In CHANGELOG.md the change is filed only under the 🟠 Security heading with no 🔴 Breaking changes heading and no Migration callout — the classification error LRN-153 (severity high) codifies, and a weaker standard than the wave itself insisted on for GH-144's strictly smaller error-code change.
- fix: Add the 429/-32000 admission rejection and Retry-After to docs/protocols.md's A2A error table and to DESIGN.md §5.1's error table plus the streaming bullets; move the A2A cap into a 🔴 Breaking changes CHANGELOG entry with a Migration callout naming _MAX_A2A_STREAMS = 500 and _MAX_A2A_STREAMS_PER_TASK = 16 so operators whose clients hold many concurrent subscriptions can react before upgrading.
- codify: A change that can turn a previously-always-200 protocol route into a rejection needs the same Breaking-changes heading, Migration callout and protocol-doc update as a wire-shape change, regardless of which CHANGELOG heading it feels like it belongs under.
- sdkCandidate: true

### RT-003
- severity: medium
- file: CHANGELOG.md
- description: GH-143's client-visible behaviour break is filed under `### 🟠 Security` with no Migration callout, while the strictly smaller GH-144 change in the same wave got a dedicated `### 🔴 Breaking changes` heading, a Migration callout, and docs/protocols.md + DESIGN.md updates. Yet GH-143 changes what a well-formed authenticated request receives: `GET /mcp` and `GET /mcp/sse` previously always returned 200 `text/event-stream` for an admitted caller (GET /mcp had no cap at all; GET /mcp/sse had a 500-entry evict-oldest map with no per-identity limit) and can now return 429. Under this SDK's own documented org-wide OAuth client / shared-API-key modes every caller in an org collapses onto one `identity_key()`, so an org holding more than `_MAX_GET_STREAMS_PER_IDENTITY = 200` concurrent connectors regresses on upgrade with no notice and no named default to react to. LRN-153: classify by wire impact, not by the heading it feels like it belongs under.
- fix: Promote the GH-143 admission-cap change to the `### 🔴 Breaking changes` heading (or add a Behavior-changes heading) with an explicit Migration callout naming `_MAX_GET_STREAMS = 500`, `_MAX_GET_STREAMS_PER_IDENTITY = 200`, `_MAX_A2A_STREAMS = 500`, `_MAX_A2A_STREAMS_PER_IDENTITY = 200`, `_MAX_A2A_STREAMS_PER_TASK = 16` and the two override env vars, so an operator whose clients hold more streams than that under one identity can react before upgrading.
- codify: A change that can turn a previously-always-200 protocol route into a rejection needs the same Breaking-changes + Migration treatment as a wire-shape change, with the shipped default named so operators can size against it.
- sdkCandidate: true

### RT-004
- severity: medium
- file: CHANGELOG.md
- description: The primary GH-143 Security entry (CHANGELOG.md:79) states the shipped default is `_MAX_GET_STREAMS_PER_IDENTITY = 8`. The code ships 200 (agent_sdk/routes/mcp.py:176). The correction only appears four bullets later at CHANGELOG.md:183, framed as 'the old hardcoded ... = 8'. A reader hitting the release's headline entry for this change gets a value that is 25x off, on the one number an operator sizing an org-wide OAuth deployment actually needs. `tests/test_changelog_gh143_gh144_wire_changes.py::test_changelog_gh143_security_entry` only asserts the substring `_MAX_GET_STREAMS` is present, so it cannot catch the wrong value.
- fix: Change CHANGELOG.md:79 to `_MAX_GET_STREAMS_PER_IDENTITY = 200` and note the org-wide-collapse rationale inline (or fold the two GH-143 bullets into one entry describing the shipped state, keeping the '8 was wrong' history as a sub-bullet). Add an assertion importing the constant from agent_sdk.routes.mcp and requiring its literal value to appear in the entry, so the two can never drift again.
- codify: A CHANGELOG entry must describe the state that SHIPS, not the state at the moment the entry was drafted — pin any constant it names with a test that imports the real value.
- sdkCandidate: true

### RT-005
- severity: medium
- file: CHANGELOG.md
- description: CHANGELOG [0.7.0]'s RT-002 A2A entry (lines 159-180) describes a two-layer admission — global _MAX_A2A_STREAMS=500 then per-task _MAX_A2A_STREAMS_PER_TASK=16 — but the landed code has three layers (a2a.py:392 global, :400 per-identity, :408 per-task). _MAX_A2A_STREAMS_PER_IDENTITY=200 and the brand-new operator-facing setting AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY (config.py:158) appear in no CHANGELOG entry and no documentation anywhere in the tree, and agent_sdk/config.py is missing from that entry's file list. Separately the GH-143 Security entry states the shipped constant as '_MAX_GET_STREAMS_PER_IDENTITY = 8' while the value that actually ships is 200 (mcp.py:146). `grep -n "MAX_A2A_STREAMS_PER_IDENTITY\|AGENT_SDK_MAX_A2A_STREAMS" CHANGELOG.md` returns zero matches, confirming the gap — while the exactly analogous MCP setting received a dedicated CHANGELOG entry in the same release. A new public settings field shipped in a release with zero operator-visible coverage.
- fix: Correct the RT-002 entry to describe all three admission layers, name _MAX_A2A_STREAMS_PER_IDENTITY=200 and AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY with its default, add agent_sdk/config.py to that entry's file list, correct the GH-143 entry's stated per-identity default to 200, and add a Migration callout (a previously-always-200 protocol route can now return 429). Document both AGENT_SDK_MAX_*_STREAMS_PER_IDENTITY settings in DESIGN.md alongside AGENT_SDK_INTERRUPT_TTL / AGENT_SDK_MAX_INTERRUPTED at DESIGN.md:299.
- sdkCandidate: true

### RT-006
- severity: medium
- file: tests/test_changelog_gh143_gh144_wire_changes.py
- description: The LRN-145 CHANGELOG guard is vacuous. Line 35 computes `unreleased = text[text.find("## [Unreleased]") : text.find("## [0.6.0]")]`, a slice that today contains an empty `## [Unreleased]` heading plus the entire `## [0.7.0]` release block. Every assertion phrased "CHANGELOG.md [Unreleased] must have a GH-144 entry" (lines 36, 116) therefore passes on entries that live inside an already-dated release section — precisely the state LRN-145 exists to forbid. test_changelog_has_unreleased_section (line 26) only checks the heading exists and precedes [0.6.0], which is trivially true. Once [0.8.0] is cut the slice widens further and the guard keeps passing forever.
- fix: Bound the slice at the next `## [` heading after `## [Unreleased]` (e.g. regex-split on `^## \[` and take the Unreleased block only), then decide deliberately whether these entries belong under Unreleased or under a genuinely cut [0.7.0] — and if the latter, rename the tests so they no longer claim to enforce LRN-145.
- sdkCandidate: true

### RT-007
- severity: medium
- file: agent_sdk/app.py
- description: Adding 429 -> -32000 to _A2A_CODE (agent_sdk/app.py:685-687) silently changes the pre-existing identity rate limiter's wire code on every /v1/* route. agent_sdk/auth/middleware.py:81-84's _rate_limited() raises HTTPException(429, "rate limit exceeded", headers={"Retry-After": "60"}); before this wave that 429 fell through to the -32603 default, and now emits -32000. Any existing A2A client branching on -32603 to detect throttling silently stops matching. This is a consumer-visible wire change on a route that predates the wave, and it is mentioned only as a trailing parenthetical inside the 🟠 Security RT-002 entry — no 🔴 Breaking changes heading, no Migration callout, and no test pins the new mapping (tests/test_rt002_a2a_stream_admission_cap.py::_assert_429_envelope asserts only that the key "error" is present in the body, never the code).
- fix: Give the mapping change its own 🔴 Breaking changes CHANGELOG entry stating both directions (emit: /v1/* 429 now carries -32000, was -32603; consume: clients matching -32603 for throttling must add -32000), and add an assertion to _assert_429_envelope that body['error']['code'] == -32000 plus a dedicated test driving the identity rate limiter to 429 on a /v1/* route and asserting the same code.
- codify: Extending a status->error-code map changes the wire output of every pre-existing path that already returned that status — enumerate those paths and give the change its own breaking-change entry and a test, never just the new path that motivated it.
- sdkCandidate: true

### RT-008
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: The stream-admission mechanism is now copy-pasted three times and is registered in no component registry. agent_sdk/routes/mcp.py:246-317 defines _StreamRecord/_get_streams/_prune_get_streams; the admit block (prune, global cap, _identity_key + O(n) owner scan, uuid + current_task registration, async release) is duplicated verbatim between mcp_get (mcp.py:865-913) and mcp_sse (mcp.py:999-1041); and agent_sdk/routes/a2a.py:86-108 plus :345-385 is a near-verbatim fourth copy whose own docstring says "Mirrors routes/mcp.py's _get_streams() accessor pattern exactly." The copies have already diverged: mcp_get's 429s carry MCP-Protocol-Version and mcp_sse's do not, and the a2a copy diverged structurally by dropping the identity dimension entirely. workspace/components/README.md registers nothing for this capability (highest entry is C-023) — Dimension 8: an unregistered reusable utility that has already produced three implementations inside a single wave.
- fix: Extract one helper into agent_sdk/common/ — e.g. admit_stream(app, state_attr, owner_key, *, global_cap, per_owner_cap, extra_headers) -> tuple[str, Callable[[], Awaitable[None]]] | JSONResponse — covering prune, both cap checks, slot-id generation, owning-task capture and registration, and call it from mcp_get, mcp_sse and _open_stream with route-appropriate headers and owner keys. Register it in workspace/components/README.md as a new C-NNN so the next indefinite-stream route reuses it.
- codify: Routes enforcing one shared budget must share one admission helper — a copy-pasted limiter drifts on the details (here: a missing version header on one copy, a missing identity dimension on another) before the first review.
- sdkCandidate: true

### RT-009
- severity: medium
- file: agent_sdk/common/admission.py
- description: resolve_per_identity_limit (admission.py:154-172) returns min(override, ceiling) where the ceiling is _MAX_GET_STREAMS = 500 (mcp.py:170) or _MAX_A2A_STREAMS = 500 (a2a.py:106) — neither has an AGENT_SDK_* setting. _MAX_A2A_STREAMS_PER_TASK = 16 (a2a.py:108) and InMemoryTaskStore(capacity=1000) (app.py:528-532 wires only task_ttl/interrupt_ttl/max_interrupted) are likewise hard-coded. DESIGN.md:353 justifies the low-hundreds per-identity default by saying it 'is operator-raisable without a code change', which is true only up to 500 — exactly the case an org-wide OAuth client (which collapses a whole org onto one identity_key per admission.py:96-107) is most likely to exceed. An operator there has no knob and no recovery. The per-task cap is in the same position: unlike both per-identity caps added in the same wave (AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY and AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY, agent_sdk/config.py:156,169), it has no AGENT_SDK_* override, so a deployment where more than 16 viewers legitimately subscribe to one task (a shared dashboard, a multi-tab console) has no supported path but monkeypatching a private module attribute.
- fix: Promote _MAX_GET_STREAMS and _MAX_A2A_STREAMS to BaseAgentSettings fields (AGENT_SDK_MAX_MCP_STREAMS / AGENT_SDK_MAX_A2A_STREAMS, ge=1, defaults 500) read at admission time so resolve_per_identity_limit's clamp ceiling moves with them, and wire InMemoryTaskStore(capacity=...) to a setting. Also expose _MAX_A2A_STREAMS_PER_TASK as `max_a2a_streams_per_task: int | None = Field(default=None, ge=1, alias='AGENT_SDK_MAX_A2A_STREAMS_PER_TASK')` on BaseAgentSettings, resolved via the existing resolve_per_identity_limit helper (admission.py:144), keeping 16 as the default.
- sdkCandidate: true

### RT-010
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: `assert owning_task is not None` is used as request-path control flow at a2a.py:492 and mcp.py:909 and :1031. StreamSlot.owning_task is typed non-optional (admission.py:87) and prune_finished calls slot.owning_task.done() unguarded (admission.py:136). Under python -O / PYTHONOPTIMIZE the asserts are stripped, a None owner is stored, and the next admission raises AttributeError BEFORE streams.pop(sid, None) (admission.py:138) — so the poisoned record is never cleared and every subsequent GET /mcp, GET /mcp/sse, POST /v1/message:stream, POST /v1/tasks/{id}:subscribe and POST /ag-ui/run returns 500 for the remaining process lifetime, with no self-heal, on routes the mcp.py module docstring calls connection-critical. The same wave handles the identical asyncio.current_task() case defensively one layer down (tasks/store.py:151-154), so the two halves disagree on hardening. Flagged four times across earlier deferred rounds.
- fix: Type StreamSlot.owning_task as `asyncio.Task[Any] | None`, have prune_finished skip records whose owning_task is None, and replace the three asserts with a plain assignment — a slot that cannot be liveness-keyed is simply never auto-reaped, matching tasks/store.py's treatment, instead of poisoning the reaper for both budgets.
- codify: A bare assert must never establish a type invariant on a live request path: python -O strips it, and here the resulting AttributeError escapes before the cleanup pop, permanently 500-ing every stream route.
- sdkCandidate: true

### RT-011
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: None of the seven cap-rejection branches logs anything, emits a counter, or records a metric: agent_sdk/routes/mcp.py:885, 896, 1016, 1024 and agent_sdk/routes/a2a.py:466, 473, 480 all return/raise with no `logger` call, while mcp.py logs every other rejection class (`logger.warning` at :575, :589, :597, :609, :676). DESIGN.md:353 and docs/protocols.md:105-110 both record that a 429 on the MCP path surfaces in Claude.ai as an opaque 'Couldn't connect', and harness/reference/mcp-claude-platforms.md's P8 checklist makes 'is something returning 403/429 on the MCP path?' the first debug question — so the SDK is now the thing emitting that signal with zero server-side evidence, indistinguishable from an auth, CORS or network fault. The wave's own SI-2 regression test (tests/test_gh143_mcp_get_stream_cap.py:395) inspects `caplog` for `agent_sdk.routes.mcp` while handling the rejection, which only makes sense if a log line was expected to exist. Flagged repeatedly across earlier rounds (recorded in workspace/todos/deferred/w040-group-G-medium-low.md as RT-005/RT-016) and still absent.
- fix: Add `logger.warning("mcp get stream cap reached scope=%s open=%d", "global"|"identity", len(streams))` to both mcp branches and the equivalent to a2a's three, emitting only a static scope label and the count — never `_identity_key(identity)`, the Authorization header or Mcp-Session-Id (SI-2). Assert the log line's presence and its absence of identity-derived values in the existing SI-2 tests.
- codify: A load-shed branch on a connection-critical protocol route must log its scope and current depth — a rejection with no server-side signal is indistinguishable from an auth or network fault to the operator debugging it.
- sdkCandidate: true

### RT-012
- severity: low
- file: agent_sdk/common/admission.py
- description: SlotTable is declared and constructed as an OrderedDict (admission.py:93, :110, :114) but no ordering semantics are ever used — `grep -n "move_to_end\|popitem"` across admission.py, routes/mcp.py and routes/a2a.py hits only _sessions() at mcp.py:250 and :271, which genuinely needs LRU. The type is vestigial from the evict-oldest design mcp.py:151-160 explicitly rejects and invites a contributor to reintroduce the eviction that comment forbids. Separately, count_for_owner and count_for_task (admission.py:141-151) are O(n) scans over up to 500 entries on every admission of every stream route.
- fix: Change the structure and its annotations to a plain dict[str, StreamSlot] in slot_table/prune_finished/count_for_owner/count_for_task so the reject-not-evict intent is expressed in the type, and keep per-owner and per-task counts in Counter/defaultdict(int) maps updated at register and release for O(1) admission.
- sdkCandidate: true

### RT-013
- severity: medium
- file: agent_sdk/common/cors.py
- description: `_EXPOSE_HEADERS = b"WWW-Authenticate, Mcp-Session-Id, X-A2A-Extensions"` (agent_sdk/common/cors.py:28) does not include `Retry-After`, which every new cap rejection sets (agent_sdk/routes/mcp.py:885,896,1016,1024; agent_sdk/routes/a2a.py:466,473,480). It also omits `MCP-Protocol-Version`, which mcp_get's two 429s set — that header appears only in `_ALLOW_HEADERS` (line 26, a request-direction list). A cross-origin browser MCP or AG-UI client therefore cannot read either header on the 429: the backoff hint is invisible and the client hot-retries, defeating the exact backpressure the cap exists to provide. Browsers are a first-class target here — the whole module exists because Claude.ai web calls these endpoints cross-origin (cors.py:1-9), and DESIGN.md:353 explicitly frames the 429 around Claude.ai. This is the LRN-004 failure class (header emitted but never exposed) applied to two newly added headers, and it was already raised as a deferred finding in prior rounds without being fixed.
- fix: Add `Retry-After` and `MCP-Protocol-Version` to `_EXPOSE_HEADERS` in agent_sdk/common/cors.py:28, and extend the CORS expose-headers test to assert both are present on a 429 from GET /mcp so a future header addition cannot repeat this.
- codify: Any header a route newly emits must be added to the CORS expose-headers list in the same change — an unexposed header is invisible to every browser client and silently disables whatever behaviour it was meant to drive.
- sdkCandidate: true

### RT-014
- severity: low
- file: agent_sdk/common/admission.py
- description: The module docstring (agent_sdk/common/admission.py:17-19) states the routes keep 'their own rejection shape (MCP answers `JSONResponse` carrying `MCP-Protocol-Version`, A2A raises `HTTPException` ...)'. That is true only for `mcp_get` (agent_sdk/routes/mcp.py:885-903). `mcp_sse`'s two rejections (mcp.py:1016 and 1024) carry only `Retry-After` and no `MCP-Protocol-Version`, so the shared module's own account of the divergence it preserved is inaccurate for half the MCP surface — and nothing pins the asymmetry either way. tests/test_rt001_mcp_sse_stream_cap.py:44-51 already asserts only Retry-After on the SSE side, so the divergence is pinned in place by the test suite rather than caught by it — the exact drift the duplicated admission block (RT-008 above) makes inevitable.
- fix: Either add `_PROTOCOL_VERSION_HEADER` to mcp_sse's two 429 header dicts (harmless — the legacy transport predates the header, but consistency costs nothing), or amend the docstring to state that only Streamable HTTP's GET carries it and add an assertion of its deliberate absence in tests/test_rt001_mcp_sse_stream_cap.py.
- sdkCandidate: true

### RT-015
- severity: medium
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: test_prune_never_evicts_a_still_open_stream_regardless_of_elapsed_time patches mcp_module.time.monotonic at lines 366-367, but agent_sdk/routes/mcp.py never calls time.monotonic — it uses time.time() exclusively (:246, :265, :270, :836). The test's stated invariant ('a still-open slot must never be reclaimed by wall-clock pruning') is therefore unguarded: reintroducing a time.time()-based TTL reaper leaves it green. Worse, mcp_module.time IS the stdlib time module and asyncio.base_events.BaseEventLoop.time() returns time.monotonic() resolved through that module attribute (verified via inspect.getsource), so the patch advances the event-loop clock by +10,000s for the remainder of the test, instantly firing t1's in-flight asyncio.sleep(_HEARTBEAT_SECONDS) and every anyio/httpx timer — a latent flake in a test whose whole subject is timing. Deferred across multiple prior rounds and unfixed.
- fix: Remove the global time.monotonic patch. Assert the invariant structurally instead: seed _get_streams() with a sentinel asyncio.Task that is not done(), call prune_finished and assert the entry survives, then let the task complete and assert it is reclaimed. If a wall-clock guard is genuinely wanted, patch mcp_module.time.time — the clock the module actually reads — rather than the stdlib clock asyncio depends on.
- codify: A test that patches a clock the module under test never reads asserts nothing; assert against the exact time source the code calls, or assert structurally that no time source is referenced.
- sdkCandidate: true

### RT-016
- severity: medium
- file: tests/test_http_protocol.py
- description: No test anywhere asserts that GET /mcp returns 200 with content-type: text/event-stream. The only happy-path test, test_mcp_get_no_protocol_version_header_still_succeeds (tests/test_http_protocol.py:295-305), asserts only pytest.raises(asyncio.TimeoutError) — 'the request did not complete' — and never inspects status_code or headers; the _still_streaming() helper used throughout tests/test_gh143_mcp_get_stream_cap.py:52-63 has the same blind spot. The route just gained two new non-SSE exit branches (429 global, 429 per-identity) on top of the pre-existing 400 and 403, and mcp.py:9 declares the 200/text-event-stream invariant connection-critical ('Returning 405 here breaks Claude.ai Desktop — never'). A regression turning the admitted path into a non-200 or non-SSE response passes the entire test suite. LRN-001 (severity high) requires TestClient-level header assertions for any wave touching a protocol route.
- fix: Add a happy-path test driving GET /mcp through a raw ASGI scope with a send-capture (the pattern already used at tests/test_gh143_mcp_get_stream_cap.py:252-278), asserting http.response.start carries status 200 and a content-type: text/event-stream header plus the first padding-comment body chunk; add the equivalent for GET /mcp/sse asserting the 'event: endpoint' first frame.
- sdkCandidate: true

### RT-017
- severity: low
- file: tests/test_rt003_task_store_reap_conformance.py
- description: The wave made reap_dead_subscriptions a mandatory obligation on the abstract TaskStore.subscribe contract (agent_sdk/tasks/store.py:129-140), but the conformance suite gates it with a hand-maintained list — _STORE_FACTORIES: list[Callable[[], TaskStore]] = [InMemoryTaskStore] at line 40 — rather than enumerating TaskStore.__subclasses__(). The list is complete today (InMemoryTaskStore is the only in-tree implementation), but a future in-tree store silently escapes the gate and reintroduces the unbounded record.subscriptions growth this wave closed. LRN-140's Prevention clause: scope base-class-contract fixes to 'all subclasses via an enumerating meta-test', not the named instance(s).
- fix: Parametrize the conformance tests over TaskStore.__subclasses__() (importing agent_sdk.tasks.memory to ensure registration) instead of the literal _STORE_FACTORIES list, so any new in-tree TaskStore must satisfy the reap contract to go green.
- sdkCandidate: true

### RT-018
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: GH-144's stated root cause was two independent terminal predicates on one logical condition. The landed fix keeps both and duplicates the literal: `record.task.status.state in TERMINAL_STATES` plus 'task is in a terminal state and cannot accept new messages' now appears at a2a.py:352-356 (_resume_or_error, message/send) and again at a2a.py:632-638 (message_stream's new branch), so the structural cause survives and can diverge again on the next edit. No parity test exists (grep for 'parity' across tests/test_w017_gh51_multiturn.py and tests/test_gh144_terminal_resume_error_docs.py returns nothing): test_send_terminal_taskid_returns_unsupported (:128) and test_stream_terminal_taskid_returns_unsupported (:139) each assert the constant independently, so a one-sided change to either the code or the message stays green.
- fix: Hoist the message to a module-level _TERMINAL_TASK_MESSAGE constant and the predicate to one helper (e.g. `_terminal_reject(record) -> JSONResponse | None`) called by both paths, then add a parity test driving the identical terminal task through /v1/message:send and /v1/message:stream asserting the same status_code, error.code and error.message.
- codify: Reconciling two diverged error paths by duplicating the predicate leaves the divergence possible — extract one shared check and lock it with a cross-method parity test asserting identical status, code, and message.
- sdkCandidate: true

### RT-019
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: _open_stream's signature at a2a.py:273-275 is `-> tuple[AsyncIterator[bytes], Any]`, so the abort callable is untyped. The whole point of the round-4 fix making abort `async def` (a2a.py:324-334) is that every caller must `await` it, but with `Any` a bare `abort()` type-checks clean and silently returns an un-awaited coroutine — reintroducing exactly the subscription leak just fixed. mcp.py:217 got this right with _StreamRecord = tuple[str, asyncio.Task[Any], Callable[[], Awaitable[None]]].
- fix: Annotate as `tuple[AsyncIterator[bytes], Callable[[], Awaitable[None]]]` so mypy rejects a caller that forgets to await abort().
- sdkCandidate: true

### RT-020
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: message_stream creates and stores the TaskRecord before the admission check, so rejected requests still consume task-store LRU capacity. At agent_sdk/routes/a2a.py:451-453 the else-branch calls _create_task_record(...) — which calls store.create() and therefore _evict_over_capacity() (agent_sdk/tasks/memory.py:39-47, :241-248) — before `await _open_stream(...)` can raise HTTPException(429). Verified live: the victim request in the reproduction received its 429 only after its TaskRecord had already been created and stored. At capacity a caller can therefore keep flushing the 1000-entry LRU while every one of its own requests is being rejected, evicting other tenants' live tasks — and eviction cancels the paused worker coroutine and sentinel-closes subscriber queues (DESIGN.md:299). _open_stream's docstring claims admission happens "BEFORE store.subscribe()", which is true but misleadingly narrow: it is not before store.create().
- fix: Hoist the global (and per-identity) admission check above _create_task_record in message_stream — e.g. an _admission_check(request, identity) call before line 452, with the per-task check staying inside _open_stream where the record exists — so a rejected request mutates no store state. Add a test asserting that a 429'd message:stream leaves task-store size unchanged.
- sdkCandidate: true

### RT-021
- severity: low
- file: agent_sdk/routes/a2a.py
- description: `_admit` stores the slot's task id as `task_id or ""` (a2a.py:510) while the per-task gate is `if task_id is not None:` (a2a.py:433). The empty string is therefore an in-band sentinel inside the same domain as real task ids. Any future caller that passes `""` instead of `None` makes `task_count = sum(1 for rec if rec[0] == "")` match every reserved/unbound slot — including every `/ag-ui/run` slot — turning the 16-subscribers-per-task cap into a global 16-stream cliff for all callers.
- fix: Store the task id as `str | None` in `_A2AStreamRecord` and compare against `None` in both `_admit`'s per-task scan and `_StreamSlot.bind`, removing the `""` sentinel entirely.
- sdkCandidate: true

### RT-022
- severity: low
- file: agent_sdk/routes/a2a.py
- description: `_open_stream` became `async` and now performs `await _admit(request, identity, record.task.id)` (a2a.py:545) between `message_stream`'s identity-scoped `store.get()` and `store.subscribe()` (a2a.py:548). `InMemoryTaskStore.subscribe` does a bare `record = self._records[task_id]` (memory.py:70), which raises `KeyError` -> HTTP 500 if the record disappeared. This is safe today only by accident: `_admit`'s awaits (`_prune_a2a_streams` -> `release()`) contain no real suspension points, so control never returns to the event loop. Any future `release` that awaits actual work — e.g. a durable `TaskStore` whose teardown is async — silently converts an evicted or TTL-expired record into an unhandled 500 on a documented public extension point (C-005).
- fix: Make `InMemoryTaskStore.subscribe` use `self._records.get(task_id)` and raise a typed error the route maps to `-32001`, or re-verify the record inside `_open_stream` after `_admit` returns instead of relying on the awaits never suspending.
- sdkCandidate: true

### RT-023
- severity: low
- file: agent_sdk/routes/a2a.py
- description: tasks_resubscribe (agent_sdk/routes/a2a.py:709) and message_stream (a2a.py:580) both call _echo_extensions(request, response) before admission, writing X-A2A-Extensions onto the `response` object. When _admit raises HTTPException(429) (a2a.py:434/441/448), app.py:697's _a2a_auth_envelope constructs a fresh JSONResponse from exc.headers only, so the activated-extension echo required by DESIGN.md §5.1 is dropped on the 429 — an A2UI or credential-forwarding client that activated an extension gets no echo on the rejection and cannot confirm activation state before retrying.
- fix: Merge the echoed X-A2A-Extensions value into the HTTPException's headers dict in _admit (or have _a2a_auth_envelope carry forward request-scoped echo headers), so the 429 preserves the same extension echo the 200 path emits.
- sdkCandidate: true

### RT-024
- severity: medium
- file: DESIGN.md
- description: DESIGN.md §5.5 claims the A2A budget includes 'a per-task subscriber cap that bounds `record.subscriptions`, the list `store.publish` walks per frame'. Both paths that actually create subscriptions in bulk bypass it: `message_stream`'s no-taskId path calls `_admit(request, identity, None)` (agent_sdk/routes/a2a.py:598) and `/ag-ui/run` always calls `_admit_stream(request, identity, None)` (agent_sdk/routes/ag_ui.py:466) — including its resume branch, which subscribes to an already-existing task at ag_ui.py:516 and never binds the slot. One task's `record.subscriptions` is therefore bounded only by the 500 global / 200 per-identity budgets, not by `_MAX_A2A_STREAMS_PER_TASK = 16`, so the specific harm the per-task cap was introduced to close is bounded ~31x looser than documented.
- fix: Call `slot.bind(record.task.id, sub)` on AG-UI's resume path once the interrupt record resolves so the per-task cap can see it, or restate DESIGN.md §5.5 and docs/protocols.md to scope the per-task cap to `tasks:subscribe` and `message:stream`'s resume branch only.
- sdkCandidate: true

### RT-025
- severity: medium
- file: agent_sdk/routes/ag_ui.py
- description: POST /ag-ui/run is a third authenticated long-lived SSE surface on the same single-process connection pool and is admitted against neither budget. agent_sdk/routes/ag_ui.py:458-536 returns a StreamingResponse that calls store.subscribe() at :489 and :507 — the same TaskStore.subscribe the wave just modified — and holds the connection with 15s heartbeats until the task terminates, bounded only by AGENT_SDK_TASK_DEADLINE (default 600s), not by _get_streams() or _a2a_streams(). The wave's own bypass argument, stated twice (agent_sdk/routes/mcp.py:132-134 and agent_sdk/routes/a2a.py:70-71: a cap on only one transport is trivially bypassed by calling the other), applies verbatim here, so the process-wide bound the wave set out to establish still does not exist. Unlike the MCP and A2A cases the stream is not literally indefinite, which is why this is medium rather than high, but 600s of held connection at the 100/min identity rate limit is ample to reach four figures of concurrent streams.
- fix: Route /ag-ui/run through the shared admission helper proposed in RT-008 (global + per-identity), enforced after Depends(require_identity) and the Origin/Content-Type guards and before the StreamingResponse is constructed, and add an AG-UI case to the shared-budget test so a future fourth stream route is caught by an existing test rather than a review.
- sdkCandidate: true

### RT-026
- severity: low
- file: agent_sdk/routes/ag_ui.py
- description: `from .a2a import _admit as _admit_stream` at agent_sdk/routes/ag_ui.py:52 imports a private symbol from a sibling route module, and the import is placed mid-block between the `..tasks.store` and `..agent.events` imports rather than with the other relative imports. The whole point of the round-5 extraction was to hoist shared admission bookkeeping into agent_sdk/common/admission.py (C-024), but the admission ENTRY POINT (_admit) and its return type (_ClaimedSlot) stayed behind in routes/a2a.py, so routes/ag_ui.py now depends on another route module's private API and any future stream route will too. AG-UI therefore also silently inherits A2A's cap constants and its HTTPException-shaped rejection, which docs/protocols.md then had to special-case ('on /ag-ui/run it is the bare {"detail": ...} shape').
- fix: Move _admit and _ClaimedSlot into agent_sdk/common/admission.py alongside StreamSlot/prune_finished (parameterising the cap constants the two callers differ on), import them from there in both routes/a2a.py and routes/ag_ui.py, and move the import into the sorted relative-import block.
- sdkCandidate: true

### RT-027
- severity: low
- file: agent_sdk/routes/ag_ui.py
- description: `_prune_a2a_streams` does not exist anywhere in the codebase (the helper is `agent_sdk/common/admission.py::prune_finished`, aliased in mcp.py as `_prune_get_streams`). It is referenced as a live symbol in two places: agent_sdk/routes/ag_ui.py:636's comment ('`_prune_a2a_streams` is the liveness backstop') and, more consequentially, in `_ADMISSION_MARKERS` at tests/test_rt001_admission_before_mutation.py:238 — the marker set the `test_every_sse_route_is_admission_capped` completeness gate matches handler source against. A dead marker in that set is a latent false-pass vector for the one gate that exists to stop a future SSE route from bypassing the budget.
- fix: Fix the ag_ui.py:636 comment to name `prune_finished` (or `_admit`'s slot lifecycle), and replace `_prune_a2a_streams` in `_ADMISSION_MARKERS` with `prune_finished`. Add a guard asserting every marker in the set resolves to a real symbol in agent_sdk.routes.* or agent_sdk.common.admission, so the gate cannot silently accumulate dead markers.
- sdkCandidate: true

### RT-028
- severity: medium
- file: agent_sdk/tasks/store.py
- description: Subscription.owner_task (store.py:51) is populated only inside InMemoryTaskStore.subscribe (memory.py:83-86); Subscription.__init__ leaves it None, and reap_dead_subscriptions (store.py:113-118) skips `owner_task is None`. A third-party TaskStore subclass that obeys the new MUST-call contract documented on the abstract subscribe() (store.py:129-141) therefore reaps nothing — the contract is unenforceable and silently vacuous for exactly the population the repo already guards for elsewhere (interrupt_ttl_remaining's default impl).
- fix: Move the `asyncio.current_task()` capture (with the RuntimeError guard) from InMemoryTaskStore.subscribe into Subscription.__init__, which the base class owns, so every store implementation gets a populated owner_task for free and reap_dead_subscriptions actually works for subclasses.
- sdkCandidate: true

### RT-029
- severity: low
- file: agent_sdk/tasks/store.py
- description: reap_dead_subscriptions (store.py:113-118) drops orphaned Subscription objects out of record.subscriptions without calling sub.close(), so a reaped subscription's queue never receives the _CLOSE sentinel. Every other removal path in the class closes first — close_streams at memory.py:118-120 and evict at memory.py:217-219. The reap is now called from two places (memory.py's `subscribe` and `_evict_over_capacity`), which makes the inconsistent removal contract twice as reachable, and the orphaned subscription's `asyncio.Queue(maxsize=256)` never receives the `_CLOSE` sentinel as a result. Currently harmless (a reaped orphan's owning task is by definition done, so it has no live reader) but it makes the removal contract inconsistent across a newly-public base-class method and would silently strand any future caller holding a Subscription across tasks. Deferred across multiple prior rounds and unfixed.
- fix: Call s.close() on each subscription filtered out by the reap in TaskStore.reap_dead_subscriptions before rebinding record.subscriptions, matching close_streams() and evict().
- sdkCandidate: true

### RT-030
- severity: low
- file: agent_sdk/tasks/memory.py
- description: `InMemoryTaskStore.touch()` (and the LRU `move_to_end` it performs) has zero call sites: `grep -rn "\.touch(" ` over the entire repository including tests and template returns nothing. It is dead code, and it is also the exact hook whose absence enables uncontrolled LRU eviction under load — nothing keeps an actively-streamed task at the MRU end of `_evict_over_capacity`'s ordering, since `publish()` bumps `updated_at` but never reorders.
- fix: Either call `touch(task_id)` from `publish()`/`subscribe()` so streaming tasks stay MRU, or delete `touch` and its `TaskStore` declaration so the API surface stops advertising a hook nothing uses.
- sdkCandidate: true

### RT-031
- severity: medium
- file: agent_sdk/config.py
- description: max_mcp_streams_per_identity (config.py:147-150) and max_a2a_streams_per_identity (config.py:157-160) are typed int | None with no ge= constraint and no boot-time validation, and the resolvers clamp only the upper bound (min(limit, _MAX_*_STREAMS) at mcp.py:198 and a2a.py:123). Setting AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY=0 (or negative) therefore makes _max_streams_per_identity() return 0, so 'owner_count >= 0' at mcp.py:881 and :1009 is always true and EVERY GET /mcp and GET /mcp/sse returns 429 for the process lifetime — a total MCP connector outage from a single typo, with no boot-time error. AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY=0 does the same to POST /v1/message:stream and POST /v1/tasks/{id}:subscribe. Both fields are documented in-code as 'raise this for a larger org', so a mistyped value is a plausible operator action.
- fix: Add ge=1 to both Field(...) declarations in agent_sdk/config.py and a settings test asserting that 0 and -1 are rejected at construction, so a misconfiguration fails loudly at boot rather than silently disabling the protocol surface.
- sdkCandidate: true

### RT-032
- severity: medium
- file: workspace/todos/plan.md
- description: workspace/todos/plan.md carries no row for w040 at all — its wave table ends at 'W39 [x] ✅ 2026-08-16'. Meanwhile workspace/todos/active/w040-gh-issues.md:16,28 still shows both items unchecked `- [ ]` while the full implementation, CHANGELOG entries and new test modules are landed in the working tree, and workspace/todos/deferred/w040-group-G-budget-exhausted.md records status: budget-exhausted after 5 rounds. This is the LRN-067 split-brain shape (plan/todo/code disagree on status) plus the LRN-062/LRN-109 condition (wave archive silently skips plan.md when no pre-seeded row exists), so the archive step will drop w040 from the ledger with no error. LRN-100 additionally requires the budget-exhausted deferred marker to be relocated once its findings are resolved.
- fix: Append a pre-seeded w040 row to workspace/todos/plan.md's wave table before archive, reconcile the checkbox state in workspace/todos/active/w040-gh-issues.md with the landed code, and relocate workspace/todos/deferred/w040-group-G-budget-exhausted.md per LRN-100 once its findings there are resolved rather than leaving both the active todo and the deferred marker live simultaneously.
- sdkCandidate: true

### RT-033
- severity: medium
- file: workspace/todos/archive/w040-gh-issues.md
- description: The archived wave todo declares scope as `agent_sdk/routes/a2a.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py` plus docs. The landed working tree also modifies `agent_sdk/routes/ag_ui.py` (+144 lines, a whole new admission integration), `agent_sdk/app.py` (the 429 -> -32000 envelope mapping, which changes the error code the pre-existing identity rate limiter returns on /v1/* from -32603 to -32000), `agent_sdk/config.py` (two new settings), `pyproject.toml`, `REVIEWS.md`, `workspace/components/README.md`, `.claude/skills/acceptance/SKILL.md`, and adds the new module `agent_sdk/common/admission.py` plus 16 new test files — none of which appear on any `Creates:`/`Modifies:` line. LRN-053 (scope is the union of Creates AND Modifies), LRN-160 (paths named only in prose must be promoted onto those lines) and LRN-168 all apply. This undeclared scope is the direct mechanism by which the new settings field and the new module fell outside the wave's declared review surface and therefore outside its SemVer accounting. Separately, the entire wave was uncommitted at archive time — eleven of the new test files were untracked `??` in git and named only in prose, never on a `Creates:` line — yet both todo checkboxes were already `[x]` and the file had been moved to `workspace/todos/archive/`; LRN-121's Check clause requires the opposite ordering (commit, then archive).
- fix: Extend both todo entries' `Creates:`/`Modifies:` lines to name every tracked file the diff touches — `agent_sdk/routes/ag_ui.py`, `agent_sdk/app.py`, `agent_sdk/config.py`, `agent_sdk/common/admission.py` (new), `pyproject.toml`, `REVIEWS.md`, `workspace/components/README.md`, `.claude/skills/acceptance/SKILL.md` and the 16 new `tests/` files. `git add` the untracked test files and commit before archiving, then re-run LRN-121's pre-archive gate over the widened scope. Also add a CHANGELOG line for the /v1/* rate-limiter 429 error-code change (-32603 -> -32000), which is consumer-visible on a pre-existing path.
- sdkCandidate: false

### RT-034
- severity: low
- file: template/.claude/skills/acceptance/SKILL.md
- description: The peer-repo runtime copy that `/acceptance` actually executes for downstream agents was ONE-LINE synced for GH-144 (line 200 now correctly reads '501 / -32004') but not whole-file synced: it still carries the superseded pre-GH-89 paragraph 'The admin key is read from ADR-000 but never printed to the terminal', where harness/ and .claude/ both carry the chmod-600 keyFile externalisation prose. A prior deferred fix explicitly required re-syncing the whole file, not the changed line. Nothing detects this: tests/test_rt004_r5_acceptance_skill_mirror_parity.py pins only `.claude/` vs `harness/`, and tests/test_workflow_sync.py's byte-identity check (from which 'acceptance' was just un-exempted) likewise covers only the two in-repo copies — the peer repo at template/ is a separate git checkout and is invisible to both.
- fix: Re-sync the non-path-specific prose from harness/skills/acceptance/SKILL.md into template/.claude/skills/acceptance/SKILL.md (keeping the two genuinely divergent lines: the `scriptPath` target and the Path note) and commit+push to wailuen/a2a-agent-template per LRN-071. Add a parity check for the peer-repo copy that skips gracefully when template/ is not checked out, so the drift is at least visible.
- sdkCandidate: true

### RT-035
- severity: low
- file: workspace/components/README.md
- description: C-024 was added to the registry table (line 28) but has no entry in the file's `## Descriptions` section — the last description block is C-019 (line 88). The Descriptions section is where every landed component records its call sites, its parity contract and the 'do not re-derive this' rule; without one, the next stream route has the table row but none of the guidance that C-024 exists to carry (in particular: that `release` MUST be `async def`, that `subscribe` is the only legal way to attach a Subscription to a slot, and that the two budgets are deliberately separate tables).
- fix: Add a `**C-024 stream admission bookkeeping** (agent_sdk/common/admission.py)` description block summarising the StreamSlot contract, the three release layers, the two-table split, both routes' call sites, and the rule that any future indefinite-SSE route must admit through it rather than re-deriving a limiter.
- sdkCandidate: false

### RT-036
- severity: low
- file: uv.lock
- description: `uv.lock` is dirty in the working tree with a single change — `agent-sdk version = "0.5.44"` -> `"0.6.0"` — that has nothing to do with either GH-143 or GH-144. It is a leftover from the `ced6262 chore: release v0.6.0` commit, which bumped pyproject.toml:7 to 0.6.0 without regenerating the lockfile. It nevertheless lands inside w040's diff, on no todo's Creates:/Modifies: line and in no CHANGELOG file list, so it counts as undeclared wave scope under LRN-168.
- fix: Either commit the lockfile sync separately as release hygiene against the v0.6.0 tag, or declare it explicitly in the w040 todo; and add `uv lock` to the /sdk-release checklist so a version bump can never leave uv.lock drifting into the next wave's diff.
- sdkCandidate: true

## Instruction

Non-blocking — these did not block w040's archive. Address opportunistically or fold into a future wave.
