wave: w040
group: G
date: 2026-08-19
round_count: 5
status: budget-exhausted

## Findings

### RT-001
- severity: high
- file: CHANGELOG.md
- description: The GH-144 entry ships a stable-core wire break (message/stream terminal-task 404/-32001 -> 501/-32004, agent_sdk/routes/a2a.py:341-350) under a patch bump by asserting it "satisfies both conditions of DESIGN.md §4.0's wire-shape conformance exemption" and is "spec-conformance-driven". Neither claim is evidenced. This repo's own signed-off Round 10 audit (REVIEWS.md:453) classifies the exact same finding as "an internal cross-method inconsistency, not a hard-MUST breach (both codes are valid A2A error codes)", and harness/reference/a2a-protocol-0_3_0.md:132 requires only that a terminal re-message "MUST return an error" while its code->method table (:110) maps neither -32001 nor -32004 to message/send|stream. DESIGN.md:141 states the exemption applies only when the change's "sole purpose is bringing the SDK's wire output/parsing into conformance with an external protocol spec ... rather than a voluntary redesign", and that "a voluntary breaking change to the stable core ... still requires a major bump; this exemption cannot be cited for those." The exemption text is also scoped to "a wire shape in models/", while models/errors.py is unchanged here — only routes/a2a.py's code selection moved.
- fix: Either (a) cite a specific A2A v0.3.0 clause that mandates -32004 over -32001 for terminal re-message and add it to the code comment at agent_sdk/routes/a2a.py:345 and the CHANGELOG entry, or (b) reclassify as a voluntary stable-core break and bump major per DESIGN.md:141. Either way, reconcile REVIEWS.md:453's "not a hard-MUST breach" verdict with the CHANGELOG's conformance claim so the two records do not contradict each other.
- codify: A CHANGELOG entry may not cite DESIGN.md §4.0's conformance exemption when the repo's own audit record classifies the same change as an internal-consistency fix rather than a spec MUST — the exemption requires an actual spec clause citation, not an argument from semantics.
- sdkCandidate: true

### RT-002
- severity: high
- file: agent_sdk/tasks/store.py
- description: Subscription gains a new public attribute owner_task (agent_sdk/tasks/store.py:51) and InMemoryTaskStore.subscribe gains reaping behavior (agent_sdk/tasks/memory.py:70-90), but neither file is declared anywhere. The todo (workspace/todos/active/w040-gh-issues.md:17,29) scopes group G to routes/a2a.py and routes/mcp.py only, and neither CHANGELOG entry's file list names agent_sdk/tasks/store.py or agent_sdk/tasks/memory.py. Subscription and TaskStore are exported from agent_sdk/tasks/__init__.py::__all__ and TaskStore is registered component C-005, so this is a stable-core public API addition (DESIGN.md §4.0) shipping with no changelog record — and, because it fell outside the declared scope, outside the wave's adversarial-review and protocol-audit surface (the LRN-053 Creates-union-Modifies pattern, LRN-168).
- fix: Add agent_sdk/tasks/store.py and agent_sdk/tasks/memory.py to the group G todo's Modifies: field and to both CHANGELOG entries' trailing file lists, plus an '### Added' line for the new public Subscription.owner_task attribute, then re-run the unit redteam over the widened scope.
- codify: Every production file the diff touches must appear in the todo's Creates/Modifies scope and in the CHANGELOG entry's file list — a public attribute added to an exported stable-core class outside declared scope escapes both review and SemVer accounting.
- sdkCandidate: true

### RT-003
- severity: high
- file: agent_sdk/tasks/store.py
- description: The layer-3 orphan-subscription backstop that agent_sdk/routes/a2a.py::_open_stream now depends on lives only inside InMemoryTaskStore.subscribe (agent_sdk/tasks/memory.py:78-85). The abstract TaskStore.subscribe declaration (agent_sdk/tasks/store.py:111) is a bare `...` with no docstring and states no such obligation, yet TaskStore is an explicitly documented public extension point (docs/deployment.md:55 `Agent(task_store=...)`, DESIGN.md:295, DESIGN.md:567 "TaskStore interface for a shared backend later"). Any third-party or future shared-backend TaskStore silently reintroduces the exact unbounded record.subscriptions growth this change was written to close — store.publish walks that list for every frame — with no test or type error to signal it.
- fix: Either hoist the reap out of the implementation (a concrete helper on the TaskStore base, e.g. `_reap_dead_subscriptions(record)`, called by every subscribe implementation, or perform it in _open_stream itself so it is transport-owned), or state the requirement in TaskStore.subscribe's abstract docstring and add a store-conformance test that any TaskStore implementation must pass.
- codify: When a route's leak-safety depends on behavior inside one implementation of a public ABC, the obligation must be stated on the ABC (docstring + conformance test) or hoisted into shared code — an invariant that exists in only one subclass of a documented extension point is not an invariant.
- sdkCandidate: true

### RT-004
- severity: medium
- file: DESIGN.md
- description: GH-143 adds a new wire-visible response (429 + Retry-After) to two protocol routes, but the SDK's own spec surfaces were not updated. DESIGN.md:351 still reads "`GET /mcp` — server->client SSE channel: returns `text/event-stream` with heartbeats" with no mention of the cap or 429; DESIGN.md:355 describes the legacy SSE pair without noting it now shares the same budget; DESIGN.md:396's "Rate limiting — two layers" is now three layers. docs/protocols.md's MCP section (lines 73-81) documents no 429 at all. The GH-144 half of the same wave did update both DESIGN.md:277 and docs/protocols.md:19-24, so the omission is asymmetric within one wave.
- fix: Add the shared admission cap and the 429/Retry-After response to DESIGN.md §5.3's GET /mcp and legacy-SSE bullets and to §6's rate-limiting paragraph (now three layers), and add a corresponding line to docs/protocols.md's MCP section.
- sdkCandidate: true

### RT-005
- severity: medium
- file: tests/test_gh143_mcp_get_stream_cap.py
- description: The new 429 responses introduce three headers/body facts that no test asserts. tests/test_gh143_mcp_get_stream_cap.py:115,138,183,211,359 and tests/test_rt001_mcp_sse_stream_cap.py:99,132,169,214 assert only `status_code == 429`. Nothing asserts `Retry-After: 5` (agent_sdk/routes/mcp.py:843,854,965,973), nothing asserts mcp_get's rejections carry MCP-Protocol-Version (mcp.py:844,855), and nothing asserts the body carries no identity-derived value — the explicit SI-2 requirement in the todo at workspace/todos/active/w040-gh-issues.md:40, since _identity_key() returns an OAuth subject / API-key id. LRN-001 (severity high) requires TestClient-level header assertions for any wave touching a protocol route. A regression dropping Retry-After, dropping the version header, or interpolating _identity_key(identity) into the rejection message would pass green.
- fix: Extend both cap test modules to assert `r.headers['Retry-After'] == '5'`, assert `MCP-Protocol-Version` is present on mcp_get's 429 (and document its deliberate absence on mcp_sse's), and add an assertion that the 429 body text contains neither identity.subject nor the bearer token.
- sdkCandidate: true

### RT-006
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: _MAX_GET_STREAMS = 500 and _MAX_GET_STREAMS_PER_IDENTITY = 8 (agent_sdk/routes/mcp.py:133-134) are hard-coded module constants with no AGENT_SDK_* override, unlike every comparable operational bound (agent_sdk/config.py:102-109: AGENT_SDK_INTERRUPT_TTL, AGENT_SDK_MAX_INTERRUPTED, AGENT_SDK_TASK_TTL, AGENT_SDK_RATE_LIMIT, AGENT_SDK_UNAUTH_RATE_LIMIT). Because the per-identity budget of 8 is now shared between GET /mcp and GET /mcp/sse, a deployment following the documented P9.7 dual-transport workaround (harness/reference/mcp-claude-platforms.md:355-358) or hitting claude.ai web bug #291 ("GET polls ~5s", :271) can saturate one OAuth subject's 8 slots and then receive 429 instead of text/event-stream — the failure mode DESIGN.md:351 records as breaking the Claude.ai connector. An operator hitting this has no knob and no recovery other than waiting.
- fix: Expose both caps as settings (e.g. AGENT_SDK_MAX_MCP_STREAMS / AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY in agent_sdk/config.py) read at request time, and add a note to mcp_get's docstring tying the 429 path back to the LRN-053/Claude.ai-connector constraint so the tradeoff is visible at the call site.
- sdkCandidate: true

### RT-007
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: The admission block — _get_streams + _prune_get_streams + global cap + per-identity `sum(1 for rec in streams.values() if rec[0] == owner)` + two 429 JSONResponse bodies — is duplicated verbatim between mcp_get (agent_sdk/routes/mcp.py:833-856) and mcp_sse (agent_sdk/routes/mcp.py:959-976), including the two identical rejection message strings. The two copies have already diverged: mcp_get's 429s carry MCP-Protocol-Version, mcp_sse's do not. Dimension 8: a second implementation of a registered capability. Any future indefinite-stream route on this router will be a third copy.
- fix: Extract `_admit_stream(request, identity, *, extra_headers) -> tuple[str, Callable[[], None]] | JSONResponse` performing prune, both cap checks, slot-id generation, owning-task capture and slot registration, returning either the (stream_id, release) pair or the 429 response; call it from both routes and register it in workspace/components/README.md so the next stream route reuses it.
- sdkCandidate: true

### RT-008
- severity: low
- file: agent_sdk/routes/mcp.py
- description: `assert owning_task is not None` at agent_sdk/routes/mcp.py:864 and :978 establishes the _StreamRecord type invariant with a bare assert. Under `python -O` the assert is stripped, a None owner is stored in _get_streams(), and _prune_get_streams's `rec[1].done()` then raises AttributeError on every subsequent admission for BOTH routes; because the exception escapes before `streams.pop(sid, None)`, the poison record is never cleared, permanently 500-ing GET /mcp and GET /mcp/sse with no self-heal. agent_sdk/tasks/memory.py:86-89 handles the identical asyncio.current_task() case defensively (`owner_task is None` -> never reaped), so the two halves of the same fix disagree on hardening.
- fix: Replace the asserts with the memory.py treatment: allow a None owner in _StreamRecord (`asyncio.Task[Any] | None`) and have _prune_get_streams skip records whose task is None, so a slot that cannot be liveness-keyed is simply never auto-reaped instead of poisoning the reaper.
- sdkCandidate: true

### RT-009
- severity: low
- file: agent_sdk/tasks/memory.py
- description: The reap at agent_sdk/tasks/memory.py:80-85 drops orphaned Subscription objects out of record.subscriptions without calling sub.close(), so a reaped subscription's queue never receives the _CLOSE sentinel. Every other removal path in this file closes first (close_streams at :117-121, evict at :212-214). The asymmetry is currently harmless (a reaped orphan by definition has no live reader, since its owning task is done) but makes the removal contract inconsistent and would silently strand any future caller that holds a Subscription across tasks.
- fix: Call `s.close()` on each subscription filtered out by the reap before rebinding record.subscriptions, matching close_streams() and evict().
- sdkCandidate: true

### RT-010
- severity: low
- file: agent_sdk/routes/a2a.py
- description: The a2a layer-3 backstop only runs inside InMemoryTaskStore.subscribe for the record being subscribed to, so an orphan left by a hard-cancelled /v1/tasks/{id}:subscribe on a task that is never re-subscribed persists until that task is evicted (AGENT_SDK_TASK_TTL, default 1h). Meanwhile the still-running worker's store.publish walks that orphan for every frame and fills its 256-slot queue until it self-kills. The memory.py:76-77 comment claims the list is "bounded here", which is true only per re-subscribed task, not per task.
- fix: Either sweep dead-owner subscriptions in publish()/touch() as well as subscribe(), or narrow the memory.py comment to state the bound is per-task-on-next-subscribe so the residual window is documented rather than implied away.
- sdkCandidate: true

## Instruction

Fix remaining findings, then re-run /wave w040.
