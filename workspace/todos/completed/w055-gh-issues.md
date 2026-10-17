# w055 — GitHub issues 188–198

Sourced from open issues on wailuen/a2a-sdk. GH-186 is deferred by ruling and NOT in this wave.
Target: 0.17.0 (GH-196 is a breaking change; GH-189/193/194 add behaviour).

Grouping: the four `agent_sdk/routes/a2a.py` items are chained through Depends so no two of
them edit that file at the same time (A1 → A2 → A3 → A4). G1 and G2 touch disjoint files and
run alongside A1. Every item adds its own entry to `CHANGELOG.md` `[Unreleased]`.

---

- [ ] `GH-198` Consent CSP form-action blocks Copilot Studio's regional redirect hop ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/oauth.py` (`_redirect_security_headers`, new `_KNOWN_REDIRECT_HOPS`), `tests/test_oauth_flow.py`, `CHANGELOG.md`)
  - Reads: commit `51d339f` (read-only: `git show 51d339f`; do NOT cherry-pick, checkout or change git state, reproduce its diff in the working tree), `workspace/learning/LRN-126*`
  - Severity: high
  - Root cause: the consent page and its 303 set `form-action 'self' <redirect origin>`. Chromium enforces form-action across the whole redirect chain, so `global.consent.azure-apim.net` → 302 → `asia-001.consent.azure-apim.net` is blocked and Copilot Studio never gets the code.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/198#issuecomment-6229360049
  - AC: `_KNOWN_REDIRECT_HOPS = {"https://global.consent.azure-apim.net": ("https://*.consent.azure-apim.net",)}`; its sources are appended to `form-action` only when the validated redirect origin equals the key exactly. No client-supplied text reaches the CSP.
  - AC: Test: approve with redirect_uri `https://global.consent.azure-apim.net/redirect/<id>` → the 303 CSP `form-action` is exactly `'self' https://global.consent.azure-apim.net https://*.consent.azure-apim.net`.
  - AC: Test (LRN-126): the GET `/oauth/authorize` consent-page render for the same client carries the same widened `form-action`.
  - AC: Test: lookalike origins (`global.consent.azure-apim.net.evil.example`, `asia-001.consent.azure-apim.net`, port 8443, trailing-dot host) do NOT get the wildcard source.
  - AC: Test: an unrelated origin (e.g. `https://claude.ai`) gets a CSP byte-identical to before.
  - AC: CHANGELOG Fixed entry with the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/198
  - SI: SI-5  # Changes the OAuth consent CSP in agent_sdk/routes/oauth.py, which is auth code, and has no SI: field. Add SI-5 (auth surface) and SI-2: the CSP must hold only server-side constants from _KNOWN_REDIRECT_HOPS, chosen by an exact match on the validated redirect origin. Per LRN-126, widen form-action on the form-owning GET /oauth/authorize document as well as on the 303.

- [ ] `GH-192` Malformed RunAgentInput reports "no user message" instead of a malformed-body error ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/ag_ui.py` (`_parse_body` and the generator's validation), new `tests/test_gh192_ag_ui_malformed_body.py`, `CHANGELOG.md`)
  - Reads: `DESIGN.md` §5.3 (~line 334), `tests/test_gh97_ag_ui_thread_run_id_synthesis.py`
  - Severity: low
  - Root cause: `_parse_body` turns a non-JSON or non-object body into `{}`, which later fails with the misleading "no user message in input".
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/192#issuecomment-6229361690
  - AC: A body like `{not json` gets 200 SSE: RUN_STARTED then RUN_ERROR with the fixed message `malformed RunAgentInput body` (no body text echoed).
  - AC: A JSON array or scalar body gets the same RUN_ERROR.
  - AC: DESIGN.md §5.3 is unchanged: no 400/422 before the stream, ids still synthesized; GH-97 tests and the existing validation-inside-generator tests stay green.
  - AC: CHANGELOG Fixed entry with the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/192
  - SI: SI-2  # Changes AG-UI ingress parsing, and has no SI: field. Add SI-2: the RUN_ERROR text must be the fixed string 'malformed RunAgentInput body', with no body bytes and no json.JSONDecodeError text (which carries a document excerpt) passed to the error or the logs.

- [ ] `GH-191` Console test chat retries auth failures and replays the whole AG-UI run on stream drop ‖ group:G1
  - Creates: (modifies `agent_sdk/console/static/chat.js` (first-request retry loop ~507-524, stream-drop handler ~664-681), a test under `tests/` for the retry policy (JS logic via an existing console test pattern, or a static check if no JS runner exists), `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/ag_ui.py` (429 `Retry-After`), `tests/` console tests
  - Severity: medium
  - Root cause: any non-OK status (401, 403, 413, 415, 429) is retried with backoff, ignoring `Retry-After`. A stream drop re-POSTs the whole run with a new runId while the first run keeps going on the server, so every tool runs twice. AG-UI has no way to reconnect to a running stream.
  - AC: No retry on 400/401/403/404/413/415/422: show the error line on the first failure.
  - AC: 429 and 503 wait for `Retry-After` seconds (capped at 30 s), a small fixed number of tries; backoff when the header is missing.
  - AC: A network failure with no HTTP response may retry, but only before any SSE frame was read.
  - AC: A stream drop after any frame does NOT re-POST; it shows a line saying the stream dropped, the run may still finish on the server, and it was not resent; the turn ends.
  - AC: The false "prevents server-side duplicate-run rejection" comment is removed. The A2A send path in chat.js gets the same retry rules if it has the same wide retry.
  - AC: Do not change `loadCatalogIds()` (GH-180).
  - AC: CHANGELOG Fixed entry.
  - GH: https://github.com/wailuen/a2a-sdk/issues/191
  - SI: SI-5  # Changes how the admin console client handles 401/403 auth failures and replays, and has no SI: field. Add a note that the error line shown on 401/403 must not render server error bodies or the admin key into the DOM. The no-replay rule must also cover the A2A send path, which can otherwise trigger duplicate tool side effects.

- [ ] `GH-195` ChatDriver cannot answer an AG-UI interrupt ‖ group:G1
  - Creates: (modifies `agent_sdk/testing/chat.py` (`ChatDriver`, new `agui_resume`, shared SSE parsing helper), `docs/testing.md`, new `tests/test_gh195_chatdriver_agui_resume.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/ag_ui.py` (resume input `resume[{interruptId,status,payload}]`), `agent_sdk/console/static/chat.js` (how the console sends a resume)
  - Severity: medium
  - Root cause: `agui_turn` has no resume input and always appends a user message; the only `resume()` posts to A2A.
  - AC: New `ChatDriver.agui_resume(interrupt_id, thread_id, messages, *, payload=None, status="resolved", emit=None)` POSTs `/ag-ui/run` with `resume=[{interruptId, status, payload}]` and does NOT append a user message.
  - AC: SSE frame parsing is shared with `agui_turn` (one helper), so tool/a2ui/text/error/interrupt emits behave the same.
  - AC: Docstring: the `interrupt` emit gets the AG-UI interrupt dict (with `id`) on AG-UI and the task dict on A2A.
  - AC: Test: a ToolInterrupt tool via `agui_turn` fires `interrupt` with an id; `agui_resume(id, payload={"decision": "approved"})` ends with RUN_FINISHED success and the tool result.
  - AC: Test: `agui_resume` with an unknown id fires an error.
  - AC: CHANGELOG entry (provisional `agent_sdk.testing` API, additive).
  - GH: https://github.com/wailuen/a2a-sdk/issues/195

- [ ] `GH-194` Empty final model reply after a tool result ends as an empty success ‖ group:G2
  - Creates: (modifies `agent_sdk/agent/loop.py` (post-tool empty-reply handling ~1308-1320, reuse `_final_summary` pattern), the `LoopPolicies` definition (new flag `empty_reply_retry: bool = True`), new `tests/test_gh194_empty_reply_retry.py`, `docs/` page that lists loop policies, `CHANGELOG.md`)
  - Reads: `agent_sdk/agent/model_client.py`, GH-155 `_final_summary` in `agent_sdk/agent/loop.py`
  - Severity: medium
  - Root cause: a model reply with no tool calls and blank text after a tool result yields `DoneEvent(ok=True)` with no text and no retry.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/194#issuecomment-6229361165
  - AC: After a tool result, a reply with no tool calls and only blank text triggers exactly one extra model call with tools off (`tool_choice="none"`).
  - AC: The retry does not use a `max_turns` turn; its tokens count toward the token budget and yield a UsageEvent.
  - AC: A non-empty retry reply is yielded as text and folded into the transcript, then `DoneEvent(ok=True)`.
  - AC: A still-empty retry, or one that raises, yields the fixed notice `I ran the requested steps but could not write a reply. Please try again or rephrase your request.` and ends `ok=True` — unless a card (ArtifactEvent) was already delivered this turn, in which case no notice is added. No provider text in the notice.
  - AC: No retry on a turn with no tool result, when sealed, past the deadline, or out of token budget; sealed is re-checked after the retry await.
  - AC: `empty_reply_retry=False` restores today's behaviour.
  - AC: Tests with a fake model client: empty→text; empty→empty; empty→raise; card+empty; flag off.
  - AC: CHANGELOG Changed entry with the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/194
  - Reuses: C-017  # Fold the retry reply into the transcript with the shared fold/bridge helpers in agent_sdk/agent/loop.py (fold_result_content / bridge_trailing_user / close_dangling_tool_use), the same path _final_summary (GH-155) uses. A hand-built assistant message would drift from the runner.py and tasks/memory.py consumers.

- [ ] `GH-196` Advertised additionalProperties:false is not enforced ‖ group:G2
  - Creates: (modifies `agent_sdk/agent/registry.py` (`input_schema` ~657-661, `invoke` ~742-751, `invoke_gen` ~787-794), the `@tool` decorator (new `allow_extra_args: bool = False`), `docs/tools.md`, `harness/skills/add-tool/SKILL.md` and its `template/.claude/skills/add-tool/SKILL.md` mirror (one note), new `tests/test_gh196_reject_unknown_tool_args.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/agent/loop.py` (tool call path), `agent_sdk/routes/mcp.py` (`tools/call`), GH-135 `ToolInputValidationError`
  - Severity: medium
  - Root cause: GH-47 set `additionalProperties: false` only for MCP schema shape; arguments are validated with plain `model_validate`, so unknown keys are silently dropped and a misnamed filter returns an unfiltered result that looks filtered.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/196#issuecomment-6229360794
  - AC: `invoke()` and `invoke_gen()` reject argument keys not in the input model (field names and aliases) with `ToolInputValidationError`, unless the input model sets `extra="allow"` or the tool sets `allow_extra_args=True`. The user's model class is not mutated.
  - AC: The error the model sees names the unknown key(s) and location, never the value (SI-2).
  - AC: A tool with no input model and non-empty arguments is rejected unless opted out.
  - AC: `input_schema()` advertises `additionalProperties: false` only when enforced; `true` for opted-out or `extra="allow"` tools.
  - AC: reuse_fields `$ref` tokens and alias-named fields still validate (no false rejects).
  - AC: Tests: default model + extra key rejected on both the loop and MCP `tools/call`; `extra="allow"` model succeeds; opted-out tool succeeds and advertises `true`; a correct call is unchanged. Existing tests that pass extra keys are fixed by correcting the call, not by opting out wholesale.
  - AC: CHANGELOG Breaking changes entry with the ruling URL and migration steps (add the field, or opt out).
  - GH: https://github.com/wailuen/a2a-sdk/issues/196
  - Reuses: C-010  # ToolEntry.invoke_any (agent_sdk/agent/registry.py:811) goes through invoke()/invoke_gen(), so MCP tools/call, admin try-tool and commitments all pick up the check automatically. But the model_validate block is copied in both invoke() (~743-750) and invoke_gen() (~787-792). Move the unknown-key check plus model_validate into ONE private helper (e.g. ToolEntry._validate_input) that both call. Do not add the check twice.
  - Reuses: C-007  # The text the model sees for an unknown key must be built only from loc and error type. Raise it as a pydantic ValidationError of type extra_forbidden, wrapped in ToolInputValidationError, so the existing safe_validation_message (agent_sdk/agent/loop.py:1080) renders it. Any free text that names a key goes through sanitize_text/safe_error_text. Never interpolate the value (SI-2).
  - SI: SI-2  # Changes tool-argument validation on every dispatch surface (loop, MCP tools/call, admin try-tool), and has no SI: field. Add SI-2: the unknown-key error names key and location only, never the value. ToolInputValidationError's own message must stay a fixed string (RT-003).

- [ ] `GH-188` supportedCatalogIds advertises catalogs the agent never emits ‖ group:G2
  - Creates: (modifies `agent_sdk/a2ui/catalog.py` (`supported_catalogs` ~316-326), `agent_sdk/routes/agent_card.py` (~153-170, pass the tool registry), `DESIGN.md` (~line 254), `tests/test_card_console.py` (~line 36), existing SC-D2 tests in `tests/test_a2ui_group_d*.py` as needed, new `tests/test_gh188_catalogs_from_emits.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/models/content_types.py` (PROFILE_TYPES), `agent_sdk/agent/loop.py` (~1728, emits gate), `agent_sdk/a2ui/translator.py`
  - Severity: low
  - Root cause: `supported_catalogs()` always lists the Standard Profile first and every registered domain catalog. Profile types self-register on import, so the issue's proposed fix would change nothing; the real source of truth is the tools' `emits` types.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/188#issuecomment-6229361485
  - AC: `supportedCatalogIds` is built from the catalogs of the registered tools' `emits` types, after the `a2ui_allowed_components` filter.
  - AC: Test: an agent whose only emitting tool emits a domain card advertises only that domain catalog (no `urn:a2ui-profile:standard:v1`).
  - AC: Test: an agent with a tool that emits a Profile type (e.g. KpiCard) lists the Standard Profile first.
  - AC: Test: a registered domain catalog no tool emits is not advertised.
  - AC: Test: an agent with no emitting tools advertises `[]` and the A2UI extension entry is still present.
  - AC: Do not change `agent_sdk/console/static/chat.js` (it already falls back to the Standard Profile).
  - AC: DESIGN.md and CHANGELOG (Changed, agent-card change) updated with the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/188

- [ ] `GH-190` pushNotificationConfigs methods return -32601 instead of -32003 ‖ group:A1
  - Creates: (modifies `agent_sdk/routes/a2a.py` (four new routes), `docs/protocols.md` (error table), new `tests/test_gh190_push_config_not_supported.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/app.py` (~823 fallback), `agent_sdk/routes/agent_card.py` (~200 `pushNotifications: false`), `agent_sdk/models/errors.py` (-32003 → 501)
  - Severity: medium
  - Root cause: no `/v1/tasks/{id}/pushNotificationConfigs*` routes exist, so they fall through to the generic 404/-32601 or 405/-32004.
  - AC: POST and GET `/v1/tasks/{id}/pushNotificationConfigs`, and GET and DELETE `/v1/tasks/{id}/pushNotificationConfigs/{configId}` each return HTTP 501 with `error.code == -32003`.
  - AC: Each route requires identity (no key → 401 + WWW-Authenticate, same as other `/v1/tasks` routes) and passes the origin guard.
  - AC: The reply is the same whether the task exists, belongs to someone else, or is unknown.
  - AC: The POST body is not parsed or echoed.
  - AC: docs/protocols.md error table lists the four routes; CHANGELOG Fixed entry.
  - GH: https://github.com/wailuen/a2a-sdk/issues/190
  - Reuses: C-009  # The four new pushNotificationConfigs routes must call guard_origin(request) from agent_sdk/common/origin.py, plus Depends(require_identity), the same way the other /v1/tasks routes in agent_sdk/routes/a2a.py do (lines 607-609, 886-888, 955-957, 1001-1003). Do not write a second inline origin check.
  - SI: SI-5  # Adds four new A2A routes and has no SI: field. Every route must have Depends(require_identity) plus guard_origin (401 + WWW-Authenticate with no key). The reply must be identical whether the task exists, belongs to another identity, or is unknown, so the routes cannot be used to probe for tasks. Add SI-5.

- [ ] `GH-197` A2A message:stream sends no heartbeat during long tool calls; harness timeout too short ‖ group:A2
  - Creates: (modifies `agent_sdk/routes/a2a.py` (`_open_stream` gen ~859-873), `harness/workflows/acceptance-api.js` (lines ~143 and ~226), new `tests/test_gh197_a2a_stream_heartbeat.py`, `CHANGELOG.md`, `template/.claude/workflows/acceptance-api.js` (lands via commit+push to wailuen/a2a-agent-template per LRN-071; runtime copy is what /acceptance / the harness skill actually executes — implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step))
  - Reads: `agent_sdk/common/sse.py` (`HEARTBEAT`), `agent_sdk/routes/ag_ui.py` (~772-776, 15 s ping pattern)
  - Depends: GH-190
  - Severity: medium
  - Root cause: `_open_stream` awaits `sub.get()` with no timeout, so a long tool sends zero bytes and short-timeout clients disconnect. AG-UI and MCP already send `: ping`.
  - AC: `message:stream`, the resume stream and `tasks/{id}:subscribe` send `HEARTBEAT` comment frames at least every 15 s while nothing is queued. The interval is a shared constant with AG-UI; the test patches it, never sleeps 15 s and never patches `time.monotonic`.
  - AC: The heartbeat is an SSE comment only; the first full-Task frame and the `final: true` ending are unchanged.
  - AC: A timeout never drops a queued item; StreamTerminated, `None` and `final` still end the loop.
  - AC: Client disconnect during the wait still releases the subscription (LRN-193).
  - AC: `harness/workflows/acceptance-api.js` uses a read timeout of at least 600 s on both clients; the skill-mirror parity test stays green (there is no template copy of this workflow).
  - AC: CHANGELOG Fixed entry.
  - GH: https://github.com/wailuen/a2a-sdk/issues/197
  - SI: SI-5  # Changes the A2A SSE transport (message:stream, resume stream, tasks/{id}:subscribe), and has no SI: field. The heartbeat timeout must not skip the per-iteration ownership/termination checks. Per LRN-193, disconnect during the wait must still release the subscription.
  - Mirror: `template/.claude/workflows/acceptance-api.js`  # The todo modifies harness/workflows/acceptance-api.js and states 'there is no template copy of this workflow'. That is false. template/.claude/workflows/acceptance-api.js exists in the peer repo and is byte-identical today; it is the runtime copy downstream agents execute. tests/test_workflow_sync.py (axis 2, harness <-> template byte-identity, test_acceptance_api_is_harness_template_shared) will fail if only the harness copy changes. Add the template path to Modifies, apply the same 600 s read-timeout edit at both clients (~143, ~226), and land it via git -C template commit + push to wailuen/a2a-agent-template per LRN-071/LRN-085.

- [ ] `GH-189` message:send with blocking=true returns 501 instead of waiting ‖ group:A3
  - Creates: (modifies `agent_sdk/routes/a2a.py` (`_config_error` ~408-412, send path ~605-656, resume path), `agent_sdk/config.py` (new `blocking_send_max_seconds`, env `AGENT_SDK_BLOCKING_SEND_MAX`, default 120), `docs/protocols.md` (~line 12 and ~21-22), `docs/deployment.md` if it lists settings, new `tests/test_gh189_blocking_send.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/models/a2a.py` (`TERMINAL_STATES`, `INTERRUPT_STATES`), the subscription machinery used by `_open_stream`
  - Depends: GH-197
  - Severity: medium
  - Root cause: blocking sends are rejected with -32004/501 since the first commit; the official a2a-python client sends `blocking: true` by default.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/189#issuecomment-6229360257
  - AC: `blocking: true` returns 200 with a Task in a terminal state for a fast tool, artifacts present.
  - AC: A blocking send whose tool raises ToolInterrupt returns 200 with `input-required` (does not hang).
  - AC: A blocking send that outlasts min(task deadline, `blocking_send_max_seconds`) returns 200 with the current non-terminal Task; the worker keeps running and `tasks/get` later shows it terminal. Tests patch the cap; no long real sleeps.
  - AC: A blocking resume waits the same way.
  - AC: Client disconnect during the wait leaks no subscription.
  - AC: `blocking: false` and absent configuration keep today's immediate snapshot.
  - AC: docs/protocols.md updated; CHANGELOG Changed entry with an A2A spec citation and the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/189
  - Reuses: C-019  # Decide when the blocking wait is done with the same TERMINAL_STATES / INTERRUPT_STATES that set_task_status (agent_sdk/agent/runner.py) uses to commit status. Build on the subscription machinery that _open_stream already uses. Do not write a separate state list or a polling loop.
  - SI: SI-5  # Changes the authenticated message:send and resume transport to hold the connection open, and has no SI: field. Add SI-5: the blocking wait must re-check task ownership exactly as the non-blocking path does. Per LRN-193, a client that disconnects mid-wait must release its subscription and stream-budget slot without relying on a generator finally block.

- [ ] `GH-193` A2A resume rejects DataPart answers ‖ group:A4
  - Creates: (modifies `agent_sdk/routes/a2a.py` (`_parse_send` ~422-450 / `_unsupported_input_error` ~368-384, `_resume_or_error` ~510-547), `agent_sdk/example/agent.py` (`confirmed()` also reads `payload`), `docs/protocols.md` (~29-32), new `tests/test_gh193_data_part_resume.py`, `tests/test_gh185_current_identity.py` (one data-path case), `CHANGELOG.md`)
  - Reads: `agent_sdk/auth/context.py` (`ResumeEnvelope`), `agent_sdk/agent/runner.py` (`wait_resume`, ~1419 responseSchema metadata), `agent_sdk/routes/ag_ui.py` (~720-729, AG-UI resume shape), `agent_sdk/contrib/action_gate/gate.py` (`parse_decision`)
  - Depends: GH-189
  - Severity: medium
  - Root cause: the GH-159 non-text check runs in `_parse_send` before the resume branch, and `_resume_or_error` delivers only `_message_text(msg)`, so a structured answer to a `responseSchema` interrupt can never reach `resume_handler`.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/193#issuecomment-6229360550
  - AC: The non-text check runs only on the fresh-task path; fresh messages with a DataPart or FilePart still get -32005/415 (existing GH-159 tests stay green).
  - AC: `message:send` and `message:stream` resuming an interrupt-state task with exactly one DataPart whose `data` is an object (and no other parts) return 200; `resume_handler` receives `{"status": None, "payload": <data>}` inside `ResumeEnvelope`.
  - AC: A text-only resume still delivers a plain `str`.
  - AC: A resume with a FilePart, more than one part mixing kinds, more than one DataPart, or non-object `data` is refused (-32005 for FilePart, -32602 otherwise); the error names the part kind only, never content (SI-2).
  - AC: A DataPart resume on a working or unknown task keeps today's error order and never reveals whether the task exists.
  - AC: `action_gate`: DataPart `{"decision": "approved"}` approves; `{"status": "approved"}` inside data does NOT approve.
  - AC: The resuming caller's identity is still bound after a DataPart resume (GH-185 test case).
  - AC: docs/protocols.md GH-159 text updated to say resumes may carry one DataPart; CHANGELOG Changed entry with the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/193
  - SI: SI-2  # Changes the A2A resume transport and the identity binding on resume (ResumeEnvelope, GH-185 current_identity), and has no SI: field. Add SI-2 (refusal errors name only the part kind, never DataPart content) and SI-5 (a DataPart resume on a working or unknown task must keep today's error order and must not show whether the task exists; the resumer's identity is re-bound).

---
Archived 2026-10-17 by hand after the wave (archive step left it in active/). Released as v0.17.0.
