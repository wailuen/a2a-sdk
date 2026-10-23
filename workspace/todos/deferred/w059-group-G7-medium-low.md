# w059 — group G7 deferred medium/low findings

- Wave: w059
- Scope: unit:G7
- Date: 2026-10-22

Non-blocking — these did not block w059's archive. Address opportunistically or fold into a future wave.

## RT-002 (medium) — agent_sdk/testing/mcp.py
[SDK] run_gate calls `client.call_tool(name, args)` (line 205) without a try block. A JSON-RPC error, an HTTP 4xx/5xx (including 429) or a transport error during tools/call raises McpError with fixed text out of run_gate. The tool name, its sample= args and the partial GateResult are all lost. Verified live against build_app(): args that are not a JSON object, and an unknown tool, both end the CLI with only 'FAIL: mcp JSON-RPC error'. This breaks the AC 'stops acceptance ... naming the tool and args'.
- Fix: In run_gate, wrap call_tool in `try/except McpError as exc` and append `f"{shown}: tools/call failed ({exc})"` to failures, then return the result. Before calling, check that each sample is a dict and fail with the tool name when it is not. Add tests for the JSON-RPC-error, HTTP-429 and non-dict-sample paths.
- Codify: A gate that must name the failing item has to catch transport and protocol errors per item, not only at the top level.
- sdkCandidate: true

## RT-003 (medium) — agent_sdk/testing/mcp.py
[SDK] Lines 197-200 use `samples.get(name)`. A tool that is missing from samples.json is handled exactly like an explicit `null` (sample=None): it gets a warning and is skipped. An empty or wrong samples file (for example `{}`, or a typo in a tool name) makes the gate PASS with 0 tools called. Sample keys that match no listed tool are also ignored without any message.
- Fix: Treat 'name not in samples' as a failure ('tool X missing from samples file'), and keep the warning only for an explicit null. Fail on sample keys that are not in tools/list. Add tests for both cases.
- Codify: A missing entry and an explicit 'no sample' must be different states. Otherwise the gate can pass while calling nothing.
- sdkCandidate: true

## RT-004 (medium) — tests/test_gh209_testing_mcp.py
[SDK] Every test uses a hand-written httpx.MockTransport (line 33). The interrupt test sends a hand-written f"... {MCP_INTERRUPT_SUFFIX}" text instead of a real action_gate tool over the SDK's /mcp route, so a server-side change to the wording, sanitizing or capping would leave this test green. There are no tests for: readOnlyHint as the real registry emits it, the Mcp-Session-Id round trip, the SSE response branch (lines 91-93), the JSON-RPC-error path, the pagination cap, or the `_main` CLI output (no capsys check that 'Bearer'/the key never reach stdout).
- Fix: Add an end-to-end test using httpx.ASGITransport(app=agent.build_app()). Use a ToolSet with a read_only tool, a write tool that has a sample=, and a contrib.action_gate tool, all driven through McpClient/run_gate. Add a `_main([...])` test with capsys that checks the output has no key and no raw error body. Add an SSE-response unit test.
- Codify: A client-side marker check needs at least one test against the real producer, not a copy of the producer's string.
- sdkCandidate: true

## RT-005 (medium) — harness/skills/acceptance/SKILL.md
[SDK] Phase 1.5 (line ~189) says to take each tier-1 tool's sample= 'from the @tools.tool(...) decorators already read in Phase 0 step 4'. Step 4 (line 123) captures only name, emits= and docstring, not sample=, tier= or read_only=. Nothing says how to work out `--expected-count <N tier-1 tools>` (which default tier counts, and how to handle tools from contrib or SDK toolsets such as echo/demo_kpis). The agent also has to turn Python sample dicts into JSON by hand. The same gap is in the .claude/ and template/ copies.
- Fix: Amend Phase 0 step 4 in all three copies to also capture sample=, tier= (with its default) and read_only=, and state how to count tier-1 tools. Better: add `python -m agent_sdk.testing.mcp --dump-samples --app src.main:app` (or read entry.decl.sample from the ToolSet) so samples.json and the expected count come from the registry, not from reading source by hand.
- Codify: When a skill phase says 'use data captured in step N', step N must be changed in the same edit to capture that data.
- sdkCandidate: true

## RT-006 (medium) — agent_sdk/testing/mcp.py
[SDK] McpClient._post (lines 69-79) never sends the MCP-Protocol-Version header after initialize, and initialize (line 102) does not record or check the negotiated protocolVersion. MCP 2025-06-18 Transports, 'Protocol Version Header', says the client MUST send it on all later HTTP requests. The SDK server accepts the missing header (GH-200), so the gate never exercises the header path that real clients such as Claude.ai use.
- Fix: Store result['protocolVersion'] from initialize, check that it is one of SUPPORTED_PROTOCOL_VERSIONS, and send `MCP-Protocol-Version: <negotiated>` on every request after initialize, including notifications/initialized.
- sdkCandidate: true

## RT-007 (medium) — agent_sdk/testing/mcp.py
[SDK] Unregistered reusable code is duplicated. This is the third inline SSE `data:` line parser (chat.py:221, turns.py:147, mcp.py:92) and the second bearer key-file reader (turns.py:263, mcp.py:53). McpClient/run_gate are reusable building blocks, but none of them is in workspace/components/README.md.
- Fix: Extract `read_key_file(path) -> str` and `iter_sse_data(text) -> Iterator[str]` into agent_sdk/testing/_util.py and use them from chat.py, turns.py and mcp.py. Register McpClient/run_gate and the shared helpers as C-NNN entries.
- sdkCandidate: false

## RT-008 (low) — agent_sdk/testing/mcp.py
The SSE branch (lines 91-93) takes the last `data:` line as the whole message. It breaks on a multi-line data field (spec-valid SSE). It does not match the response id, so a trailing notification would be read as the result.
- Fix: Split events on blank lines, join multi-line `data:` values with '\n', and pick the JSON-RPC message whose id equals the request id.
- sdkCandidate: false

## RT-009 (low) — agent_sdk/testing/mcp.py
__aexit__ (lines 66-67) closes the HTTP client but never sends DELETE /mcp for the session. Every gate run leaves one session open against the per-identity session cap (GH-201, default 200) until the 30-minute idle timeout.
- Fix: In __aexit__, when self._session is set, send DELETE /mcp with Mcp-Session-Id inside a try that ignores errors, then close the client.
- sdkCandidate: false

## RT-010 (low) — CHANGELOG.md
The GH-204 entry (line 14) says 'Tests: tests/test_gh209_testing_mcp.py'. The GH-204 tests are in tests/test_rt003_rt004_mcp_error_mapping.py (lines ~234-280). test_gh209 only uses the constant.
- Fix: Change the GH-204 Tests pointer to tests/test_rt003_rt004_mcp_error_mapping.py.
- sdkCandidate: false

## RT-011 (low) — agent_sdk/testing/mcp.py
`--expected-count` is optional (line 225), and _check_list skips the count check without a word when it is None (line 155), even though the AC requires 'count equals registered tier-1 tools'. The description check (lines 159-162) looks only at top-level properties, not nested object properties or array items.
- Fix: Make --expected-count required in the CLI, or print a WARN when it is absent. Walk nested `properties` and `items` recursively for the description check.
- sdkCandidate: false

## RT-012 (low) — agent_sdk/testing/mcp.py
SI-1 boundary: line 54 builds an httpx.AsyncClient outside agent_sdk/sources/ and agent_sdk/agent/, the only modules the invariant names. It is the agent's own test client (turns.py and chat.py follow the same pattern), but no exemption for agent_sdk/testing is written down. It also sends the bearer to any --base-url, including a plain http:// address that is not local.
- Fix: Write down an explicit SI-1 exemption for agent_sdk/testing (a client of the agent itself, never an upstream) in DESIGN.md. Refuse http:// base URLs whose host is not loopback.
- sdkCandidate: false

## RT-013 (low) — DESIGN.md
The public module list (DESIGN.md:130 testing/ line) and docs/testing.md do not mention agent_sdk.testing.mcp, McpClient/run_gate, or the `python -m agent_sdk.testing.mcp` CLI. The only documentation is the module docstring and the acceptance skill.
- Fix: Add McpClient/run_gate and the CLI to the DESIGN.md testing/ entry and to docs/testing.md, marked PROVISIONAL.
- sdkCandidate: false
