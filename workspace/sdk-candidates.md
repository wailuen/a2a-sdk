# SDK issue candidates — w039 (2026-09-03)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

**Reconciliation note (2026-09-04):** 8 candidates from the original 25 described the local/origin
branch-divergence problem itself (unmerged v0.6.0/v0.7.0, pyproject/CHANGELOG version mismatches,
a weaker duplicate GH-145 fix, a forked `redact.py`, a stale mypy error) — all resolved by merge
commit `0dc0517` (origin/main merged into main, now 0 commits behind) plus its uncommitted
follow-up cleanup. Verified directly against current code/state, not just by removing them:
`git rev-list --left-right --count main...origin/main` reads `6 0`; `pyproject.toml` and
`CHANGELOG.md` agree on 0.8.0 with GH-145/147/149/150 entries present; `bedrock.py` has both the
`AUTH_TYPE_MAPS` probe and `set_credentials` pre-seeding; `redact.py` exports both `sanitize_text`
and `safe_error_text` as the merge intended; `mypy` is clean and `is_content_sequence` is already
a `TypeGuard`. Removed and renumbered below; nothing else was changed.

## Candidate 1: TaskStore's C-005 durable-store contract promises that overriding persist_messages (for messages) and persist_status (for status) together makes a copy-on-get store correct, but persist_messages has exactly one call site in the whole SDK (runner.py:493, inside repair_dangling_tool_use), which never runs on normal task completion. RT-B-008's change now flushes terminal COMPLETED/FAILED status on the happy path via _set_status(store=store) without ever calling persist_messages, so a durable store marks a task terminal before ever receiving its transcript.
- Severity: high
- Component: sdk/build
- File: agent_sdk/tasks/store.py
- Rationale: Core SDK internals — the abstract TaskStore contract that every durable subclass implements against; not agent-specific code. No routes/console/credentials-specific fit, so bucketed under sdk/build as SDK internal state/persistence layer.

## Candidate 2: repair_dangling_tool_use(store=...) is unguarded at 3 of its 5 call sites (runner.py:594 in _fail, :1092 in run_task_worker's except AgentError, :1121 in except Exception). Its persist_messages flush can raise, and a raising store there escapes as an unhandled exception in a fire-and-forget asyncio.Task, leaving the task stuck WORKING with streams never sentinel-closed. Only the tasks_cancel path already has this guard.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py
- Rationale: runner.py is the agent task-worker execution machinery — the SDK's turn/task loop, not agent-specific tool code.

## Candidate 3: repair_dangling_tool_use dereferences block['toolUse']['toolUseId'] with only a shallow isinstance/key-presence guard, so a malformed tail block raises TypeError/KeyError inside repair_dangling_tool_use_safe, which swallows it and returns False — but all five callers then proceed unconditionally to set_task_status, durably committing a terminal status over an unrepaired transcript (recreating the GH-150 dangling-toolUse replay bug).
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py
- Rationale: Same runner.py task-worker repair machinery — core SDK loop internals.

## Candidate 4: _run_deferred_background interpolates the caught exception's class name directly into wire-facing strings (f"deferred job failed ({type(exc).__name__})" at runner.py:821 and f"internal error ({type(exc).__name__})" at :1007), which reach WireError.message, the status Message, and ToolResultEvent.error — leaking upstream provider/auth/quota failure class names to untrusted callers, contradicting the same release's own fix that removed identical enrichment from bedrock.py.
- Severity: high
- Component: security
- File: agent_sdk/agent/runner.py
- Rationale: Direct violation of the SDK's wire-information-disclosure policy (LRN-044) — an exception-detail leak to untrusted protocol callers is a security classification, not a functional loop bug.

## Candidate 5: Three bare except Exception blocks in runner.py (lines 895, 1056, 1405) drop the caught exception's class entirely with no logger call before mapping it to a fixed wire string — a direct LRN-044 Check-clause violation, since pydantic's ValidationError subclasses ValueError, so validation failures (e.g. inside build_artifact) get reduced to "invalid agent response" with zero operator attribution.
- Severity: critical
- Component: security
- File: agent_sdk/agent/runner.py
- Rationale: Same LRN-044 wire-vs-log exception-handling security policy as the other exception-enrichment findings, just the missing-log-line direction — security component for consistency.

## Candidate 6: repair_dangling_tool_use_safe collapses two different outcomes (in-memory repair failed vs. in-memory repair succeeded but the durable persist_messages flush failed) into one boolean, and all five callers thread it into set_task_status(repaired=...), which treats repaired=False as 'skip both durable flushes and return' — so a single transient durable-store write failure permanently prevents the terminal status from ever reaching storage, even though set_task_status's own retry logic would otherwise recover it.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py
- Rationale: Core task-worker/loop repair-and-flush machinery in runner.py.

## Candidate 7: Three broad except Exception handlers in run_loop (loop.py:1027, :1069, :1123) interpolate the caught exception's class name into the wire-facing tool error (f"tool '{tc.name}' failed ({type(exc).__name__})"), which is stringified verbatim into the AG-UI TOOL_CALL_RESULT frame and folded into record.messages for replay — violating the same wave's own amended LRN-044 Check clause, already applied to bedrock.py and runner.py but missed in loop.py.
- Severity: critical
- Component: security
- File: agent_sdk/agent/loop.py
- Rationale: LRN-044 wire-information-disclosure policy violation — security component, matching the other exception-enrichment findings.

## Candidate 8: Hoisting metadata: dict[str, Any] | None onto ContentModel and splitting to_plain_text() into a concrete base method over a new abstract _body_text() changes wire key order for all 14 FROZEN Profile types, adds a new abstractmethod to a public ABC, and hard-fails class definition for any external subclass with a plain metadata attribute — none of it required by external protocol conformance, yet shipped under a patch version (0.5.45) in violation of DESIGN.md §4.0's rule that a voluntary breaking change to the stable core requires a major bump.
- Severity: high
- Component: sdk/build
- File: agent_sdk/models/content_types.py
- Rationale: Core ContentModel base-class / release-versioning policy — an SDK internals + release-process issue, not agent-specific code; sdk/build covers both the model internals and the version-bump-policy violation.

## Candidate 9: The to_plain_text()→_body_text() split infinitely recurses for any domain card that subclasses a CONCRETE built-in card and extends its text via super().to_plain_text() — previously-legal code against the old API. __init_subclass__ rebinds the override to _body_text and hands the name back to the base ContentModel.to_plain_text, so super() resolves back into the same override, hitting RecursionError on every request that emits that card's mandatory text fallback.
- Severity: high
- Component: sdk/build
- File: agent_sdk/models/content_types.py
- Rationale: ContentModel is core SDK internals shared by every content type; the bug is in the base-class template-method mechanism, not any specific agent's domain card.

## Candidate 10: run_task_worker's terminal except AgentError (line 1385) and except Exception (line 1423) handlers carry no already-terminal guard, so an exception escaping run_loop after a concurrent tasks_cancel has committed CANCELED overwrites it with FAILED — durably persisting FAILED over CANCELED and publishing a second terminal frame onto streams the canceller already closed. _run_deferred_background._fail already has this guard; the two worker handlers do not.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py
- Rationale: Task-worker terminal-state race condition in the core agent loop machinery.

## Candidate 11: The new MAX_CONTEXT_MESSAGES=50 cap silently disables A2A contextId continuation entirely once a single task produces more than ~50 messages: _turn_boundary_slice returns [] with no log line when the trailing cap-sized window contains no plain user turn, and context_messages() returns that empty list, dropping the whole prior transcript rather than truncating it. Verified numerically: max_turns=24 carries 50 messages, max_turns=25 carries 0.
- Severity: high
- Component: sdk/build
- File: agent_sdk/tasks/memory.py
- Rationale: InMemoryTaskStore internals — core SDK task/context storage, no protocol-route-specific fit, so sdk/build.

## Candidate 12: ContentModel.__init_subclass__ raises TypeError at class-definition time when a subclass declares both a _body_text() method and a to_plain_text() override — before 0.5.45 _body_text had no reserved meaning, so a domain card with an unrelated private helper of that name now fails at import, contradicting the CHANGELOG's 'Migration: none required' claim for this same change.
- Severity: high
- Component: sdk/build
- File: agent_sdk/models/content_types.py
- Rationale: ContentModel base-class internals — same SDK model-layer bucket as the other content_types.py findings.

## Candidate 13: All three advisor copies (.claude/agents, harness/agents, template) had TimeSeriesChart's typed metadata: {identifier?, metric?, frequency?, source?} row deleted and replaced with a free-form cross-cutting note plus a directive that a conformance audit MUST NOT flag a type for metadata — loosening the frozen A2UI Standard Profile v1 contract to make the SDK's own code conformant. REVIEWS.md Round 8 records this as PROPOSED/unratified, yet it shipped in the release commit anyway, and the test gate only fails on a revert, never on the unratified edit being present.
- Severity: high
- Component: harness/agent
- File: .claude/agents/a2ui-advisor.md
- Rationale: The a2ui-advisor.md file is the harness's portable conformance-oracle agent definition (used across projects by /a2ui-check), not agent-domain code — maps directly to the harness/agent component.

## Candidate 14: bridge_context_messages' head repair is skipped in exactly the case the head is broken: its RT-007 guard disables the head trim whenever no genuine user-turn boundary exists anywhere in the transcript, so a leading toolResult orphan or a leading assistant message both survive untouched, and routes/a2a.py then appends the new user turn onto a Converse-illegal conversation head — reachable through any external durable TaskStore whose context_messages() lacks a guaranteed-legal head.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: Core transcript-normalization logic inside the agent conversation loop.

## Candidate 15: The migration docs claim that from a new _body_text() override, super()._body_text() and super().to_plain_text() 'both resolve correctly' and differ only by one extra indirection — false: super().to_plain_text() from a _body_text() override recurses forever, because the re-entrancy guard only fires for the legacy adoption path, not for new-style _body_text overrides that call super().to_plain_text() directly.
- Severity: high
- Component: sdk/build
- File: docs/content-types.md
- Rationale: Documents the same ContentModel base-class mechanism as the other content_types.py findings — sdk/build for consistency, since it's SDK reference documentation for core model internals rather than a protocol route or harness file.

## Candidate 16: bridge_context_messages' DanglingToolUseUnreadable recovery pops one message and never re-runs close_dangling_tool_use, so a transcript whose unreadable tail sits on top of a readable dangling toolUse is returned still dangling and folded into a new task's record.messages, which Bedrock's Converse API then rejects.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: Transcript-repair logic inside the core agent loop module.

## Candidate 17: The /admin/api/selfcheck-info endpoint hardcodes "mcp_protocol_version": "2025-06-18" instead of deriving it from routes/mcp.py's SUPPORTED_PROTOCOL_VERSIONS[0] (currently 2025-11-25) — so the operator's own self-check diagnostic (selfcheck.js's probeMcp()) always negotiates the stale version and never exercises fields gated behind the newer negotiated version (e.g. serverInfo.title, GH-43), and misreports the SDK's actual max supported MCP protocol version to any operator debugging connectivity.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/admin.py
- Rationale: A protocol-version constant that has drifted from its single source of truth in routes/mcp.py — directly a protocol-routes / MCP version-negotiation defect, mapping to protocol/mcp.
