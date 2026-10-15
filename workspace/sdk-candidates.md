# SDK issue candidates — w049 (2026-10-15)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GH-171 AC not met: _field_summary puts the optional marker on the type ('b: str|null?') instead of the key ('b?: str|null'), so required_paths(parse_schema(...)) treats every field as required; test hides it, docs and CHANGELOG document the wrong convention.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/a2ui/catalog.py
- Rationale: A2UI catalog fallback schema generation is SDK code shared by every agent's prompt section.

## Candidate 2: GH-173 SI-2 not met: _assert_finite formats the value into its ValueError message, so str(ValidationError) still echoes nan/inf despite hide_input_in_errors=True; tests and CHANGELOG note missing.
- Severity: high
- Component: security
- File: agent_sdk/models/content_types.py
- Rationale: Input-echo leak in SDK content_types base validators affects every agent's error text on A2A/MCP wire.

## Candidate 3: Nullable int fields (CategoryValue.count, FundPerformance.quartile, total_count, etc.) reject nan/inf instead of coercing to None as the #173 ruling requires; _finite_floats only covers float fields and runs after type validation.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Rationale: SDK content_types models and _Wire base validator; ruling covers all nullable numeric fields.

## Candidate 4: build_artifact serializability guard used json.dumps without allow_nan=False, so mutated, model_construct or plain-scalar NaN values still reached the A2A stream as invalid JSON.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py
- Rationale: build_artifact is the SDK runner choke point every artifact passes through.

## Candidate 5: BriefingKpiItem.delta (float | None) still rejects non-finite values instead of coercing to None, contradicting the #173 maintainer ruling with no recorded exception.
- Severity: high
- Component: protocol/a2ui
- File: agent_sdk/models/content_types.py
- Rationale: Built-in SDK content model behavior conflicts with maintainer ruling; wave cannot self-sign an exception.

## Candidate 6: GH-173 new rejection of non-finite values on non-nullable float fields (including every agent's domain ContentModel subclasses) is filed under Fixed, not Breaking with a Migration line; SDK-wide hide_input_in_errors change barely mentioned.
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: SDK release notes must declare breaking behavior that affects downstream agents.

## Candidate 7: GH-172 and GH-173 Breaking entries cite no spec clause or maintainer ruling URL (issue 172 comment 6182565843, issue 173 comment 6182565586).
- Severity: high
- Component: sdk/build
- File: CHANGELOG.md
- Rationale: SDK CHANGELOG authority-citation rule for breaking entries.

## Candidate 8: sse_data now uses allow_nan=False, but AG-UI _parse_body accepted bare NaN; client state {"x":NaN} crashes the stream at STATE_SNAPSHOT (outside try) after RUN_STARTED with no terminal frame.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/common/sse.py
- Rationale: AG-UI route regression in SDK protocol surface; breaks one-terminal-frame rule.

## Candidate 9: Wave changed runner.py, sse.py, mcp.py and three test files that no todo lists in Creates:/Modifies:, so the scope-driven redteam never reviewed their callers.
- Severity: high
- Component: harness/workflow
- File: agent_sdk/agent/runner.py
- Rationale: Wave scope-scan / todo-scope discipline is a harness workflow concern.

## Candidate 10: A2A ingress (a2a.py:428) and MCP ingress accepted bare NaN/Infinity; NaN in message metadata crashes /v1/message:stream at the first sse_data frame with no final:true frame while the task keeps running.
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: A2A route ingress/stream termination is SDK protocol code.

## Candidate 11: routes/a2a.py, routes/oauth.py and new common/json_strict.py were changed/created without appearing on any todo Modifies/Creates line; CHANGELOG lacks file paths and an Added entry for loads_strict; tests/test_a2ui_wire.py listed but untouched.
- Severity: high
- Component: harness/workflow
- File: agent_sdk/routes/a2a.py
- Rationale: Todo scope drift and release scope audit are harness workflow rules.

## Candidate 12: loads_strict only blocks NaN/Infinity literal tokens; overflowing numbers like 1e999 parse to inf, causing HTTP 500 on A2A send and MCP, and crashing AG-UI streams.
- Severity: high
- Component: security
- File: agent_sdk/common/json_strict.py
- Rationale: SDK-wide strict-JSON ingress helper used on every protocol surface; client input can trigger unhandled errors.

## Candidate 13: AG-UI _run() has no serialization guard: STATE_SNAPSHOT is yielded outside try and no frame catches ValueError, so any non-finite value cuts the stream with no RUN_ERROR/RUN_FINISHED.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: AG-UI SDK route violates the terminal-frame invariant.

## Candidate 14: MCP has no non-finite output guard: a NaN artifact gives bare HTTP 500 on POST /mcp, and on /mcp/messages json.dumps(allow_nan=False) raises uncaught so the SSE client never gets a reply; CHANGELOG -32006 claim is false for MCP.
- Severity: high
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py
- Rationale: MCP route in SDK must return tool faults as isError results or JSON-RPC errors.
