# w064 — group G2 deferred medium/low findings

- Wave: w064
- Scope: unit:G2
- Date: 2026-10-24

Non-blocking — these did not block w064's archive. Address opportunistically or fold into a future wave.

Findings are deduped by file + description across all redteam rounds (merged duplicates list both round IDs).

## MEDIUM

### RT-002 — `agent_sdk/testing/chat.py:294,306,329` — `role: null` drops reply text [sdkCandidate]
- Quote: `if t == "TEXT_MESSAGE_START" and frame.get("messageId") and "role" in frame:` / `if roles.get(mid, "assistant") == "assistant"`
- Issue: the role filter records a role whenever the `role` key is present, even when null. A START or first CHUNK with `"role": null` then has its text dropped (None != "assistant"). AC: text is dropped only for an explicit non-"assistant" string role. AG-UI Python SDK `TextMessageChunkEvent.role` is Optional/None by default, so producers without exclude_none send `role: null`. Reply becomes "", turns.py (C-055) labels it `empty-reply` and retries. Probe: START{messageId:'a', role:null} + CONTENT 'hi' + RUN_FINISHED -> reply ''.
- Fix: record a role only when `isinstance(role, str) and role`, on both the START path and the first-CHUNK path. Add ROLE_CASES rows with `role: None` on a START and on a first CHUNK, text kept.
- Codify: treat an explicit null in an optional AG-UI field the same as the field being absent; key presence alone is not a recorded value.

### RT-001 / RT-003 — `agent_sdk/testing/mcp.py:173` — gate excludes any tool named `load_skill` [sdkCandidate]
- Quote: `counted = sum(1 for t in tools if t.get("name") != "load_skill")`
- Issue: `load_skill` is reserved only when `skills_dir` is set (agent_sdk/app.py `LOAD_SKILL_TOOL in registry.entries` check). An agent with no skills_dir can register its own tier-1 `load_skill`; the gate leaves it out and fails a correct `--expected-count`. Probe: `_check_list([{name:'load_skill'},{name:'b'}], 2, ...)` -> `['tools/list count 1 != registered tier-1 tools 2']`. The literal also duplicates `LOAD_SKILL_TOOL` (agent_sdk/agent/loop.py) and `_LOAD_SKILL` (routes/mcp.py).
- Fix: exclude only the built-in tool — match its fixed wire shape from routes/mcp.py `_load_skill_tool` (title "Load skill", readOnlyHint True + openWorldHint False, single required `name` string), or export a helper from routes/mcp.py, or add an explicit `skills_tool: bool` / `--skills-tool` option to run_gate and `_check_list`. Use `agent_sdk.agent.loop.LOAD_SKILL_TOOL`. Add a negative test: a domain `load_skill` on an app with no skills_dir is still counted.
- Codify: a rule that skips a reserved name must use the same condition as the reservation (skills_dir set / mcp_skills="tool"), not the bare name.

## LOW

### RT-003 / RT-004 — `tests/test_gh237_testing_clients.py:114,128` — only HTTPStatusError covered for leave-messages-unchanged
- Quote: `async def test_turn_http_error_leaves_messages():` / `with pytest.raises(httpx.HTTPStatusError):`
- Issue: AC lists HTTPStatusError, TransportError, and cancel. No test covers a TransportError or a cancel mid-stream after frames were read.
- Fix: parametrise with a MockTransport handler raising `httpx.ConnectError`, plus a case cancelling the agui_turn task after the first frame. Assert `messages` equals the pre-call snapshot and the exception propagates from `ChatDriver.agui_turn`.

### RT-004 (round 2) — `tests/test_gh237_testing_clients.py:234` — run_gate test checks only the passing direction
- Quote: `res = await run_gate(c, {"real": {"a": "x"}}, expected_count=1)`
- Issue: no check that a real mismatch is still caught with load_skill present; a broken exclusion could pass.
- Fix: assert `run_gate(c, ..., expected_count=2)` fails naming 'tools/list count 1'. Add the RT-001 negative case once fixed.

### RT-005 — `docs/testing.md:76` — load_skill note misplaced [sdkCandidate]
- Quote: ``- MCP: the built-in `load_skill` tool (`mcp_skills="tool"`) is not counted against `--expected-count`. `agent_sdk.testing.mcp.McpTestClient` ...``
- Issue: sentence precedes the McpTestClient intro, names `--expected-count` which the section never introduces, omits `run_gate(expected_count=...)`, and overruns the wrap width. harness/skills/acceptance/SKILL.md (~line 207, "differs from the registered tier-1 count") still does not say load_skill is excluded.
- Fix: move after the McpTestClient / list_tools() / run_gate description, wrap to file width, name both entry points (e.g. 'run_gate(expected_count=...) / `python -m agent_sdk.testing.mcp --expected-count` leave the built-in load_skill tool (mcp_skills="tool") out of the count.'). Add the same note to the gate step in harness/skills/acceptance/SKILL.md (follow-up if out of scope).

### RT-006 — `workspace/components/README.md:65` — C-072 description in Location column [sdkCandidate]
- Quote: `| C-072 | agui_terminal_stream_reader | agent_sdk/testing/chat.py::ChatDriver._run_agui (owns the assistant-role reply filter, ...) | present |`
- Issue: other rows (e.g. C-055, C-056) keep Location for paths and put the description in the Name column; wave workflows reading Location as a path get prose. Also append-on-finish lives in `agui_turn` / `agui_resume`, not `_run_agui`.
- Fix: `| C-072 | agui_terminal_stream_reader (assistant-role reply filter, (finished, reply) run-outcome signal, append-on-finish: ...) | agent_sdk/testing/chat.py::ChatDriver._run_agui + ChatDriver.agui_turn / agui_resume | present |`.

### RT-007 — `CHANGELOG.md:14` — GH-237 entry hides behaviour changes [sdkCandidate]
- Issue: filed under Fixed without a behaviour-change note. (1) Callers passing `--expected-count N+1` to allow for load_skill now fail the gate. (2) Direct `ChatDriver.agui_turn` callers no longer keep the user message in `messages` after RUN_ERROR or an exception. GH-241's entry marks its behaviour change; GH-237's does not.
- Fix: add a short **behaviour change** note: pass `--expected-count` without load_skill; direct agui_turn callers must re-add the query themselves when retrying after a failure.
