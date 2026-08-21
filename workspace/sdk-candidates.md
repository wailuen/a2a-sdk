# SDK issue candidates — w040 (2026-08-19)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GET /mcp registers an admission-cap slot before the StreamingResponse is created, but the only release path is the heartbeat generator's finally, which never runs if the ASGI response is cancelled before the generator body starts; mcp_get_streams has no TTL or eviction, so leaked slots permanently shrink the process-wide cap.
- Severity: critical
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: Defect lives in a protocol route file (agent_sdk/routes/mcp.py), explicitly in-scope; the admission-cap mechanism it breaks is GET /mcp's, so protocol/mcp.

## Candidate 2: The identity-scoped terminal-task vs missing-task error-code split in message:stream has no regression test proving a foreign identity's terminal task returns 404/-32001 rather than 501/-32004, leaving the invariant unprotected against refactors.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: Test-coverage gap on the A2A route's own error-code contract (agent_sdk/routes/a2a.py); protocol/a2a.

## Candidate 3: LRN-103's narrative and harness/skills/acceptance/SKILL.md both still claim message/send or message/stream on a terminal task returns -32001, but after GH-144 both return 501/-32004 — the learning was not reconciled with the wire-code change in the same wave.
- Severity: high
- Component: harness/skill
- File: workspace/learning/LRN-103-a2a-multiturn-contextid-continuation.md
- Rationale: Both the learning doc and harness/skills/acceptance/SKILL.md are harness/skills artifacts documenting SDK wire behavior; harness/skill.

## Candidate 4: The TTL backstop (_prune_get_streams / _GET_STREAM_TTL_SECONDS) can reclaim bookkeeping entries for streams that are still live but backpressured, defeating the admission cap it was meant to protect and contradicting the module's own reject-not-evict rationale.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: Bug in agent_sdk/routes/mcp.py's stream-cap mechanism; protocol/mcp.

## Candidate 5: docs/protocols.md states terminal-task resume returns 409/-32002, which is wrong for both message/send (501/-32004) and message/stream (now 501/-32004 after GH-144); -32002 is reserved for tasks/cancel only.
- Severity: high
- Component: protocol/a2a
- File: docs/protocols.md
- Rationale: Public documentation of the A2A error-code contract emitted by agent_sdk/routes/a2a.py; protocol/a2a.

## Candidate 6: GET /mcp's new admission cap does not cover the identically-authenticated, identically-indefinite GET /mcp/sse route in the same module, so the DoS GH-143 was meant to close is bypassable by hitting the sibling endpoint, whose evict-oldest logic also severs other tenants' live SSE streams.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: Both routes live in agent_sdk/routes/mcp.py; protocol/mcp.

## Candidate 7: Neither the GH-144 wire-code change (terminal-stream 404/-32001 -> 501/-32004) nor the GH-143 429 admission response is recorded in CHANGELOG.md, and there is no [Unreleased] section even though both are stable-core wire changes requiring a typed entry and migration callout.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: Release/versioning documentation gap for the SDK's stable-core wire contract; sdk/build owns CHANGELOG/versioning discipline.

## Candidate 8: Deleting _MAX_SSE_SESSIONS' evict-oldest loop left _prune_get_streams reclaiming only the streams dict, never _sse_queues(), even though mcp_sse's release() owns both — leaked GET /mcp/sse entries pin an asyncio.Queue for the process lifetime and the new cap never throttles repetition.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: Bug in agent_sdk/routes/mcp.py's SSE session bookkeeping; protocol/mcp.

## Candidate 9: The GH-144 CHANGELOG entry claims the wire break qualifies for DESIGN.md §4.0's conformance exemption, but neither required condition is met, and the repo's own signed-off audit classifies it as a non-hard-MUST internal inconsistency.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: SemVer/release-classification defect in CHANGELOG.md; sdk/build.

## Candidate 10: Subscription gains a new public owner_task attribute and InMemoryTaskStore.subscribe gains reaping behavior, but neither store.py nor memory.py is declared in the wave's todo scope or CHANGELOG file lists, despite Subscription/TaskStore being exported stable-core public API.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/store.py
- Rationale: TaskStore is core SDK task-execution infrastructure (SDK internals, analogous to the credential-store example); sdk/loop.

## Candidate 11: The orphan-subscription reap that agent_sdk/routes/a2a.py now depends on lives only inside InMemoryTaskStore.subscribe; the abstract TaskStore.subscribe declaration has no docstring stating the obligation, so any alternate TaskStore implementation silently reintroduces the unbounded subscription-list leak.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/store.py
- Rationale: TaskStore ABC contract is core SDK internals; sdk/loop.

## Candidate 12: Slot-release callables passed to Starlette's BackgroundTask are plain defs, so BackgroundTask dispatches them via a threadpool, letting them mutate event-loop-owned state from another thread — reproduced causing 'dict mutated during iteration' 500s and a silently dropped SSE frame.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: Concurrency bug anchored in agent_sdk/routes/mcp.py's stream lifecycle; protocol/mcp.

## Candidate 13: (Duplicate/variant) The GH-144 CHANGELOG entry's citation of DESIGN.md §4.0's wire-shape exemption fails both required conditions and contradicts REVIEWS.md's own 'not a hard-MUST breach' verdict for the same change.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: Same release-documentation classification issue; sdk/build.

## Candidate 14: (Duplicate/variant) TaskStore.subscribe's abstract declaration has no docstring establishing the orphan-reap obligation that agent_sdk/routes/a2a.py's leak-safety now depends on, so any alternate TaskStore implementation reintroduces the leak silently.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/store.py
- Rationale: TaskStore ABC; sdk/loop.

## Candidate 15: (Duplicate/variant) Subscription.owner_task and InMemoryTaskStore's reaping behavior are undeclared stable-core public API additions outside the wave's declared Modifies scope, alongside several other dirtied doc files with no Creates/Modifies line of their own.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/store.py
- Rationale: TaskStore/Subscription are core SDK task infrastructure; sdk/loop.

## Candidate 16: Only the harness/ authoring copy of the acceptance SKILL.md was updated for GH-144; the executing .claude/ copy and the peer-repo template/.claude/ copy both still instruct sending taskId on every follow-up turn with no completed-vs-interrupted split, so every multi-turn acceptance run now fails 501/-32004.
- Severity: high
- Component: harness/skill
- File: .claude/skills/acceptance/SKILL.md
- Rationale: SKILL.md mirror-drift in a harness skill; harness/skill.

## Candidate 17: New 429 responses on GET /mcp and GET /mcp/sse are asserted only on status_code — no test checks the Retry-After header, the MCP-Protocol-Version header, or that the rejection body/logs never leak the caller's identity subject.
- Severity: high
- Component: protocol/mcp
- File: tests/test_gh143_mcp_get_stream_cap.py
- Rationale: SDK's own test suite covering agent_sdk/routes/mcp.py's protocol contract (not an agent's domain test); protocol/mcp.

## Candidate 18: _MAX_GET_STREAMS_PER_IDENTITY is keyed on _identity_key(), which is the OAuth client_id or API-key id — never an end user — so under org-wide OAuth client provisioning or a shared API key, every caller in an organization collapses onto one quota key and the whole org is capped at 8 concurrent MCP streams with no override.
- Severity: critical
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: Bug in agent_sdk/routes/mcp.py's admission-cap keying, enforced and fixed in the MCP route; protocol/mcp.

## Candidate 19: The DoS GH-143 aimed to close remains reachable via POST /v1/tasks/{id}:subscribe and POST /v1/message:stream, which hold indefinite authenticated SSE responses on the same connection pool with no concurrency accounting.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: Missing admission control on agent_sdk/routes/a2a.py's streaming endpoints; protocol/a2a.

## Candidate 20: The tree is left self-contradictory: CHANGELOG.md concludes GH-144 needs a 0.7.0 major bump, pyproject.toml is still pinned at 0.6.0, both todos remain unchecked, and REVIEWS.md still marks both issues 'DEFER to a future wave' even though this is that wave.
- Severity: high
- Component: sdk/build
- File: pyproject.toml
- Rationale: Version/release-state bookkeeping in pyproject.toml; sdk/build.

## Candidate 21: The new A2A stream admission budget has only a global cap and a per-task cap (vacuous on the no-taskId path, which always mints a fresh task id) — no per-identity dimension — so one tenant can consume the entire global budget and lock out every other tenant.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: Admission-control gap in agent_sdk/routes/a2a.py; protocol/a2a.

## Candidate 22: The GH-144 fix to the peer-repo template's acceptance SKILL.md was edited in the working tree but never committed/pushed to the separate wailuen/a2a-agent-template clone (gitignored by a2a-sdk), so it is silently lost even though the wave todo was archived as complete.
- Severity: high
- Component: harness/template
- File: template/.claude/skills/acceptance/SKILL.md
- Rationale: Defect in the template scaffold's delivery process; harness/template.

## Candidate 23: message_stream's no-taskId branch creates a TaskRecord before the new admission cap is checked, so a 429-rejected request still inserts an orphan record into the LRU-bounded task store, whose eviction can sever another tenant's in-flight SSE stream — the reject-not-evict path becomes an eviction vector.
- Severity: critical
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: Ordering bug in agent_sdk/routes/a2a.py's admission path; protocol/a2a.

## Candidate 24: POST /ag-ui/run is a third authenticated, indefinitely-held SSE stream on the same connection pool with no admission cap at all — it appears in neither the MCP nor A2A stream-tracking structures, leaving the DoS the cap was built to close fully reachable via this route.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: Missing admission control on agent_sdk/routes/ag_ui.py; protocol/ag-ui.

## Candidate 25: The new 429 admission-cap behavior across GET /mcp, GET /mcp/sse, POST /v1/message:stream and POST /v1/tasks/{id}:subscribe is undocumented in DESIGN.md, docs/protocols.md, and module docstrings, even though a 429 on the MCP path is a known Claude.ai 'Couldn't connect' failure mode.
- Severity: high
- Component: security
- File: DESIGN.md
- Rationale: Concerns an undocumented DoS/rate-limiting protection spanning multiple protocol routes; classified under the cross-cutting security component since it documents a security/availability control, not a single protocol's wire shape.

## Candidate 26: _evict_over_capacity skips only interrupted records, never records with live subscriptions, so store-capacity overflow driven by any authenticated caller can evict and sever another tenant's live-streamed task with no final:true frame.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/memory.py
- Rationale: Core task-store eviction bug in agent_sdk/tasks/memory.py; sdk/loop.

## Candidate 27: The entire stream-admission mechanism (_identity_key, stream tracking, pruning, per-identity limit resolution, rejection handling) is implemented twice — near-identical between mcp.py and a2a.py — with no shared component registered, and the two copies have already drifted in record shape and rejection style.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: Duplicated logic anchored at agent_sdk/routes/a2a.py:161; protocol/a2a.

## Candidate 28: The new max_mcp_streams_per_identity / max_a2a_streams_per_identity settings have no lower-bound validation; an operator setting 0 or a negative value (a natural 'unlimited' reading) causes the admission guard to reject every stream for every identity with no startup error.
- Severity: high
- Component: security
- File: agent_sdk/config.py
- Rationale: Unvalidated operator-facing setting causes a full self-inflicted denial of service; classified security for the input-validation/availability defect.

## Candidate 29: The live acceptance SKILL.md copy still interpolates the resolved admin API key directly into a Workflow input (leaking it into transcripts) instead of the GH-89/SI-2 chmod-600 temp-file pattern the harness/ source of truth now uses, and its scriptPath points at a workflow file that does not exist.
- Severity: high
- Component: security
- File: .claude/skills/acceptance/SKILL.md
- Rationale: Credential/secret exposure into transcripts is a security defect, even though the artifact is a harness skill file.

## Candidate 30: POST /ag-ui/run admits against the shared A2A stream budget but never calls slot.bind() on its subscriptions, so the documented per-task subscriber cap is silently unenforced for AG-UI-originated subscribers on a task, undercounting the very budget it is documented to share.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: Admission-binding bug in agent_sdk/routes/ag_ui.py; protocol/ag-ui.

## Candidate 31: No test in the suite asserts that an admitted GET /mcp (or GET /mcp/sse) actually returns HTTP 200 with content-type text/event-stream after the new rejection branches were added, so a regression that breaks the happy path could pass the entire suite green.
- Severity: high
- Component: protocol/mcp
- File: tests/test_gh143_mcp_get_stream_cap.py
- Rationale: SDK test-coverage gap for agent_sdk/routes/mcp.py's happy path; protocol/mcp.

## Candidate 32: Three new stable-core additions — the AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY setting, the new agent_sdk/common/admission.py module, and the per-identity A2A cap layer itself — ship with zero CHANGELOG record, and the existing A2A entry misdescribes the shipped design by omitting the per-identity layer entirely.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: Release/versioning documentation gap for new stable-core public API surface; sdk/build.

## Candidate 33: TaskStore.subscribe's abstract docstring mandates calling the reap helper but never mandates that implementations record Subscription.owner_task on the subscription they return, so a third-party TaskStore that reaps but forgets to stamp owner_task has a permanently vacuous reap.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/store.py
- Rationale: TaskStore ABC contract gap; sdk/loop.

## Candidate 34: Two stable-core behavior changes to InMemoryTaskStore — permanently skipping live-subscriber records during eviction, and publish() now refreshing LRU order — landed with no CHANGELOG entry and no DESIGN.md §5.2 update, changing the store's documented LRU-1000 and worst-case occupancy guarantees.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/memory.py
- Rationale: Behavior change in core task-store internals (agent_sdk/tasks/memory.py); sdk/loop.

## Candidate 35: _handle_tools_call's structuredContent coercion branch gates on the raw emits type rather than on output_schema() being non-None, so a tool declared with a non-BaseModel emits type (a supported pattern) throws an unhandled AttributeError on every successful MCP tools/call invocation, while the identical tool succeeds on A2A/AG-UI — breaking cross-surface tool parity.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: Correctness bug in agent_sdk/routes/mcp.py's MCP tools/call handling (root cause traces into SDK internals registry.py/loop.py); the observable break and fix site are in the MCP route, so protocol/mcp.
