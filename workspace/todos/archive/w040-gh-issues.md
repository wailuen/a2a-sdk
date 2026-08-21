# w040 — GitHub issues #143–#144

Sourced from open issues on wailuen/a2a-sdk. Both items are independent
(different files, different route modules). Run in parallel (group:G).
Target: v0.6.1.

RT-002 (redteam correction): GH-144's fix does not qualify for DESIGN.md
§4.0's wire-shape conformance exemption (see CHANGELOG's RT-002 correction
under the GH-144 entry) — it is a voluntary stable-core break requiring a
major-equivalent (`0.7.0`) bump, not eligible for the `v0.6.1` patch this
wave otherwise targets. GH-143 has no such exemption dependency (additive
admission control; no existing wire shape changes) and remains `v0.6.1`-
eligible on its own. Release-cut decision (ship GH-144 in a `0.7.0` instead,
or split it out of this wave) is left to the release process — not made
unilaterally here.

Both issues were originally surfaced by the pre-release `/agent-stack-check`
conformance audit ahead of v0.6.0 (2026-08-18) and recorded as deferred
Medium findings in `REVIEWS.md` Round 10, explicitly deferred to "the next
`/gh-review` triage cycle." This is that cycle. Triage confirmed both are
still present verbatim in current code, unfixed, with no active wave
conflicts.

Reconciled (RT-003): both items landed and shipped as `0.7.0` — the
major-equivalent bump this file's own RT-002 note above required for GH-144,
not the `v0.6.1` patch originally targeted (see CHANGELOG.md's "📋 Release
process (RT-003, gh-review triage correction)" entry under `[0.7.0]`, which
also carries the version-bump/todo/REVIEWS.md reconciliation this note
summarizes). A subsequent redteam pass over both items' own admission-control
work surfaced two further findings, also fixed and shipped in the same
`0.7.0`: RT-001 (round 2) — GH-143's per-identity `GET /mcp` cap was keyed on
`_identity_key()`, which collapses an entire org onto one quota under this
SDK's own org-wide OAuth client / shared-API-key deployment modes (fix:
raised default + new `AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY` override,
`agent_sdk/routes/mcp.py`, `agent_sdk/config.py`,
`tests/test_rt001_mcp_org_wide_identity_cap.py`); RT-002 — GH-143's cap
covered `GET /mcp`/`GET /mcp/sse` only, leaving the A2A SSE surface
(`message:stream`'s resume branch, `tasks:subscribe`) with no concurrency
bound at all (fix: shared global + per-task admission budget mirroring
`_get_streams()`, `agent_sdk/routes/a2a.py`, `agent_sdk/app.py`,
`tests/test_rt002_a2a_stream_admission_cap.py`). See CHANGELOG.md `[0.7.0]`
for full detail on both follow-ups.

---

- [x] `GH-144` sdk/a2a: terminal-task error code differs between message/send (-32004) and message/stream (-32001) ‖ group:G
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`, `DESIGN.md`, `docs/protocols.md`, `harness/skills/acceptance/SKILL.md`, `workspace/learning/LRN-103-a2a-multiturn-contextid-continuation.md`, `CHANGELOG.md`)
  - RT-004: widened post-hoc — the RT-001 (round 4) redteam follow-up bundled
    into this item's `a2a.py` edit also touches `agent_sdk/tasks/store.py`
    (`Subscription.owner_task`, `TaskStore.reap_dead_subscriptions`) and
    `agent_sdk/tasks/memory.py` (`InMemoryTaskStore.subscribe`'s reap call) —
    see the CHANGELOG's RT-001 (round 4) Security entry.
  - Reads: `agent_sdk/routes/a2a.py`, `agent_sdk/models/errors.py`
  - Severity: medium
  - Root cause: `message_stream`'s task_id branch (`agent_sdk/routes/a2a.py:330-335`) short-circuits on `record is None or record.task.status.state in TERMINAL_STATES` and returns `A2A_TASK_NOT_FOUND` (-32001, HTTP 404) for both cases — before `_resume_or_error` (lines 191-218) is ever reached. `_resume_or_error`, used by `message/send`, has its own terminal check (lines 199-204) that instead returns `A2A_UNSUPPORTED_OPERATION` (-32004, HTTP 501) for the identical terminal-state condition, with an explicit "A2A-F1" comment justifying that code. `-32001` is defined as "task ID not found," which is a semantic misuse for a task that exists but is terminal. The in-code comment at line 334 ("not found OR terminal: no resumable task (consistent with resume path)") asserts equivalence with the resume path that does not actually hold.
  - AC: `message_stream`'s task_id branch distinguishes a genuinely-missing record (`record is None` → -32001/404) from a present-but-terminal record (→ -32004/501, matching `_resume_or_error`'s behavior for `message/send`), without opening/aborting a stream subscription for the terminal case.
  - AC: A test asserts `message/stream` on a terminal-state task with `taskId` returns HTTP 501 / -32004, matching `message/send`'s existing behavior for the same input.
  - AC: The stale comment at `agent_sdk/routes/a2a.py:334` is updated to reflect the corrected, code-differentiated behavior.
  - GH: https://github.com/wailuen/a2a-sdk/issues/144
  - SI: `SI-2`  # No SI: field, but the todo rewrites an error-emission path. The new missing-vs-terminal split at agent_sdk/routes/a2a.py:333-335 must keep STATIC error text ('task not found' / 'task is in a terminal state and cannot accept new messages', matching _resume_or_error at :198/:204) — never interpolate the caller-supplied params.message.task_id, params.message.context_id, or any request payload into the -32001/-32004 message or into a log line added while debugging the split.
  - SI: `SI-5`  # No SI: field, but this changes an authenticated data path's disclosure surface. The new -32004 terminal branch MUST stay strictly downstream of the identity-scoped store.get(params.message.task_id, identity) at a2a.py:332 — a task owned by another identity returns None there and must keep yielding -32001/404. Differentiating 'missing' from 'terminal' above that call, or on an unscoped lookup, converts the branch into a cross-identity existence oracle and breaks the task-identity-binding invariant in DESIGN.md:266 ('existence is not leaked'). Depends(require_identity) and guard_origin at a2a.py:329 must remain unchanged.

- [x] `GH-143` sdk/mcp: GET /mcp SSE stream has no cap on concurrent connections (DoS risk) ‖ group:G
  - Creates: (modifies `agent_sdk/routes/mcp.py`, `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`, `CHANGELOG.md`)
  - RT-004: widened post-hoc — the RT-001 (round 4) redteam follow-up bundled
    into this item's `mcp.py` edit also touches `agent_sdk/tasks/store.py`
    (`Subscription.owner_task`, `TaskStore.reap_dead_subscriptions`) and
    `agent_sdk/tasks/memory.py` (`InMemoryTaskStore.subscribe`'s reap call) —
    see the CHANGELOG's RT-001 (round 4) Security entry.
  - Reads: `agent_sdk/routes/mcp.py`, `agent_sdk/auth/middleware.py`, `agent_sdk/common/limits.py`
  - Severity: medium
  - Root cause: `mcp_get` (`agent_sdk/routes/mcp.py:688-724`) returns an authenticated, indefinitely-held `text/event-stream` heartbeat (15s loop) with no tracking of concurrent open streams, per-identity or global. `identity_limiter` (`agent_sdk/auth/middleware.py:117`, backed by `RateLimiter.allow()` in `agent_sdk/common/limits.py:18-39`) only rate-limits the request that *establishes* the stream — it plays no role once the `StreamingResponse` is returned. The legacy SSE transport already solves this next door: `mcp_sse` (`mcp.py:770-805`) tracks sessions via `_sse_queues()` (`mcp.py:169-176`), enforces `_MAX_SSE_SESSIONS=500` (`mcp.py:106`) with evict-oldest at `mcp.py:781-782`, and cleans up in a `finally` block (`mcp.py:800-801`). The server is single-process/single-worker by design (`config.py:161-165`; `template/Dockerfile:65 --workers 1`), so exhausting this channel degrades the whole process for every tenant.
  - AC: A bounded app-state tracking structure for open GET `/mcp` streams exists (e.g. `app.state.mcp_get_streams`), following the `_sse_queues()` accessor pattern at `mcp.py:169-176`.
  - AC: A cap constant analogous to `_MAX_SSE_SESSIONS` (`mcp.py:106`) gates `mcp_get`, enforced (global and/or per-identity via `_identity_key()` at `mcp.py:123-125`) before the `StreamingResponse` is returned; the chosen enforcement strategy (evict-oldest vs. 429-reject) is documented in a comment.
  - AC: The stream is deregistered in a `finally` block inside `heartbeats()` (`mcp.py:712-720`) so disconnects and client timeouts always free the slot, mirroring `mcp_sse`'s cleanup at `mcp.py:800-801`.
  - AC: Unit test(s) verify the cap is enforced at N concurrent GET streams, a released/disconnected stream frees capacity for a new one, and per-identity accounting (if implemented) does not let one identity's streams count against another's quota.
  - GH: https://github.com/wailuen/a2a-sdk/issues/143
  - Reuses: `C-007`  # If the cap-rejection response body, the eviction path, or any new log line carries a caller-derived string, it MUST route through safe_error_text (agent_sdk/common/redact.py) rather than being interpolated raw. Preferred shape: a wholly static 429/503 message with no identity-derived value at all — see the SI-2 annotation. Do not re-derive a local truncate/control-char helper (C-007 exists precisely to stop a divergent copy).
  - SI: `SI-5`  # No SI: field, but the todo adds admission control to an authenticated route and Reads: agent_sdk/auth/middleware.py. (a) The cap must be enforced INSIDE mcp_get after Depends(require_identity) + guard_origin — never as pre-auth middleware, which would let unauthenticated callers consume/deny slots. (b) mcp_get currently binds `_identity: Identity = Depends(require_identity)` (mcp.py:690); per-identity accounting via _identity_key() requires renaming it to `identity` — the Depends must not be dropped or relaxed in that edit. (c) AC-3 as written is a self-DoS hazard: deregistering only in heartbeats()'s finally means a client that disconnects before the generator's first iteration never runs the finally, leaking a slot permanently; under a 429-reject strategy that is an authenticated lockout with no recovery. Tie release to the response lifecycle, or use evict-oldest like _MAX_SSE_SESSIONS (mcp.py:781-782) so leaked slots self-heal.
  - SI: `SI-2`  # No SI: field. _identity_key() returns f'{identity.kind}:{identity.subject}' — an OAuth subject or API-key id. That value, the Authorization header, and the Mcp-Session-Id must never appear in the cap-rejection response body or in any eviction/rejection log line. Per-identity counters may be keyed on it internally, but the emitted 429/503 must be a static message.
