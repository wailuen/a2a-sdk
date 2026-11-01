# w070 — deferred non-blocking findings (unit:G1)

- Wave: w070 (GH-224, MCP elicitation SSE answer mode)
- Scope: unit:G1
- Date: 2026-11-01

Non-blocking — these did not block w070's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across all redteam rounds. All are `[SDK]`, sdkCandidate: true.

## Medium

### D-01 SSE answer-mode generator heartbeats forever if the worker dies without a final frame
- File: agent_sdk/routes/mcp.py (~1352-1369, `while True:` / `except Exception:`)
- Problem: `_sse_worker` catches only `Exception`. If a tool body or resume_handler leaks `asyncio.CancelledError` (or any BaseException), no final frame is queued. The generator sends HEARTBEAT forever, the tools/call id never gets a response, and the per-identity stream slot stays held. Confirmed by probe: 0 data events, 29 heartbeats in 1.5 s, `len(_get_streams(app)) == 1`. Breaks AC (transport) "exactly one JSON-RPC response ... then the stream ends" and LRN-363.
- Fix: wait on `{queue.get(), worker}` with `asyncio.wait` + heartbeat timeout; if the worker is done and the queue is empty, yield one fixed -32603 frame (dumps_strict, `_is_writable`/`_error`) and return. Or catch BaseException in `_sse_worker`, queue the -32603 final frame, re-raise CancelledError. Test: tool raising CancelledError -> exactly one -32603 data event, then `len(_get_streams(app)) == 0`.
- Codify: An SSE generator that waits on a worker's hand-off queue must also end the stream when the worker dies without its terminal frame.

### D-02 Result dropped after client disconnect is not logged
- File: agent_sdk/routes/mcp_elicitation.py (~276-291, `CallState.put`)
- Problem: AC (disconnect) phases (a) and (c) require a shielded body's / approved action's result to be "dropped and logged by tool name only". `CallState.put` drops silently; CallState does not hold the tool name. An approved action_gate action can run with no operator trace.
- Fix: in `_sse_worker` (where `params['name']` is known) when `call.disconnected` is set, or in `put()` with the tool name passed into CallState, log e.g. `logger.info('mcp stream result dropped, client gone tool=%s', name)` (tool + phase only, no value, SI-2). Add caplog assertions to tests 27 and 28(a).
- Codify: Every AC "logged by X" clause needs a caplog assertion; a silent drop passes every slot/pending test.

### D-03 Two required fallbacks have no test (LRN-560)
- File: agent_sdk/routes/mcp.py (~1313 `count_for_owner(...) >= _max_streams_per_identity(app)`, the `_MAX_GET_STREAMS` check, and `table.add(...)` ~1242 / `MAX_PENDING_PER_SESSION`)
- Problem: (1) stream budget full -> JSON-mode reply, never 5xx; (2) 8-pending-per-session cap -> in-stream isError with no elicitation/create. Deleting either check leaves all tests green.
- Fix: (a) monkeypatch `_max_streams_per_identity` to 0 (or fill `_get_streams`) -> application/json body equal to EXPECTED_INTERRUPT; (b) pre-fill the session PendingTable with 8 entries -> 9th call's stream has exactly one data event equal to the JSON-mode body and no elicitation/create serialized.

### D-04 Test 28(b) / 29 do not drive a real disconnect race
- File: tests/test_gh224_mcp_elicitation.py (~1060-1108, `validate_then_disconnect`)
- Problem: 28(b) sets `disconnected` and calls drop_call by hand inside a patched validate_content; the real ASGI disconnect comes after the action finished. The generator's disconnect `finally` between Future resolution and the worker's next step is never exercised, and the slot count during the gated action is not asserted. Test 29 (phase d) swaps StreamingResponse for a body-skipping class instead of disconnecting at http.response.start.
- Fix: drive 28(b) with `RawCall.disconnect()` right after the accept POST resolves the Future; block resume_handler on an event, assert `len(_get_streams)==1`, release, then assert the action ran exactly once and `len(_get_streams(app)) == 0`. For 29 use `RawCall(hold_start=True)` + disconnect, or document why not.

### D-05 Top-level title/description copied onto requestedSchema
- File: agent_sdk/routes/mcp_elicitation.py (~150, `_kept_text(flat, out)`)
- Problem: MCP ElicitRequest requestedSchema (2025-06-18, 2025-11-25 schema.ts) allows only type/properties/required (+ $schema in 2025-11-25). Pydantic always emits a model title, so every model-derived form sends an undefined field.
- Fix: keep title/description on properties only. Assert the top-level key set in test_accept_runs_resume_handler / test_converter_enum_optional_and_recursive.
- Codify: Wire shapes sent to an MCP client must use only the fields in that version's schema.ts; Pydantic's model-level title is not a requestedSchema field.

### D-06 No-handler emits tool turns user content into typed structuredContent
- File: agent_sdk/routes/mcp.py (~1279, `if entry.decl.emits_types:`); docs/protocols.md:226
- Problem: with no resume_handler on an emits-declaring tool, raw form content goes through emits coercion and can come back as the tool's typed structuredContent. Not in AC (outcome); contradicts protocols.md:226 ("returned as JSON text"); differs from A2A/AG-UI loop (§5.6 parity). Docs (protocols.md, tools.md) also do not describe the current behaviour.
- Fix: preferred — return a fixed isError for emits tools without a resume_handler. If coercion is kept, get a maintainer ruling and document it in protocols.md and tools.md. Either way add a test where content validates as the emits model.
- Codify: User-typed elicitation content must never become a tool's typed output without passing through tool code.

### D-07 notifications/cancelled ignored for a parked tools/call
- File: agent_sdk/routes/mcp.py (~561, `if method.startswith("notifications/"):`)
- Problem: Streamable HTTP says disconnect SHOULD NOT mean cancel; clients SHOULD send notifications/cancelled. All notifications/* return None, so a cancelled waiting call holds a stream slot and pending entry for up to `mcp_elicitation_timeout_seconds` (300 s).
- Fix: handle notifications/cancelled whose `params.requestId` matches a waiting SSE-mode call from the same session + identity; fail its pending Future with a cancel isError (as session removal does). Add a test.
- Codify: When a route starts parking calls, wire the protocol's explicit cancel channel to the parked call.

### D-08 Single-mode "always application/json" contract statements now false
- Files: agent_sdk/routes/mcp.py:88 (module docstring); docs/protocols.md:248; DESIGN.md:378 and :381; `_get_streams` docstring agent_sdk/routes/mcp.py:405
- Problem: all still say POST /mcp always answers application/json / SSE is GET-only, and the stream-budget lists name only GET /mcp + GET /mcp/sse. protocols.md also omits that a POSTed JSON-RPC response with matching id/session/identity resolves a pending elicitation/create.
- Fix: describe SSE answer mode (the three triggers, one elicitation/create then one response, legacy SSE unchanged, point to `_open_answer_stream`); add POST /mcp SSE answer mode to every budget member list with "falls back to JSON, never 429"; add the response-resolves-elicitation sentence; cite GH-224 + ruling comment.
- Codify: A new response mode on an existing route must update every statement of the old contract (module docstring, DESIGN.md, docs); a wave that reverses DESIGN.md must list it in Modifies.

## Low

### D-09 Accepted content hard-sliced at 8192 chars -> invalid JSON
- File: agent_sdk/routes/mcp.py (~1285-1287, `body[:_ELICIT_CONTENT_MAX_CHARS]`)
- Problem: cut mid-token, no marker, isError False; one-off cap no other tools/call result uses.
- Fix: return a fixed isError when over the cap, or use the shared text cap (C-075 / `_tool_text`) with a visible marker. Never hard-slice JSON.

### D-10 resume_handler errors routed through `_tool_failure` validation branch
- File: agent_sdk/routes/mcp.py (~1293, `return _tool_failure(exc, name, entry, timeout)`)
- Problem: ToolInputValidationError gets rendered against `input_model` (original args, not the resume value). agent/loop.py sends these to the generic branch; AC (outcome) lists only AgentError, TimeoutError, generic.
- Fix: `resumed: bool` flag on `_tool_failure`, or catch explicitly at the call site so it gets the generic "tool execution failed" text.

### D-11 Re-raised ToolInterrupt returns the second interrupt, not JSON-mode's
- File: agent_sdk/routes/mcp.py (~1293, `return _interrupt_result(name, again)`)
- Problem: AC says the same response JSON mode would send; JSON mode sends the first interrupt's isError.
- Fix: return `_interrupt_result(name, interrupt)` and log the re-raise by tool name only; or record the intent in the todo and assert it in test 28(c).

### D-12 SSE-worker catch-all log has no error type or frames
- File: agent_sdk/routes/mcp.py (~1353, `logger.error("mcp stream response failed")`)
- Fix: log `error_type=type(exc).__name__` and `frames=frame_locations(exc)`, never `str(exc)` (SI-2), like `_tool_failure`.

### D-13 Elicitation timeout accepts infinity
- File: agent_sdk/config.py (~288, `default=300.0, gt=0, alias="AGENT_SDK_MCP_ELICITATION_TIMEOUT_SECONDS"`)
- Problem: `inf` parses (verified); `wait_for(future, inf)` never times out; on ASGI spec_version >= 2.4 a dropped client can hold a slot a long time.
- Fix: `allow_inf_nan=False` and an upper bound (e.g. `le=86400`).

### D-14 format date-time accepts plain dates
- File: agent_sdk/routes/mcp_elicitation.py (~163, `datetime.fromisoformat(value)`)
- Problem: Python 3.11+ accepts '2025-01-02' and '20250102' (verified); not RFC 3339 date-time.
- Fix: require a 'T'/space time part (plus offset if needed) before fromisoformat; add a date-only case to test_invalid_accept_content_rejected.

### D-15 Docs omit converter-refused keywords
- File: docs/tools.md:249
- Problem: only nested objects, arrays, $ref, unions listed; converter also refuses pattern, const (single-value Literal), exclusiveMinimum/exclusiveMaximum (Field gt/lt), multipleOf, examples, non-string enums. Authors silently lose elicitation.
- Fix: list them in docs/tools.md and the C-109 registry entry.

### D-16 C-109/C-110 rows out of order
- File: workspace/components/README.md:101
- Fix: move the C-108 row above C-109/C-110.

---

Resolved 2026-11-01: D-01..D-16 all fixed by hand before the v0.26.0 release.
