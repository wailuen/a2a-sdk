wave: w055
scope: phase
date: 2026-10-17

Non-blocking — these did not block w055's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every phase redteam round. Where several rounds raised the same
finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. All findings are SDK-level (sdkCandidate: true).

## Findings

### RT-001
- severity: medium
- file: agent_sdk/app.py
- description: GH-194's opt-out `LoopPolicies.empty_reply_retry=False` cannot be reached by an app built with build_app(). app.py:643-650 builds LoopPolicies only from settings, and BaseAgentSettings has no `empty_reply_retry` field, unlike its sibling `final_summary` (AGENT_SDK_FINAL_SUMMARY, config.py:234). docs/tools.md ('Set False for the old silent end') and the CHANGELOG promise an opt-out that downstream agents cannot use.
- fix: Add `empty_reply_retry: bool = Field(default=True, alias="AGENT_SDK_EMPTY_REPLY_RETRY")` to BaseAgentSettings, pass `empty_reply_retry=settings.empty_reply_retry` in app.py's LoopPolicies(...), document it in docs/deployment.md next to AGENT_SDK_FINAL_SUMMARY, and add a build_app-level test that the env var turns the retry off.
- codify: A new LoopPolicies flag only counts as an opt-out once build_app() wires it from a BaseAgentSettings field; check app.py's LoopPolicies(...) call whenever a policy field is added.

### RT-002
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: A blocking resume in message_send returns the `record` that `_resume_or_error` fetched BEFORE `_wait_blocking`, and never reads it from the store again. store.py:131-140 explicitly allows a durable TaskStore whose get() returns a fresh copy (kept up to date through persist_status/persist_messages). With such a store, the blocking resume answers with the stale pre-resume input-required snapshot, so a client may resume again. The todo's SI-5 note also asked that the blocking wait re-check task ownership, which this path never does.
- fix: After `await _wait_blocking(request, sub)` in the resume branch, re-fetch with `fresh = request.app.state.task_store.get(params.message.task_id, identity)`. Use `fresh` for `_echo_a2ui_if_present`/`_task_wire` when it is not None, and keep the 404-style reply when it is None. Add a test with a copy-returning TaskStore subclass.
- codify: A route that waits and then returns a TaskRecord must read it from the store again after the wait; only InMemoryTaskStore guarantees that get() returns the live object.

### RT-003
- severity: medium
- file: agent_sdk/routes/a2a.py
- description: The blocking-resume branch of message_send calls `_admit` and `slot.subscribe(existing.task.id)` before `_resume_or_error`'s state checks, and outside the try/finally. (a) Under stream saturation, a resume of an owned terminal or still-working task gets 429 instead of the -32004 that the non-blocking path returns, so error order depends on `blocking`. (b) `_admit` awaits `prune_finished`, so the record can be evicted between store.get and subscribe. InMemoryTaskStore.subscribe does `self._records[task_id]` (memory.py:200) and raises KeyError, which becomes an unhandled 500, and the claimed slot is only reclaimed later by prune.
- fix: Run the terminal / non-interrupt state checks (or the whole of `_resume_or_error` minus deliver_resume) before admitting. Move `sub = slot.subscribe(...)` inside the `try:` whose `finally` releases the slot. Map a missing record at subscribe time to `a2a_error(A2A_TASK_NOT_FOUND, ...)`.
- codify: Every `slot.subscribe()` after an awaited `_admit()` must sit inside the try/finally that releases the slot, because the record can be evicted during the await.

### RT-004
- severity: medium
- file: agent_sdk/console/static/retry.js
- description: On any non-retried failure, including 401 and 403, postWithRetry runs `traceFrame(`HTTP ${resp.status}`, await resp.text())`, which writes the raw server error body into the console's trace pane in the page. The GH-191 todo's SI-5 note says the 401/403 error display must not render server error bodies into the page. The new shared module keeps the old behaviour and now applies it to the A2A send path too.
- fix: For 401/403 (and ideally every auth failure), call traceFrame with the status only (for example `traceFrame(`HTTP ${status}`, "(body not shown)")`) and never read resp.text(). Extend tests/test_gh191_console_retry_policy.py so the driver asserts that traceFrame never receives the body for 401/403.
- codify: The console must never render auth-failure response bodies into the page; a shared retry helper has to apply the same rule on every send path.

### RT-005
- severity: medium
- file: docs/deployment.md
- description: Docs drift for GH-189. `AGENT_SDK_BLOCKING_SEND_MAX` is missing from docs/deployment.md, which lists runtime settings (AGENT_SDK_FINAL_SUMMARY etc.) and was named in the todo's Modifies list ('if it lists settings'). DESIGN.md's stream-admission bullet (~line 375) still lists only message:stream, :subscribe and /ag-ui/run as users of the A2A stream budget, and calls POST /v1/message:send uncapped by design. A blocking send now claims an A2A stream slot and can return 429 + Retry-After.
- fix: Add an AGENT_SDK_BLOCKING_SEND_MAX entry (default 120 s, must be > 0, capped by the task deadline, holds one A2A stream slot for the wait) to docs/deployment.md. Update DESIGN.md's admission bullet and the docs/protocols.md 429 row to include blocking `message:send` / blocking resume.

### RT-006
- severity: low
- file: agent_sdk/routes/agent_card.py
- description: GH-188 builds supportedCatalogIds only from `decl.emits`, but other paths disagree with that list. runner.py:1093 (the deferred/long_running success path) builds an A2UI artifact for any ContentModel result even when `emits` is None. A long-running card tool without `emits` therefore renders a catalog the card does not advertise (possibly `[]`). Also, a tool that emits only MarketBriefing, which is delivered as markdown and never as A2UI, makes the card advertise the Standard Profile.
- fix: Either apply the loop's `emits`-gated ArtifactEvent rule to the deferred path (only build an A2UI artifact when isinstance(raw_result, event.emits)), or include those types when deriving catalogs. Skip markdown-only types (MarketBriefing) in supported_catalogs(emits=...). Add tests for both cases.

### RT-007
- severity: low
- file: agent_sdk/agent/registry.py
- description: GH-196 does only part of the C-010 reuse note. The unknown-key check is shared (`_check_unknown_arguments`), but the model_validate block is still copied in both invoke() and invoke_gen(), instead of the single `_validate_input` helper the note asked for. Also, a tool with `allow_extra_args=True` whose model sets `extra="forbid"` advertises `additionalProperties: true` in input_schema(), while pydantic still rejects extra keys. The advertised schema contradicts what is enforced.
- fix: Fold `_check_unknown_arguments` + the narrow model_validate try into one `ToolEntry._validate_input(arguments)` called by both invoke paths. In input_schema(), advertise `true` only when the model's extra is not 'forbid', or reject the allow_extra_args + extra='forbid' combination at registration.
