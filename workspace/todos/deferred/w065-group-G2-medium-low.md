# w065 — deferred medium/low findings (unit:G2)

- Wave: w065
- Scope: unit:G2
- Date: 2026-10-24

Non-blocking — these did not block w065's archive. Address opportunistically or fold into a future wave.

Findings were raised across several redteam rounds; duplicates (same file + same defect) are merged below. Source round IDs are listed per item.

## Medium

### D-01 Gate fails the void-emits result the MCP route deliberately returns
- File: agent_sdk/testing/mcp.py:226 (`return "outputSchema declared but structuredContent is absent"`); agent_sdk/routes/mcp.py ~48-54, ~980-993
- Source: RT-003/RT-004 (several rounds) — sdkCandidate
- Problem: routes/mcp.py returns isError:false, empty text, no structuredContent for an emits tool returning None ("spec-consistent", RT-001/RT-002 ruling). run_gate fails exactly that case (pinned by test_run_gate_output_schema_check[absent]). Probe: tier-1 `emits=KpiCard` tool returning None → `tool maybe: outputSchema declared but structuredContent is absent`. CHANGELOG migration gives no fix path.
- Fix: one ruling, applied both sides. (a) route emits conforming structuredContent or isError for void under outputSchema (MCP 2025-06-18 MUST) and fix the route comment; or (b) gate treats the documented void fold as a warning ("returned no result for its sample="). Record ruling on GH-245, align CHANGELOG/docs/testing.md/DESIGN.md, add a build_app() void-emits test.
- Codify: before a test client enforces a protocol MUST, grep the SDK route for an explicit ruling; gate and route must agree.

### D-02 jsonschema promoted to core runtime dependency; uv.lock stale
- File: pyproject.toml:22 (`"jsonschema>=4.20",`)
- Source: RT-001, RT-004, RT-005 — sdkCandidate
- Problem: only user is the provisional test-only agent_sdk/testing/mcp.py; pulls attrs/referencing/rpds-py into every agent image. pyproject.toml and tests/test_rt001_testing_runtime_deps.py not in any todo Creates/Modifies (LRN-202/LRN-361). `uv lock --check` fails (uv.lock lists jsonschema only under dev).
- Fix: either (a) lazy-import inside `_check_structured`, raise McpError('run_gate outputSchema check needs jsonschema: pip install agent-sdk[testing]') when missing, add `testing` extra, drop from core, teach test_rt001_testing_runtime_deps to accept a declared extra, have acceptance skill install `agent-sdk[testing]`; or (b) keep in core, run `uv lock`, commit uv.lock, drop redundant dev entry (line 37), list pyproject.toml + uv.lock + the test in the GH-245 todo with a reason. Update GH-245 CHANGELOG bullet.
- Codify: a provisional test-only module must not add a core runtime dependency.

### D-03 Item 3/4/5 tests use hand-written fakes instead of build_app() over ASGI (LRN-496)
- File: tests/test_gh237_testing_clients.py:396 (`def _stub_client(tools, call_result):`), :364 (MockTransport McpClient), :440/:455/:465 (A2UI activation MockTransport card)
- Source: RT-002, RT-003, RT-005, RT-007 (several rounds) — sdkCandidate
- Problem: item 4 (non-conforming/absent structuredContent, no echo) uses a stub McpClient; item 3 (MCP-Protocol-Version header) and item 5 (X-A2A-Extensions + a2uiClientCapabilities) use MockTransport servers with a made-up card. Nothing proves the real card/route behave; route changes would go unnoticed.
- Fix: item 4 — real tier-1 tool whose emits model advertises a mismatching type (Field(json_schema_extra=...) or the LRN-477 exclude_none class), run_gate via McpClient over ASGITransport; keep `_check_structured` unit cases as extra only. Item 3 — real app + recording middleware/httpx event hook; initialize + list_tools succeed with header present. Item 5 — `agent_sdk.example.agent.make_agent(...).build_app()` (or emits=KpiCard tool + scripted FakeModelClient) with recording transport; assert card fetched once, POST /v1/message:stream carries X-A2A-Extensions == A2UI_EXTENSION_URI and metadata.a2uiClientCapabilities, response echoes the extension, content_types contains 'kpi_card' / an A2UI DataPart arrives. Negative case: ToolSet with no emits → no extension, no header.
- Codify: any AC test for a testing client drives build_app() over httpx.ASGITransport; stubs/MockTransport may only add to it.

### D-04 Acceptance A2A path declares only the standard catalog
- File: agent_sdk/testing/turns.py:157 (`msg["metadata"] = {"a2uiClientCapabilities": driver._caps}`)
- Source: RT-002 — sdkCandidate
- Problem: `ChatDriver(client)` has no `extra_catalogs`, so GH-180/GH-240 negotiation withholds every domain-catalog surface; domain A2UI over A2A is never exercised.
- Fix: `_a2ui_advertised` returns the extension's `params.supportedCatalogIds`; build driver with `extra_catalogs=<ids minus CATALOG_ID>`. Add build_app() test with a domain-catalog emitting tool asserting the A2UI DataPart arrives over /v1/message:stream.
- Codify: a test client that activates A2UI must declare the catalogs the card advertises.

### D-05 Acceptance skill does not document the new gate stop or `--skills-tool`
- File: harness/skills/acceptance/SKILL.md:213, :223 (run block ~198-201); mirrors .claude/skills/acceptance/SKILL.md and template/.claude/skills/acceptance/SKILL.md
- Source: RT-004, RT-006, RT-008 (several rounds) — sdkCandidate
- Problem: Phase 1.5 step 2 omits "structuredContent absent or not matching outputSchema stops the gate"; run synopsis omits `[--skills-tool]`. Operators cannot classify or fix the new FAIL line.
- Fix: add bullet under step 2 ("A tool with outputSchema whose result has no structuredContent, or one that does not match the schema, fails the gate at once; fix the tool's emits model / return type") and `[--skills-tool]` to the run block. Byte-identical in harness + .claude copies; same hunk in template copy (LRN-314/LRN-395 parity; commit and push only that path).
- Codify: a new gate failure mode in agent_sdk.testing must reach the acceptance skill's failure list in the same change.

### D-06 chat.js role predicate drifted from ChatDriver (C-072 parity)
- File: agent_sdk/console/static/chat.js:617 (`if (json.messageId && typeof json.role === "string") roles.set(...)`), also first-CHUNK path :635
- Source: RT-003 — sdkCandidate
- Problem: ChatDriver records a role only when non-empty; chat.js stores `role: ""`, so that text is dropped by the `!== "assistant"` fold. Console and ChatDriver fold the same stream differently.
- Fix: `typeof json.role === "string" && json.role` on both paths; add node case (START{role:""} + CONTENT folded as assistant) next to test_user_role_message_not_folded.
- Codify: a C-072 role-rule change in chat.py must change chat.js with a mirrored node test row.

### D-07 Template SKILL.md edit (commit 6e8d820) not recorded; contradicts todo AC
- File: template/.claude/skills/acceptance/SKILL.md:210; workspace/todos/active/w065-gh-issues.md:57
- Source: RT-005, RT-008, RT-011 — sdkCandidate
- Problem: AC says the template SKILL.md "is NOT edited", but 6e8d820 edited and pushed it. The content is correct (LRN-314/LRN-395 parity) — the plan is wrong. Not in todo or CHANGELOG, so a later redteam/archive may revert it.
- Fix: do NOT revert. Amend the AC/Modifies list to name the template file with commit 6e8d820; note it in the GH-245 CHANGELOG bullet.

## Low

### D-08 `_a2ui_advertised` crashes on non-object card; hides card-fetch failures
- File: agent_sdk/testing/turns.py:133-135 (`exts = (card.get("capabilities") or {}).get("extensions") or []`)
- Source: RT-004, RT-006, RT-008, RT-009 (several rounds) — sdkCandidate
- Problem: runs outside `_a2a_attempt`'s try; a JSON list card or non-dict `capabilities` raises AttributeError, escaping run_turn (catches only TimeoutError) → traceback instead of the `{ok: False, failureClass, reason}` record. A 429/401/5xx card fetch silently disables A2UI with no log and is not counted as rate-limited.
- Fix: isinstance checks on card, capabilities, extensions (list) → return False. Log fixed text `card fetch failed; A2UI not activated` (status code only); treat 429 as rate-limited or retry. Test with card body `[]` asserting the attempt still posts without the extension.

### D-09 Unresolvable `$ref` in outputSchema crashes run_gate
- File: agent_sdk/testing/mcp.py:228 (`jsonschema.validate(call["structuredContent"], schema)`)
- Source: RT-007 — sdkCandidate
- Problem: only ValidationError/SchemaError caught; a remote `$ref` raises `_WrappedReferencingError` (verified); CLI only catches McpError → traceback.
- Fix: also catch referencing.exceptions.Unresolvable / the jsonschema referencing error; return fixed text 'outputSchema could not be resolved'. Test with a remote `$ref` schema.

### D-10 McpClient accepts unsupported/missing negotiated protocolVersion; header test can't tell negotiated from offered
- File: agent_sdk/testing/mcp.py:119; tests/test_gh237_testing_clients.py:372
- Source: RT-009, RT-010 — sdkCandidate
- Problem: client sends any server-returned value (or its default) as MCP-Protocol-Version; a conformance gate should surface this. Test's offered and negotiated values are both SUPPORTED_PROTOCOL_VERSIONS[0].
- Fix: raise McpError('mcp initialize returned an unsupported protocolVersion') (fixed text) when not a str in SUPPORTED_PROTOCOL_VERSIONS. Add case where server answers an older supported version (e.g. '2025-06-18') and later requests carry it.

### D-11 `_is_builtin_load_skill` duplicates route literals
- File: agent_sdk/testing/mcp.py:183 (`and tool.get("title") == "Load skill"`)
- Source: RT-010, RT-011 — sdkCandidate
- Problem: second copy of `routes/mcp.py::_load_skill_tool` title/annotations/schema; drift makes the gate count the built-in as a domain tool and fail --expected-count.
- Fix: expose constants (e.g. `_LOAD_SKILL_TITLE`, `_LOAD_SKILL_ANNOTATIONS`) or a fixed-shape helper in routes/mcp.py and import them.

### D-12 testing/mcp.py module docstring out of date
- File: agent_sdk/testing/mcp.py:17 (`[--allow-error TOOL]... [--opt-in TOOL]...`)
- Source: RT-007, RT-008, RT-012 — sdkCandidate
- Fix: add `[--skills-tool]`; add a sentence that run_gate excludes only the built-in load_skill (by shape, or by name with skills_tool=True) and validates structuredContent against outputSchema for each called tool.

### D-13 C-072 registry row wrong about agui_resume
- File: workspace/components/README.md:65
- Source: RT-005, RT-007, RT-008, RT-009 — sdkCandidate
- Problem: says agui_resume appends the user message on RUN_FINISHED; it never does (chat.py ~202, ~219-220).
- Fix: "agui_turn appends the user message on any RUN_FINISHED; agui_turn and agui_resume append the assistant message only when the reply is non-empty, each with an id".

### D-14 C-074 registry row points at the wrong file
- File: workspace/components/README.md:67
- Source: RT-005, RT-006, RT-007, RT-010 — sdkCandidate
- Problem: Location says agent_sdk/testing/turns.py (agui_turn); agui_turn lives in agent_sdk/testing/chat.py. Description prose also sits in the Location column (the defect GH-245 item 9 fixed for C-072).
- Fix: move prose to Name column; Location = `agent_sdk/testing/chat.py::ChatDriver.agui_turn / agui_resume (posted messages carry an id, GH-245; called by agent_sdk/testing/turns.py::_agui_attempt) + agent_sdk/console/static/chat.js`.

### D-15 A2AError constants re-declare errors.py literals
- File: agent_sdk/testing/chat.py:43 (`AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED = -32007`)
- Source: RT-011 — sdkCandidate
- Fix: assign each from agent_sdk.models.errors (e.g. `= A2A_AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED`), keep NOT_AUTHENTICATED alias.

### D-16 Cancel-after-first-frame test uses a fixed sleep
- File: tests/test_gh237_testing_clients.py:541 (`await asyncio.sleep(0.2)`)
- Source: RT-012 — sdkCandidate
- Fix: `emit={'text': lambda d: seen.set()}` with an asyncio.Event; `await asyncio.wait_for(seen.wait(), ...)` before `task.cancel()`; assert `msgs == []`.

### D-17 acceptance-api.js onlyIds guard misses partial mismatches
- File: harness/workflows/acceptance-api.js:252
- Source: RT-013 — sdkCandidate
- Problem: `['S-1','S-99']` or `['S-1', 5]` silently drops unmatched ids (same fail-open class as GH-245 item 8).
- Fix: in both byte-identical copies, throw fixed text (e.g. 'acceptance-api: some onlyIds matched no scenario', no echo) when scenarios.length < distinct onlyIds count. Add node mutation case to tests/test_gh131_acceptance_api_args_normalization.py. Commit/push template copy only (LRN-071).

---
Filed 2026-10-25 by /sdk-autoloop cycle 1: verified still-present mediums (and lows sharing a fix) are in #251–#260. Other lows stay here, unfiled.
