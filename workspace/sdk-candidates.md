# SDK issue candidates — w055 (2026-10-17)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: RT-001: GH-191 edit left a leftover block of the old stream-drop handler after `await processStream();` (~lines 658-666). chat.js no longer parses (`node --check`: SyntaxError: Unexpected token 'else' at line 658). console.js imports chat.js statically, so the whole admin console fails to load. Fix: delete from `} else {` through the second `await processStream();` and confirm node --check passes on chat.js and console.js.
- Severity: critical
- Component: sdk/console
- File: agent_sdk/console/static/chat.js
- Rationale: Admin console static JS ships inside the SDK (agent_sdk/console); breaks every agent's console.

## Candidate 2: RT-002: GH-191 tests only assert substrings in chat.js source; nothing parses console/static/*.js, so the RT-001 syntax error passed the gate. Fix: add a node --check gate over every agent_sdk/console/static/*.js (copied as .mjs, skip when node absent); ideally move drop handling into retry.js and test behaviour under node.
- Severity: high
- Component: sdk/console
- File: tests/test_gh191_console_retry_policy.py
- Rationale: SDK's own test suite for SDK console code; gap in the SDK test gate, not agent tests.

## Candidate 3: RT-003: [Unreleased] lacks G1 entries for GH-198 (Fixed, _KNOWN_REDIRECT_HOPS / Azure APIM regional hop, ruling URL https://github.com/wailuen/a2a-sdk/issues/198#issuecomment-6229360049), GH-191 (Fixed: no retry on 4xx, Retry-After for 429/503 capped 30s, no re-POST after drop, new retry.js) and GH-195 (Added: ChatDriver.agui_resume, provisional testing API; interrupt emit gets AG-UI interrupt dict).
- Severity: high
- Component: harness/workflow
- File: CHANGELOG.md
- Rationale: SDK release notes missing required entries; wave workflow sign-off did not check CHANGELOG ACs per GH id.

## Candidate 4: RT-001 (G1): GH-195 resume test resumes example publish_note with payload={'decision':'approved'}, which the example confirmed() handler ignores, so the tool returns published:false; test only checks tool_done and fake-model text, so it would pass even if payload never reached resume_handler. docs/testing.md lines 152-157 show the same misleading example. Fix: resume with payload matching responseSchema (status='approved'), assert tool result content (e.g. '"published": true' or new tool_result emit on ChatDriver._run_agui), fix docs example.
- Severity: high
- Component: sdk/build
- File: tests/test_gh195_chatdriver_agui_resume.py
- Rationale: agent_sdk.testing.ChatDriver is an SDK testing API and docs/testing.md is SDK documentation; the test covers SDK behaviour.

## Candidate 5: RT-001 (G2): [Unreleased] has no entries for GH-194 (Changed: LoopPolicies.empty_reply_retry, fixed notice, ruling ...#issuecomment-6229361165), GH-196 (must be under '### 🔴 Breaking changes': ToolInputValidationError on unknown keys for loop, MCP tools/call, admin try-tool, commitments; additionalProperties rule; migration via extra="allow"/allow_extra_args=True; ruling ...#issuecomment-6229360794) and GH-188 (Changed: supportedCatalogIds built from tools' emits, may be [] or omit Standard Profile; new emits param; ruling ...#issuecomment-6229361485).
- Severity: high
- Component: harness/workflow
- File: CHANGELOG.md
- Rationale: SDK release notes incl. a breaking change are missing; parallel wave groups editing CHANGELOG.md each skipped it.

## Candidate 6: RT-001 (G2): GH-196 _declared_argument_keys (~line 330) always treats the Python field name of an aliased field as declared, but pydantic only accepts it with populate_by_name/validate_by_name. Verified: Field(None, alias="sectorCode") called with {"sector":"TECH"} passes the unknown-key check, pydantic drops it, tool runs with sector=None - the exact silent bug GH-196 targets; advertised additionalProperties:false is untrue for that key. Fix: include bare field name only when agent_sdk/agent/reuse.py::_accepts_field_name_alias(model) is true; add a test.
- Severity: high
- Component: sdk/build
- File: agent_sdk/agent/registry.py
- Rationale: SDK ToolSet registry argument validation; affects every agent's tools.

## Candidate 7: RT-002 (G2): LRN-144 Check lists only bridge_context_messages and _final_summary as bridge_trailing_user callers outside run_loop exits; GH-194 adds _empty_reply_retry (~line 562) without amending the LRN. Code is correct but recorded invariant no longer matches. Fix: amend workspace/learning/LRN-144-*.md ## Check to list _empty_reply_retry as an extension of run_loop's no-tool-call exit (one bridge call on notice fallback) and require grep shows only definition + one call site.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: SDK agent loop invariant record; stale invariant will cause future redteam false positives or regressions.

## Candidate 8: RT-001 (G2 loop): GH-194 _empty_reply_retry (~520-528) reuses _summary_request_messages, which appends the GH-155 cap-exit _FINAL_SUMMARY_INSTRUCTION ("You have reached the limit... can call no more tools..."). The retry is on by default and fires when no limit was hit, so the model is told a false premise and replies often claim a limit/incomplete work. Test only checks tool_choice. Fix: add _EMPTY_REPLY_INSTRUCTION, give _summary_request_messages an instruction= param, pass it from _empty_reply_retry, and test the retry request text lacks "reached the limit".
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: SDK agent loop behaviour, default-on, produces misleading user-facing replies for every agent.

## Candidate 9: RT-002 (G2 loop): LRN-202/LRN-293 Check fails. LoopPolicies (exported in __all__) gains public field empty_reply_retry but CHANGELOG has no ### Added line. GH-196 entry lists only registry.py, omitting agent_sdk/agent/loop.py (_VALIDATION_TYPE_PHRASES['unknown_argument'], _unknown_argument_loc, safe_validation_message), docs/tools.md and add-tool skill. GH-194 entry omits the 'only right after a tool result' condition. Fix: add ### Added (LoopPolicies.empty_reply_retry, @tools.tool(allow_extra_args=...), emits param on supported_catalogs()/a2ui_extension()), extend GH-196 file list, reword GH-194.
- Severity: high
- Component: harness/workflow
- File: CHANGELOG.md
- Rationale: SDK public API additions undocumented in release notes.

## Candidate 10: RT-001 (GH-190): No CHANGELOG entry for GH-190. Four new pushNotificationConfigs routes (POST/GET /v1/tasks/{id}/pushNotificationConfigs, GET/DELETE .../{configId}) now return 501 -32003 PushNotificationNotSupported instead of 404 -32601 / 405 -32004, with identity+origin guard, same reply for known/foreign/unknown tasks, body never read. Fix: add Fixed entry naming agent_sdk/routes/a2a.py, docs/protocols.md, tests/test_gh190_push_config_not_supported.py.
- Severity: high
- Component: protocol/a2a
- File: CHANGELOG.md
- Rationale: A2A protocol route behaviour change in agent_sdk/routes shipped unannounced.

## Candidate 11: RT-001 (GH-189): DESIGN.md:272 still says unhonourable blocking:true -> -32004 and the error table row at line 289 lists '-32004 UnsupportedOperation | unsupported blocking', but GH-189 removed that rejection in agent_sdk/routes/a2a.py _config_error and now waits. Fix: rewrite line 272 (wait until terminal or input-required, capped at min(task deadline, AGENT_SDK_BLOCKING_SEND_MAX), return current Task at cap, A2A v0.3.0 §7.1.1), drop 'unsupported blocking' from the -32004 row, add DESIGN.md to GH-189 Changed list in CHANGELOG.md.
- Severity: high
- Component: protocol/a2a
- File: DESIGN.md
- Rationale: SDK design spec contradicts landed A2A route behaviour; future audits will revert it.
