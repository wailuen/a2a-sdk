# w059 — GitHub issues 204–221 (actionable subset)

Sourced from open issues on wailuen/a2a-sdk (triage 2026-10-22). GH-186 is deferred by ruling and NOT in this wave.
Groups G1–G6 are independent of each other and run in parallel; items inside one group share files and run in order. G7 (GH-209) runs after G1 and G6 finish: it needs GH-204's `MCP_INTERRUPT_SUFFIX` marker and GH-210's changes to the same package and skill file.
Target: 0.18.0 (new public helpers in `agent_sdk.testing`, new `DoneEvent.code`, new card security scheme, one MCP error-code change).

Partial issues: GH-221 (parts 1–3 only), GH-219 (part 3 only), GH-218 (SDK no-redirect part only) and GH-204 (part B, without a retry hint) are in this wave as their actionable subset. The remaining parts are waiting on a ruling. Do NOT implement them, and do not close those issues after release.

`template/` is a checkout of the separate wailuen/a2a-agent-template repo. Only the template mirror paths listed on a todo's Creates: line are in scope (GH-208, GH-211, GH-210, GH-209). They land via commit+push to wailuen/a2a-agent-template (LRN-071, LRN-085); a byte-identical local copy is not delivery (LRN-335). Every other `template/` file (e.g. `template/Dockerfile` for GH-218) stays out of scope.

Each item adds its own entry to `CHANGELOG.md` `[Unreleased]`.

---

## G1 — MCP route (`agent_sdk/routes/mcp.py`)

- [ ] `GH-221` MCP conformance gaps, parts 1–3 (unknown tool error code, POSTed JSON-RPC response, GET session check) ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/mcp.py` (`_handle_tools_call` ~612-632, `_dispatch` ~450, `mcp_post` ~910, `mcp_get` ~945; `_handle_tools_call` docstring ~614 `-32601` wording), `tests/test_mcp_conformance_w10.py` (L-1 test flipped + module docstring), `tests/test_card_mcp_surface_parity.py` (docstring ~5 and comment ~51 `-32601` wording only), `DESIGN.md` (§5.5 `POST /mcp` ~374 and `GET /mcp` ~375 bullets), `docs/protocols.md` (MCP section only), new `tests/test_gh221_mcp_conformance.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/mcp.py` (`mcp_post` session checks ~873-887), `workspace/todos/deferred/v0.9.0-release-conformance-medium-low.md`, `workspace/learning/` LRN-053
  - Severity: low
  - Root cause: (1) `tools/call` for an unknown or tier-2 tool returns `-32601` (method not found); the MCP spec uses `-32602` (invalid params) for an unknown tool name. This reverses wave-10 sweep item L-1 (commit 00a63e6), which was not an owner ruling. (2) A POSTed JSON-RPC response (id + result|error, no method) hits "missing method" `-32600` and, because id is set, gets a 200 error body instead of `202 Accepted`. (3) `mcp_get` never reads `Mcp-Session-Id`.
  - AC: Unknown and tier-2 tools in `tools/call` return JSON-RPC `-32602` with a fixed message that never echoes the requested name; tier-2 still looks exactly like unknown (DESIGN §5.6).
  - AC: `tests/test_mcp_conformance_w10.py` L-1 assertion is flipped to `-32602` (not deleted) and its docstring says why.
  - AC: A POST whose body is a JSON-RPC response (has `id` and `result` or `error`, no `method`) returns HTTP 202 with an empty body; tests for both the result and the error shape.
  - AC: `GET /mcp` with `Mcp-Session-Id` applies the same checks as `mcp_post`: longer than 64 chars → 400; unknown, expired or other-owner session → 404. No header → still 200 SSE (LRN-053, Claude.ai Desktop).
  - AC: CHANGELOG `[Unreleased]` entry under Changed notes the `-32601` → `-32602` wire change for unknown tools.
  - GH: https://github.com/wailuen/a2a-sdk/issues/221
  - SI: SI-5  # The new mcp_get session check (agent_sdk/routes/mcp.py ~945) must run after Depends(require_identity) and guard_origin(request) (~953). It must look sessions up scoped to the caller's identity. An other-owner session must return the exact same 404 body as an unknown or expired one, so the response cannot be used to probe whether someone else's session exists. The new 202 branch for a POSTed JSON-RPC response must sit after the existing mcp_post auth, origin and session checks (~873-888). Otherwise an unknown or other-owner Mcp-Session-Id gets 202 instead of 404.
  - SI: SI-2  # The AC covers the tool name for -32602 only. The new GET checks need the same rule: the 400 (over 64 chars) and 404 bodies must be static, like mcp_delete's ~1071 and mcp_post's {"error": "session not found"}. Never echo the Mcp-Session-Id value in the body or in any new log line. In the 202 response-body branch, never log the posted result/error payload.
  - AC: Regression tests pin SI-5 and SI-2: other-owner GET session → 404 with a body byte-identical to the unknown-session 404; POSTed JSON-RPC response with an unknown or other-owner `Mcp-Session-Id` → 404, not 202; 400/404 bodies never contain the session id value.
  - AC: The written spec matches the new wire behaviour (LRN-425, LRN-313). `DESIGN.md` §5.5: the `POST /mcp` bullet (~374) no longer says it "always responds with `application/json`" and names the 202-empty-body outcome for a POSTed JSON-RPC response; the `GET /mcp` bullet (~375) lists the 400 (session id over 64 chars) and 404 (unknown, expired or other-owner session) outcomes next to the 429. `docs/protocols.md` MCP section says the same and gives `-32602` for an unknown or tier-2 tool. The `_handle_tools_call` docstring (`agent_sdk/routes/mcp.py` ~614) and `tests/test_card_mcp_surface_parity.py` (~5, ~51) say `-32602` invalid-params, not `-32601` method-not-found.
  - AC: `grep -n "always responds with\|32601" DESIGN.md docs/protocols.md agent_sdk/routes/mcp.py tests/test_card_mcp_surface_parity.py` has no hit that describes the old MCP behaviour. Hits about other surfaces stay (e.g. `DESIGN.md` ~296, the unmatched `/v1/*` route `-32601`, and `_METHOD_NOT_FOUND = -32601` at `agent_sdk/routes/mcp.py` ~219, still used for an unknown MCP *method*).
  - AC: The CHANGELOG `[Unreleased]` Changed entry lists `DESIGN.md` §5.5 and `docs/protocols.md` as updated.

- [ ] `GH-218` POST /mcp/ redirects to http:// behind a TLS gateway — SDK part only (serve `/mcp/` without a redirect) ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/mcp.py` (route registration ~123, ~807, ~945, ~1047), new `tests/test_gh218_mcp_trailing_slash.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/app.py` (~757 FastAPI construction, `redirect_slashes`), `agent_sdk/auth/middleware.py` (~57, ~87 PRM selection by path prefix), `agent_sdk/common/limits.py` (`client_ip`)
  - Severity: medium
  - Root cause: The MCP routes are registered at `''` under prefix `/mcp`, and FastAPI keeps `redirect_slashes=True`, so `POST /mcp/` gets a 307 built from the internal (http) scheme. Behind a TLS gateway the client is redirected to `http://`.
  - AC: `POST`, `GET` and `DELETE` on `/mcp/` reach the same handlers as `/mcp` with no 307. Do not turn off `redirect_slashes` app-wide.
  - AC: Tests: `POST /mcp/` `initialize` returns 200 with an `Mcp-Session-Id`; an unauthenticated `POST /mcp/` returns the 401 challenge pointing at the `/mcp` protected-resource metadata; `GET /mcp/` and `DELETE /mcp/` behave like their `/mcp` twins.
  - AC: Do NOT change `template/Dockerfile` or add `--forwarded-allow-ips` anywhere. That part waits on a ruling: `'*'` would break the `AGENT_SDK_TRUSTED_PROXIES` rate-limit trust model.
  - GH: https://github.com/wailuen/a2a-sdk/issues/218
  - SI: SI-5  # Serve /mcp/ for POST, GET and DELETE by adding the trailing-slash path to the SAME endpoint functions, either by stacking decorators or with add_api_route(endpoint=mcp_post, ...). That way Depends(require_identity) and the in-handler guard_origin come along unchanged. Do not use a path-rewriting middleware or Mount placed ahead of auth, and do not add a second handler copy. Test that an unauthenticated POST/GET/DELETE /mcp/ each return 401. The AC only names POST. Also assert that _unauthorized in agent_sdk/auth/middleware.py ~87 still picks the /mcp-suffixed protected-resource metadata URL for /mcp/.
  - AC: Regression tests pin SI-5: unauthenticated `POST`, `GET` and `DELETE` on `/mcp/` each return 401 with the `/mcp` protected-resource metadata URL in `WWW-Authenticate`; `/mcp/` routes use the same endpoint functions as `/mcp` (no middleware rewrite, no handler copy).

- [ ] `GH-204` ToolInterrupt over MCP — part B only: return the tool-authored interrupt message ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/mcp.py` (`_handle_tools_call` ToolInterrupt branch ~647-662; new exported constant `MCP_INTERRUPT_SUFFIX`), `tests/test_rt003_rt004_mcp_error_mapping.py` (~200-215), `CHANGELOG.md`)
  - Reads: `agent_sdk/agent/loop.py` (`ToolInterrupt` ~151-172, InterruptEvent emission ~1734-1750), `agent_sdk/contrib/action_gate/gate.py` (~208-223), `agent_sdk/common/redact.py` (`sanitize_text` ~26, `safe_line_text` ~186, `TITLE_TEXT_MAX_LEN` ~182)
  - Severity: high
  - Root cause: `_handle_tools_call` catches `ToolInterrupt` and returns a fixed "requires interactive confirmation, unsupported over MCP" text, discarding the tool's own `message`. On A2A/AG-UI that message already goes on the wire verbatim, so showing it over MCP adds no new exposure.
  - AC: `isError: true` result whose text is `interrupt.message` followed by a fixed suffix (e.g. "This action needs user input that this connection cannot collect."). An empty message keeps today's fixed text.
  - AC: No retry hint of any kind is added (no new `ToolInterrupt` field). An action_gate tool re-interrupts on every call, so a generic "call again" hint would loop. That option waits on a ruling.
  - AC: The warning log line logs the reason only, never the interrupt message.
  - AC: Test updated: the tool-authored message appears in the text; an empty message falls back to the fixed text; an action_gate interrupt over MCP still returns `isError: true`.
  - AC: No elicitation (part A) work in this wave.
  - GH: https://github.com/wailuen/a2a-sdk/issues/204
  - AC: The fixed suffix is one exported constant, `MCP_INTERRUPT_SUFFIX` in `agent_sdk/routes/mcp.py`, used for both the message-plus-suffix text and the empty-message fallback text, so a client (GH-209's MCP gate) can tell an interrupt result from a tool failure by that marker, not by matching free text.
  - Reuses: C-007  # Log ToolInterrupt.reason only through sanitize_text (agent_sdk/common/redact.py) with its default 64-char cap. reason is a free string the tool writes (loop.py ~162; action_gate passes the caller's own reason, gate.py ~218). Also strip and cap the new wire text with C-007 sanitize_text (explicit max_len) or C-034 safe_line_text (max_len=TITLE_TEXT_MAX_LEN). Do not write a new control-char stripper.
  - SI: SI-2  # (1) The warning log logs the reason only, through C-007 sanitize_text with the default 64-char cap; never raw, never interrupt.message, never the tool arguments. (2) The new wire text (interrupt.message plus MCP_INTERRUPT_SUFFIX) goes through the same control-character strip and a length cap (C-007 sanitize_text with an explicit max_len, or C-034 safe_line_text with TITLE_TEXT_MAX_LEN) before it goes into content[].text. Tool-authored summaries may be built from model-supplied arguments, and a reason='auth' interrupt may carry a sign-in link bound to a task that MCP never creates.
  - AC: Regression test pins SI-2 (test RED before the code, GREEN after): an interrupt message with C0/C1 control characters and longer than the cap comes back in `content[].text` stripped and capped, still ending with the full `MCP_INTERRUPT_SUFFIX` (sanitize and cap the message part, then append the suffix, so the cap never cuts the marker); the captured warning log line contains the sanitized reason and no message text and no tool arguments.

## G2 — AG-UI route (`agent_sdk/routes/ag_ui.py`)

- [ ] `GH-220` RUN_ERROR has no code; successful RUN_FINISHED has no outcome ‖ group:G2
  - Creates: (modifies `agent_sdk/agent/events.py` (`DoneEvent` ~129), `agent_sdk/agent/loop.py` (~1359-1362), `agent_sdk/agent/runner.py` (`DoneEvent(ok=False)` sites ~918, ~1514, ~1555), `agent_sdk/routes/ag_ui.py` (`_RunMapper.run_error`/`run_finished` ~269-286, ~485-490, route RUN_ERROR sites ~674, ~702-745, ~808, ~814), `docs/protocols.md` (§RUN_*), new `tests/test_gh220_agui_run_error_code.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/models/errors.py` (`ErrorCategory` ~17-25), `.claude/agents/ag-ui-advisor.md` (~64-69)
  - Severity: low
  - Root cause: The SDK already sorts errors into kinds (`rate_limited`, `upstream`, `validation`, `timeout`, `budget`, `internal`, `auth`, `not_found`), but `loop.py` keeps only the message in `DoneEvent`, so `RUN_ERROR` carries no `code`. `run_finished()` sets `outcome` only on the interrupt path.
  - AC: `DoneEvent` gains `code: str | None = None`. It is set from `AgentError.category` in `loop.py` and at the `runner.py` failure sites; fixed-string failures get fixed codes (deadline → `timeout`, sealed transcript → `internal`).
  - AC: `RUN_ERROR` includes `code` when set. Route-level RUN_ERRORs use fixed codes from the same `ErrorCategory` vocabulary: malformed body, invalid resume, no user message, non-text part → `validation`; interrupt expired → `not_found`; serialization, internal and stream-ended → `internal`.
  - AC: A successful run's `RUN_FINISHED` carries `outcome: {"type": "success"}`. The interrupt path is unchanged. The locked AG-UI status dual-mode ruling (resume `status` parsing in `gate.py`) is untouched.
  - AC: `code` never echoes client input (SI-2).
  - AC: Tests: a provider rate-limit `AgentError` → `RUN_ERROR.code == "rate_limited"`; an ok run → `RUN_FINISHED.outcome == {"type": "success"}`; a malformed body → `code == "validation"`.
  - AC: `docs/protocols.md` documents the code vocabulary and the always-present outcome.
  - GH: https://github.com/wailuen/a2a-sdk/issues/220

- [ ] `GH-217` self-check aborts its AG-UI run but the server keeps the model turn running ‖ group:G2
  - Creates: (modifies `agent_sdk/routes/ag_ui.py` (`_run` finally ~803-805, `stream` ~813-829), `agent_sdk/routes/a2a.py` (tasks/cancel teardown ~1133-1150 factored into a shared helper), new `tests/test_gh217_agui_disconnect_cancel.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/console/static/selfcheck.js` (~83-172), `workspace/learning/` LRN-193
  - Severity: medium
  - Root cause: The AG-UI worker is a detached asyncio task. On client disconnect the stream only unsubscribes and releases its admission slot, so the model turn and any tool calls run to the end. The console self-check aborts after the first frame, so every self-check burns a full model run.
  - AC: The `tasks/cancel` teardown (worker, background task, resume future, transcript repair, status CANCELED) is moved into one shared helper used by both routes; `tasks/cancel` behavior is unchanged.
  - AC: When the AG-UI SSE stream ends (client disconnect or cancellation) before the terminal frame was sent, the run is cancelled through that helper. Hooked to the response lifecycle, not only the generator `finally` (LRN-193).
  - AC: A run already parked on an interrupt (terminal `RUN_FINISHED` with interrupt outcome sent) is NOT cancelled on disconnect, and resume still works.
  - AC: A2A `message:stream` disconnect still leaves the task running (resubscribe behavior unchanged).
  - AC: Tests: raw ASGI `/ag-ui/run` disconnect after `RUN_STARTED` → worker cancelled, task CANCELED, fake model not called again; disconnect after interrupt → not cancelled; A2A stream disconnect → still running.
  - AC: The A2A send and stream self-check probes still cost a model turn each; that is only documented in the CHANGELOG entry, not changed.
  - GH: https://github.com/wailuen/a2a-sdk/issues/217
  - Reuses: C-019  # The shared cancel helper pulled out of tasks/cancel (agent_sdk/routes/a2a.py ~1133-1160) must keep committing CANCELED through set_task_status (agent_sdk/agent/runner.py). That is the only place that flushes terminal status to the durable store. The AG-UI disconnect path must call the same helper. It must not set record.task.status by hand or call persist_status directly.
  - Reuses: C-018  # The transcript repair step in the shared helper must call repair_dangling_tool_use_safe (agent_sdk/agent/runner.py), with no store argument, exactly as tasks/cancel does today. The C-018 registry entry says any new out-of-loop writer of record.messages MUST use it. The AG-UI disconnect cancel is a new such writer. Do not re-derive the close_dangling_tool_use/bridge_trailing_user fold.
  - SI: SI-5  # The shared teardown helper must take an already identity-scoped TaskRecord. It must never look up a task by raw id itself. tasks/cancel must keep store.get(task_id, identity) (a2a.py ~1110) and its not-found/terminal returns before calling the helper. The AG-UI disconnect path may cancel only the record its own run created under the request identity. Add a test that tasks/cancel on another identity's task still returns task-not-found after the refactor.
  - AC: Regression test pins SI-5: after the refactor, `tasks/cancel` on another identity's task returns task-not-found and leaves that task running; the shared helper's signature takes a `TaskRecord`, not a task id.

## G3 — A2UI capabilities + A2A agent card

- [ ] `GH-213` a2uiClientCapabilities reads 'catalogs' only; supportedCatalogIds is ignored ‖ group:G3
  - Creates: (modifies `agent_sdk/a2ui/translator.py` (`from_metadata` ~82-89), `DESIGN.md` §5.4, `docs/protocols.md`, `workspace/todos/deferred/w051-group-G1-medium-low.md` (close RT-008 and RT-011), new `tests/test_gh213_supported_catalog_ids.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/a2ui/translator.py` (`allows`/`gated` ~112-121), `agent_sdk/routes/a2a.py` (~407-414), `.claude/agents/a2ui-advisor.md` (~191-206, ~638)
  - Severity: medium
  - Root cause: `from_metadata()` reads only `raw["catalogs"]`; when missing it falls back to the Standard catalog, so the GH-180 gate drops domain surfaces for clients that send upstream A2UI's `supportedCatalogIds`. Already flagged and parked as w051 RT-008.
  - AC: When `catalogs` is absent or not a usable list, a non-empty `list[str]` under `supportedCatalogIds` is accepted with the same validation. When both are present, `catalogs` wins.
  - AC: The fail-closed `gated()` default is unchanged: `gated(False, {...supportedCatalogIds...})` still gives tier `none` (LRN-046, LRN-115).
  - AC: Test: A2A message with `metadata.a2uiClientCapabilities = {"supportedCatalogIds": [domain_id]}` plus the extension header → `allows(DomainModel)` is true and the domain surface is emitted.
  - AC: `DESIGN.md` §5.4 and `docs/protocols.md` name both keys; w051 RT-008 and RT-011 marked closed by GH-213.
  - GH: https://github.com/wailuen/a2a-sdk/issues/213

- [ ] `GH-219` agent card gaps — part 3 only: advertise the SDK OAuth server as an oauth2 security scheme ‖ group:G3
  - Creates: (modifies `agent_sdk/routes/agent_card.py` (~164 docstring, ~213-214 `securitySchemes`/`security`), new `tests/test_gh219_agent_card_oauth2.py`, `tests/test_forwarding_integration.py` (~168-173 exact `securitySchemes` check relaxed to a key-set check), `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/oauth.py` (authorization-server metadata ~199-207), `agent_sdk/app.py` (~609-624, ~908), `agent_sdk/auth/middleware.py` (~89, ~110, ~125), `.claude/agents/a2a-advisor.md` (~54-58)
  - Severity: low
  - Root cause: The SDK's own OAuth authorization server is always mounted and its tokens are accepted on `/v1`, and the 401 points at it, but the agent card advertises only the bearer scheme.
  - AC: `securitySchemes.oauth2 = {type: "oauth2", oauth2MetadataUrl: "<base>/.well-known/oauth-authorization-server", flows: {authorizationCode: {authorizationUrl: "<base>/oauth/authorize", tokenUrl: "<base>/oauth/token", scopes: {}}}}` and `security = [{"bearer": []}, {"oauth2": []}]` (either one is enough).
  - AC: No `openIdConnect` scheme, even when `AGENT_SDK_OAUTH_IDP=oidc` (the IdP sits upstream of the SDK's own authorization server).
  - AC: Test: the card URLs match the authorization-server metadata document byte for byte, and the card still validates against the A2A v0.3.0 model.
  - AC: The `agent_card.py` ~164 docstring says the vendor credential key is not a scheme but the SDK OAuth server is.
  - AC: Parts 1 (description fallback), 2 (tags) and 4 (card size) are NOT changed in this wave.
  - GH: https://github.com/wailuen/a2a-sdk/issues/219
  - SI: SI-5  # The new oauth2 scheme advertises the auth surface. Build its URLs from the same configured origin the authorization server uses: OAuthTokenStore.issuer, which equals settings.resolved_base_url (app.py ~611). Never build them from the request Host or X-Forwarded-* headers. Otherwise a spoofed header could point clients at an attacker's authorization endpoint through the cached card. The authenticated extended card (agent_card.py ~249) must advertise the same securitySchemes/security as the public card.
  - AC: Regression tests pin SI-5: a card request with a spoofed `Host` and `X-Forwarded-Host`/`X-Forwarded-Proto` still advertises oauth2 URLs built from `resolved_base_url`; the authenticated extended card's `securitySchemes`/`security` equal the public card's.

## G4 — Admin console test chat (`agent_sdk/console/static/`)

- [ ] `GH-216` interrupt resume always sends {decision: text}, ignoring response_schema ‖ group:G4
  - Creates: (modifies `agent_sdk/console/static/chat.js` (~476-491, ~576-583), new `agent_sdk/console/static/interrupt.js`, modifies `tests/test_card_console.py` (resume-payload pin moved from chat.js to interrupt.js), new `tests/test_gh216_console_interrupt_schema.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/ag_ui.py` (~449-451), `agent_sdk/contrib/action_gate/gate.py` (`DEFAULT_CONFIRM_SCHEMA` ~45-54, `parse_decision` ~123-143)
  - Severity: medium
  - Root cause: The server sends `interrupt.responseSchema`, but the console keeps only the interrupt id and always resumes with `{decision: text}`.
  - AC: The pending interrupt keeps `{interruptId, responseSchema}`. Single-property schema: the typed text is coerced to that property's type (integer, number, boolean, enum). Multi-property schema: a small form. No schema: `{decision: text}`.
  - AC: Bad input (e.g. `abc` for an integer) shows an error in the console, sends nothing, and keeps the pending interrupt.
  - AC: ActionGate still resumes as `{decision: "approved"}` with no special case (its schema is single-field).
  - AC: Tests: `{row_number: integer}` resumed with `2` delivers `{row_number: 2}` to the tool; ActionGate resume is classified APPROVED by `parse_decision`.
  - AC: A2A-mode interrupt handling stays out of scope.
  - GH: https://github.com/wailuen/a2a-sdk/issues/216

- [ ] `GH-215` test chat requests the domain catalog but renders only the 14 Standard Profile types ‖ group:G4
  - Creates: (modifies `agent_sdk/console/static/a2ui.js` (`RENDERERS` ~909-924, fallback ~187-194, fold loop ~95-153, `pointerTokens` ~31-41, list/table renderers ~882-906), `agent_sdk/console/static/chat.js` (~180, ~336-340, ~344-363), new `tests/test_gh215_console_generic_renderer.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/a2ui/translator.py` (~211, ~217), `agent_sdk/a2ui/catalog.py`
  - Severity: medium
  - Root cause: The console advertises every catalog in the card but its renderer table knows only 14 Standard types, so domain components fall to a raw-JSON `<pre>` (the GH-28 interim). Dropping the domain catalog from the request is wrong: since GH-51, A2A no longer sends undeclared domain surfaces.
  - AC: A generic, data-driven renderer for unknown components bound to an object: title from the component name, key/value rows for scalar fields, tables for arrays of objects. No schema endpoint is added. The raw JSON stays available in a collapsible block.
  - AC: Each message's fold step is wrapped in try/catch and pushes a note, so one bad message does not stop later surfaces; `renderA2uiMessages` in `chat.js` is guarded the same way.
  - AC: Relative JSON-Pointer paths are resolved against the component's scope (or rejected with a note), never folded to the model root.
  - AC: Every list/table renderer caps rows with one shared constant and shows an "N more" note.
  - AC: The `loadCatalogIds()` promise is kept and awaited in `sendA2a`/`sendAgui` before capabilities are built.
  - AC: Tests: unknown domain type renders as a card, not `<pre>`; a malformed message mid-array still paints the later surfaces; the row cap applies; the first send carries the domain catalog ids.
  - GH: https://github.com/wailuen/a2a-sdk/issues/215

## G5 — Wave runners (`harness/workflows/wave-cycle.js`, `.claude/workflows/sdk-wave.js`)

- [ ] `GH-208` wave-cycle.js marks a group complete without checking its Creates: outputs ‖ group:G5
  - Creates: (modifies `harness/workflows/wave-cycle.js` (~1038 `completedGroups.add`, ~978-999, ~675-676, ~945-957, ~1245-1251, ~1305-1310, ~423, ~1676), `.claude/workflows/sdk-wave.js` (~1037, ~686, matching sites), `.claude/workflows/wave-cycle.js` (byte-identical sync of the harness copy), `harness/agents/core/planner.md` (~62 HUMAN GATE marker), `harness/skills/wave/SKILL.md` and `harness/skills/todos/SKILL.md` (marker docs), `.claude/agents/core/planner.md` (byte-identical sync of the harness copy), `.claude/skills/todos/SKILL.md` (byte-identical sync of the harness copy), `.claude/skills/wave/SKILL.md` (marker docs), `tests/test_wave_cycle_behaviour.py`, `tests/test_wave_scope_extraction.py` (DECLARED_PATH_SCAN parity for the gate and re-scan), `tests/test_sdk_wave_behaviour.py`, `CHANGELOG.md`, `template/.claude/workflows/wave-cycle.js` (lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step), `template/.claude/agents/core/planner.md` (lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step), `template/.claude/skills/todos/SKILL.md` (lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step), `template/.claude/skills/wave/SKILL.md` (marker paragraph only; lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step))
  - Reads: issue body (prototype diff is against the pre-slim file — re-port by hand, do not apply), commits f9a62ad and 4dc9069
  - Severity: high
  - Root cause: The Implement loop adds every ready group to `completedGroups` as soon as its implementers return. A null implement result only blocks archive; dependents still run on missing work. `groupDeps` comes only from the model's parse with no cross-check, scope is frozen after parse, and there is no human-gate hold.
  - AC: After each tier, one deterministic script checks every concrete `Creates:` path (file exists; acceptance-record verdict PASS with no `[pending`; pattern paths need a match newer than Implement start). A null or malformed result counts every path as missing (fail closed). Failing groups go to `failedGroups` with a deferred `<wave>-group-<label>-incomplete.md` note.
  - AC: Remaining groups whose deps include a failed group are pruned transitively, skipped in unit redteam, and archive is blocked.
  - AC: `wave.groupDeps` is unioned with deps derived deterministically from each todo's `Depends:` line.
  - AC: The `Creates:`/`Modifies:` scope scan re-runs at the top of every unit and phase redteam round; new paths join `group.scope` and `wave.allScope` (used by the archive gate); a null scan fails closed.
  - AC: An explicit `HUMAN GATE` todo marker plus a release line (citing a GitHub issue URL) is documented in `planner.md` and the wave/todos skills; a group with the marker and no release line is held. Free text like `Status: NOT DONE` does not gate.
  - AC: The same changes land in `.claude/workflows/sdk-wave.js`; `.claude/workflows/wave-cycle.js` stays byte-identical to `harness/workflows/wave-cycle.js`.
  - AC: Tests: dependent not dispatched when a `Creates:` path is missing; null gate = all missing; `Depends:`-derived dep added; mid-run scope addition picked up; `Status: NOT DONE` does not gate.
  - AC: The old fail-open model file-existence check (removed in f9a62ad) is not reintroduced.
  - GH: https://github.com/wailuen/a2a-sdk/issues/208
  - AC: The HUMAN GATE marker docs land in every planner/skill copy the SDK runner uses: `.claude/agents/core/planner.md` stays byte-identical to `harness/agents/core/planner.md`, and `.claude/skills/todos/SKILL.md` stays byte-identical to `harness/skills/todos/SKILL.md`; `.claude/skills/wave/SKILL.md` documents the same marker (LRN-208, LRN-324).
  - AC: Template mirrors: `template/.claude/workflows/wave-cycle.js`, `template/.claude/agents/core/planner.md` and `template/.claude/skills/todos/SKILL.md` are byte-identical to their harness copies; `template/.claude/skills/wave/SKILL.md` gets only the marker paragraph (per-repo lines kept, LRN-405). All four are committed and pushed to wailuen/a2a-agent-template as the final step; `tests/test_wave_scope_extraction.py::test_gh164_workflow_copies_are_byte_identical`, `::test_gh164_template_mirror_is_committed_and_pushed` and `tests/test_workflow_sync.py` pass.
  - Reuses: C-037  # The new Creates: deliverable gate decides which paths are 'concrete' and which are 'pattern'. The per-round scope re-scan pulls paths from Creates:/Modifies:. Both must use the existing DECLARED_PATH_SCAN rule: the scope-scan path regex and lockfile/dotfile list already in sdk-wave.js and wave-cycle.js, kept in step with harness/wave_scope.py::_looks_like_path. Do not add a third path classifier in either runner. LRN-180 and LRN-345 record the prose and backtick misses a forked regex brings back. Extend tests/test_wave_scope_extraction.py parity rather than adding a parallel check.
  - Peer-repo: `template/.claude/workflows/wave-cycle.js`  # GH-208 modifies harness/workflows/wave-cycle.js and .claude/workflows/wave-cycle.js but not the template copy. The wave's blanket 'do NOT edit template/' deferral has no ruling issue URL behind it. It is also a hard blocker, not a choice: template/ is checked out (upstream origin/main), so tests/test_wave_scope_extraction.py::test_gh164_workflow_copies_are_byte_identical and ::test_gh164_template_mirror_is_committed_and_pushed, plus tests/test_workflow_sync.py byte-identity, go red the moment the harness copy changes. Lands via commit+push to wailuen/a2a-agent-template per LRN-071/LRN-085; a byte-identical local copy is not delivery (LRN-335).
  - Peer-repo: `template/.claude/agents/core/planner.md`  # Today template planner.md is byte-identical to harness/agents/core/planner.md. Adding the HUMAN GATE marker only to the harness copy makes them drift silently (LRN-314/LRN-208). Downstream agents' planners would never write the marker that their wave-cycle.js copy enforces once the .js mirror lands. Lands via commit+push to wailuen/a2a-agent-template.
  - Peer-repo: `template/.claude/skills/todos/SKILL.md`  # Today the template todos SKILL.md is byte-identical to harness/skills/todos/SKILL.md. The HUMAN GATE marker docs must land there too, or the copies drift (LRN-314). template/.claude/skills/wave/SKILL.md already differs on purpose (per-repo lines, LRN-405), so update only the marker paragraph there, not the whole file. Lands via commit+push to wailuen/a2a-agent-template.

- [ ] `GH-211` redteam findings carry no quoted line, so wave-cycle cannot drop stale findings ‖ group:G5
  - Depends: GH-208 (same files)
  - Creates: (modifies `harness/workflows/wave-cycle.js` (`RT_SCHEMA` ~127-151, `redteamFixLoop` ~1058-1080), `.claude/workflows/sdk-wave.js` (`RT_SCHEMA` ~144 and its fix loop), `.claude/workflows/wave-cycle.js` (sync), `harness/agents/core/redteam.md` (~144, ~218-222), `.claude/agents/core/redteam.md` (~144), `tests/test_wave_cycle_behaviour.py`, `tests/test_sdk_wave_behaviour.py`, new `workspace/learning/LRN-NNN-stale-redteam-findings.md`, `CHANGELOG.md`, `template/.claude/workflows/wave-cycle.js` (lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step), `template/.claude/agents/core/redteam.md` (lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step))
  - Reads: `harness/workflows/wave-cycle.js` (stall check ~436-438, ~1129-1131)
  - Severity: medium
  - Root cause: `RT_SCHEMA` findings have no quoted source line, and `redteam.md` has no stale-finding rule, so the fix loop cannot check a finding against the current file. Stall detection escalates to debug but never drops stale findings.
  - AC: `RT_SCHEMA` (both runners) gains a required `quote` (exact current line text) and `line`.
  - AC: `redteam.md` (harness and `.claude/` copies) wave-cycle output mode requires the quote plus `file:line`, and says never to re-raise a finding whose line no longer exists.
  - AC: Before each fix round, one deterministic script runs `grep -F` for each quote in its file; findings whose quote is gone are dropped, logged as stale, and left out of the blocking count and of "clean". An empty quote or a null script result keeps the finding (fail closed).
  - AC: Tests: a vanished quote is dropped and not blocking; a null check result keeps every finding.
  - AC: A new SDK LRN records the rule (the issue's LRN-001 is the a2a-teamwork agent's record; the SDK's LRN-001 is unrelated).
  - GH: https://github.com/wailuen/a2a-sdk/issues/211
  - AC: Template mirrors: `template/.claude/workflows/wave-cycle.js` stays byte-identical to `harness/workflows/wave-cycle.js` and `template/.claude/agents/core/redteam.md` stays byte-identical to `harness/agents/core/redteam.md`; both are committed and pushed to wailuen/a2a-agent-template as the final step, and the byte-identity and committed-and-pushed tests pass.
  - Peer-repo: `template/.claude/workflows/wave-cycle.js`  # Same blocker as GH-208. The RT_SCHEMA quote/line change and the stale-finding filter edit harness/workflows/wave-cycle.js. The byte-identity and committed-and-pushed tests will fail without the template copy. Lands via commit+push to wailuen/a2a-agent-template per LRN-071/LRN-085.
  - Peer-repo: `template/.claude/agents/core/redteam.md`  # The redteam.md wave-cycle output mode gains a required quote plus file:line and a 'never re-raise a vanished line' rule. Today the template redteam.md is byte-identical to the harness copy. Once the template wave-cycle.js requires `quote` in RT_SCHEMA, downstream redteam agents without the instruction will fail schema validation or emit empty quotes. Empty quotes fail closed, so stale findings would never be dropped. Lands via commit+push to wailuen/a2a-agent-template.

## G6 — Acceptance harness + `agent_sdk.testing`

- [ ] `GH-210` acceptance-api.js fans out every scenario at once with no rate-limit throttle or retry ‖ group:G6
  - Creates: (new `agent_sdk/testing/turns.py` (throttled, retrying A2A + AG-UI turn helper), modifies `agent_sdk/testing/__init__.py`, `harness/workflows/acceptance-api.js` (`buildScenarioPrompt` ~113-174, ~188, ~211-237, pipeline ~295-322), `harness/skills/acceptance/SKILL.md`, `.claude/skills/acceptance/SKILL.md`, new `tests/test_gh210_testing_turns.py`, `CHANGELOG.md`, `template/.claude/workflows/acceptance-api.js` (lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step), `template/.claude/skills/acceptance/SKILL.md` (hunk merge only; lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step), `template/pyproject.toml` (agent-sdk pin, today `@{{SDK_SHA}}`, must resolve to >=0.18.0; same template push))
  - Reads: `agent_sdk/testing/chat.py` (`agui_turn` ~152-169, ~267)
  - Severity: high
  - Root cause: `pipeline()` runs every scenario at once with no cap, and each turn makes one request with no retry, so rate-limited turns are scored 1–2 as agent failures. `agui_turn` appends the user message before the run, so a naive retry would duplicate it.
  - AC: `agent_sdk.testing` gets a turn helper for A2A and AG-UI with a cross-process slot limit (file locks, configurable, default 3) and exponential back-off on HTTP 429, "too many requests" text, failed task, or empty reply, inside a total budget under 600 s.
  - AC: On a failed attempt the AG-UI message list is restored; A2A task/context ids are written only on success.
  - AC: `acceptance-api.js` scenario prompts call the helper instead of the inline httpx/ChatDriver scripts, and a `rate-limited` failure class is excluded from 1–2 scoring.
  - AC: Rate limits are detected by status and text for now (GH-220 adds `RUN_ERROR.code`; using it is optional, not required).
  - AC: Tests: simulated 429 then success is retried and scored on the success; slot limit enforced across processes; message list restored after a failed AG-UI attempt.
  - GH: https://github.com/wailuen/a2a-sdk/issues/210
  - SI: SI-6  # The new agent_sdk/testing/turns.py helper must read the agent API key from the key-file path, as acceptance-api.js does today (TOKEN = Path(keyFile).read_text()). It must never take the key as a CLI argument or an environment variable written by the prompt, and never put it in a /tmp state file. SI-2: retry and back-off log lines and the 'rate-limited' failure record carry only the status code, attempt count and fixed reason text. They never carry the Authorization header, the user query or the raw response body.
  - AC: Regression tests pin SI-6/SI-2: the helper takes a key-file path (no key argument or env var); slot-lock and state files never contain the key; captured retry logs and the rate-limited record contain no Authorization header, user query or response body.
  - AC: Template mirrors: `template/.claude/workflows/acceptance-api.js` is byte-identical to the harness copy (`tests/test_workflow_sync.py` passes); `template/.claude/skills/acceptance/SKILL.md` gets the rate-limited failure class and helper instructions as a hunk (LRN-405); the template agent-sdk pin resolves to >=0.18.0 in the same push; all committed and pushed to wailuen/a2a-agent-template as the final step.
  - Peer-repo: `template/.claude/workflows/acceptance-api.js`  # GH-210 modifies harness/workflows/acceptance-api.js only. tests/test_workflow_sync.py pins harness↔template byte-identity for acceptance-api.js, and template/ is checked out, so it fails without the mirror. The mirror also has a version link: the template prompts will call agent_sdk.testing.turns, which exists only from 0.18.0. The template commit must bump or pin the template's agent-sdk dependency to >=0.18.0 in the same push. Lands via commit+push to wailuen/a2a-agent-template per LRN-071/LRN-085.
  - Peer-repo: `template/.claude/skills/acceptance/SKILL.md`  # The harness and .claude acceptance SKILL.md copies are listed, but not the template copy that downstream agents run (LRN-314; tests/test_rt005_skill_md_multiturn_parity.py already treats it as the third tracked copy). The template copy already differs on purpose, so merge the rate-limited failure class and helper instructions as a hunk, not a whole-file sync (LRN-405). Lands via commit+push to wailuen/a2a-agent-template.

## G7 — MCP tools gate (after G1 and G6)

- [ ] `GH-209` /acceptance has no MCP tools/call gate ‖ group:G7
  - Depends: GH-210 (same package and skill file), GH-204 (`MCP_INTERRUPT_SUFFIX` marker)
  - Creates: (new `agent_sdk/testing/mcp.py` (initialize, paginated `tools/list`, `tools/call`), modifies `agent_sdk/testing/__init__.py`, `harness/skills/acceptance/SKILL.md` (new Phase 1.5), `.claude/skills/acceptance/SKILL.md`, new `tests/test_gh209_testing_mcp.py`, `CHANGELOG.md`, `template/.claude/skills/acceptance/SKILL.md` (Phase 1.5 hunk merge only; lands via commit+push to wailuen/a2a-agent-template; implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step))
  - Reads: `agent_sdk/agent/registry.py` (`sample=` ~457-469, `read_only` / `readOnlyHint` ~462-479), `agent_sdk/routes/admin.py` (tools listing ~540-552), `agent_sdk/routes/mcp.py` (`MCP_INTERRUPT_SUFFIX`, from GH-204)
  - Severity: medium
  - Root cause: Nothing in `/acceptance` calls each tool directly over MCP, so tool failures show up only through judged model conversations.
  - AC: `agent_sdk.testing` gets an MCP client helper (initialize, paginated `tools/list`, `tools/call`) with unit tests.
  - AC: The acceptance skill adds "Phase 1.5 — MCP tools gate" before Phase 2A: `tools/list` checks (count equals registered tier-1 tools, every input field described, no `$ref`/`$defs`, a size budget), then one `tools/call` per tier-1 tool using its `sample=` args. Any `isError: true` not on the documented allow-list stops acceptance before any model run, naming the tool and args.
  - AC: A tier-1 tool with `sample=None` is skipped with a warning (not a failure); how samples are obtained under a service key is documented.
  - AC: Test: a tool returning `isError: true` stops the gate.
  - GH: https://github.com/wailuen/a2a-sdk/issues/209
  - SI: SI-6  # The new agent_sdk/testing/mcp.py client and the Phase 1.5 gate must read the bearer, admin or service key from the key file or credential store path. Never pass it via argv. The required doc 'how samples are obtained under a service key' must not tell people to put the service key in .env or on the command line. The gate's failure output names the tool and its sample= args, but must never include the Authorization header or the raw tools/call error body (SI-2).
  - AC: Regression tests pin SI-6/SI-2: the MCP client takes a key-file or credential-store path (no key argument); the gate's failure output for an `isError: true` tool contains the tool name and `sample=` args but no Authorization header and no raw error body.
  - AC: Template mirror: the Phase 1.5 hunk is merged into `template/.claude/skills/acceptance/SKILL.md` (no whole-file overwrite, LRN-405), states the >=0.18.0 agent-sdk requirement for `agent_sdk.testing.mcp`, and is committed and pushed to wailuen/a2a-agent-template as the final step.
  - AC: An interrupt result (GH-204: `isError: true` whose text ends with `MCP_INTERRUPT_SUFFIX`, imported from `agent_sdk.routes.mcp`, never a copied string or a free-text match) is reported as "needs user input, skipped" with a warning, not a failure, and does not stop the gate.
  - AC: The gate calls `tools/call` only for tools with `read_only=True` (`annotations.readOnlyHint == true` in `tools/list`). A tool without it is skipped with a warning, even when it has a `sample=`, unless the skill's explicit opt-in (documented in Phase 1.5, off by default) names it. A `sample=` on a write tool must never run a real upstream side effect (sending mail, writing a record) on every acceptance run.
  - AC: Tests (RED before the code, GREEN after): an action_gate tool with a `sample=` (marked `read_only=True`, or named in the opt-in), called over MCP, gives the "needs user input, skipped" warning and does not stop the gate; a tool with a `sample=` and no `readOnlyHint` is not called (no `tools/call` sent) and is skipped with a warning; with the opt-in naming it, it is called.
  - Peer-repo: `template/.claude/skills/acceptance/SKILL.md`  # The new 'Phase 1.5 — MCP tools gate' lands in the harness and .claude acceptance SKILL.md only. Downstream agents run the template copy, so the gate never reaches them (LRN-314). Merge the Phase 1.5 hunk into the template copy (no whole-file overwrite, LRN-405), with the same >=0.18.0 agent-sdk version requirement for agent_sdk.testing.mcp. Lands via commit+push to wailuen/a2a-agent-template.

---

Archived 2026-10-23 by hand. The wave's archive gate was blocked by tests red on three template-mirror checks plus a duplicate LRN-435 id. The duplicate was renumbered to LRN-455 by hand. The last unpushed template commit was pushed to wailuen/a2a-agent-template PR #2. The one remaining check (`test_gh164_template_mirror_is_committed_and_pushed`) passes only once PR #2 is merged, which pairs with the 0.18.0 SDK release because the template's acceptance workflow needs `agent_sdk.testing.turns`. Medium/low findings are in `workspace/todos/deferred/w059-*.md`.
