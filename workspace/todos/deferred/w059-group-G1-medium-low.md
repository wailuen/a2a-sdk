# w059 — group G1 — deferred medium/low findings

- Wave: w059
- Scope: unit:G1
- Date: 2026-10-22

Non-blocking — these did not block w059's archive. Address opportunistically or fold into a future wave.

Findings were collected across every redteam round. Findings that name the same file and the same problem are merged into one entry, and each entry lists the round IDs it came from. All are SDK candidates.

## Medium

### D-01 — Legacy `POST /mcp/messages` answers a POSTed JSON-RPC response
- File: `agent_sdk/routes/mcp.py` (~line 1275; `_is_jsonrpc_response` at ~808)
- Sources: RT-002 (medium), RT-006 (low)
- Problem: the GH-221 rule (a POSTed response gets 202 and is never answered) covers only `mcp_post`. `mcp_messages` passes `{id, result}` to `_dispatch`, which returns `-32600 'missing method'` and queues it on the client's SSE channel under the client's own id. The client then fails its own pending request with that id. JSON-RPC 2.0 forbids replying to a response. The two transports disagree.
- Fix: put `if _is_jsonrpc_response(message): return None` at the top of `_dispatch` (or return 202 early in `mcp_messages` after the session and version checks). Add a legacy test: POST `{id, result}` to `/mcp/messages` and assert nothing is queued.

### D-02 — No test for `GET /mcp` with a valid, caller-owned `Mcp-Session-Id`
- File: `tests/test_gh221_mcp_conformance.py` (~line 108)
- Sources: RT-003 (medium), RT-002 (medium), RT-007 (low)
- Problem: the normal Claude.ai Desktop flow (initialize, then GET with the session id) is not pinned. The new check at mcp.py ~984-1000 could reject live sessions and no test would fail (LRN-053). `test_get_without_session_header_still_streams` only checks "task not done after 0.5s". It never checks status or content type. It also cancels without awaiting, which leaves an orphan stream slot.
- Fix: add a test: initialize, then `async with client.stream("GET", "/mcp", headers={...session id, version})`. Assert 200 and `text/event-stream`, or a caller-owned slot in `_get_streams(app)`. Rewrite the no-header test the same way.
- Codify: when adding a rejection gate in front of a must-succeed endpoint, pin the valid-input path in the same test file.

### D-03 — GH-204 "action_gate interrupt over MCP" test does not use action_gate
- File: `tests/test_rt003_rt004_mcp_error_mapping.py` (~line 274)
- Sources: RT-004 (medium), RT-003 (medium), RT-002 (medium)
- Problem: `test_gh204_action_gate_interrupt_over_mcp_is_error` calls `rt001_interrupt_coroutine_tool`, a plain `ToolInterrupt("confirm", ...)`. The real `agent_sdk.contrib.action_gate` builder (`confirmation_required`, gate.py ~219) also sets `response_schema` and `resume_handler`, and that path is untested over MCP. `test_gh209_testing_mcp.py` only fakes the server reply.
- Fix: register a Tier 1 tool that raises `confirmation_required(summary="Delete invoice INV-7?", ...)`. Assert `isError is True`, the text starts with the summary and ends with `MCP_INTERRUPT_SUFFIX`, there is no resume or retry hint, and `resume_handler` is never called.
- Codify: a test named after an integration must go through that integration's real code path.

### D-04 — `MCP_INTERRUPT_SUFFIX` can be forged by a failure message
- File: `agent_sdk/routes/mcp.py` (~line 667); consumer at `agent_sdk/testing/mcp.py:177`
- Sources: RT-005 (medium)
- Problem: the AgentError branch emits `[category] {message}` verbatim. A failure message that ends with the suffix looks exactly like an interrupt to `text.endswith(MCP_INTERRUPT_SUFFIX)`. The GH-209 gate would then skip a failing tool as "needs user input".
- Fix: only the interrupt branch sets `_meta: {"agent_sdk/interrupt": true}`, and `testing.mcp` checks that. Or strip a trailing suffix from every non-interrupt `isError` text. Add a test with an AgentError message ending in the suffix.

### D-05 — Wire changes from GH-204 and GH-218 not written in DESIGN.md / docs/protocols.md; stale module docstring
- Files: `DESIGN.md` §5.5 (~lines 372-376), `docs/protocols.md` (MCP section), `agent_sdk/routes/mcp.py` module docstring (~line 14), `CHANGELOG.md` (GH-218 entry ~line 18)
- Sources: RT-006 (medium), RT-005 (medium)
- Problem: only GH-221 was documented. Missing: (a) GH-204 — a ToolInterrupt over MCP is `isError: true` with `<sanitized message or fixed fallback, capped at 1024 chars> + ' ' + MCP_INTERRUPT_SUFFIX`, no retry hint; (b) GH-218 — `/mcp/` is served by the same handlers for POST, GET and DELETE, no 307, `redirect_slashes` stays on app-wide, `--forwarded-allow-ips` untouched pending a ruling. The module docstring ("Two outcomes per spec, three here") does not list GET's 400/404/429 or the 202 for POSTed responses (LRN-425, LRN-313).
- Fix: add both items to DESIGN.md §5.5 and docs/protocols.md. Update the docstring. Name both docs in the GH-218 CHANGELOG entry.
- Codify: a new public route alias is protocol behaviour; update DESIGN.md and docs/protocols.md in the same todo and name both in the CHANGELOG.

### D-06 — CHANGELOG GH-204 entry: wrong test file and migration note under "Added"
- File: `CHANGELOG.md` (~lines 13-14)
- Sources: RT-004 (medium), RT-003 (low)
- Problem: "Tests: tests/test_gh209_testing_mcp.py" is wrong; the GH-204 tests are in `tests/test_rt003_rt004_mcp_error_mapping.py`, which [Unreleased] never names. The wire-text change (old fixed text -> message + suffix) carries a migration note but sits under "### Added" (LRN-153, LRN-433).
- Fix: point Tests at `tests/test_rt003_rt004_mcp_error_mapping.py` (test_gh209 may stay as a second reference). Move the wire-text change to Changed/Breaking with its Migration line. Keep only the new constant under Added.
- Codify: reconcile CHANGELOG Tests references with the diff; a migration instruction belongs under Changed/Breaking.

### D-07 — CHANGELOG GH-221 migration note says the session header is required on GET
- File: `CHANGELOG.md` (~line 10)
- Sources: RT-001 (medium)
- Problem: the note says clients "must send a valid `Mcp-Session-Id`" on `GET /mcp`. The code (mcp.py ~985-1000) checks the header only when it is present. DESIGN.md, docs/protocols.md and the tests all pin "no header -> 200 SSE" (LRN-053).
- Fix: reword: "clients that send `Mcp-Session-Id` on `GET /mcp` must send a live id from their own `initialize` (a stale or foreign id now gets 404; a missing header still gets 200 SSE)".
- Codify: a migration note must state the exact wire condition; never write "must send" for a header checked only when present.

## Low

### D-08 — Session-header checks copied three times
- File: `agent_sdk/routes/mcp.py` (~984-1000, ~890-899, ~1106)
- Sources: RT-007 (low)
- Problem: the 64-char -> 400 and `_session_alive` -> 404 checks are inline in `mcp_get`, `mcp_post` and `mcp_delete`. The copies already differ in which `MCP-Protocol-Version` header they return.
- Fix: extract `_session_header_error(request, sessions, owner, headers) -> JSONResponse | None` and call it from `mcp_post` (non-initialize) and `mcp_get`.

### D-09 — Malformed POSTed responses get 202 instead of 400
- File: `agent_sdk/routes/mcp.py` (~line 808)
- Sources: RT-008 (low)
- Problem: `_is_jsonrpc_response` accepts both `result` and `error`, missing or wrong `jsonrpc`, or a non-object `error`. MCP 2025-06-18 Streamable HTTP says the server MUST return an HTTP error such as 400 if it cannot accept the response.
- Fix: require `jsonrpc == "2.0"` and exactly one of `result` / `error` (with `error` a dict); otherwise 400 with a static body. Add tests for both-present and missing-jsonrpc.

### D-10 — Non-str `ToolInterrupt.reason` turns an interrupt into -32603
- File: `agent_sdk/routes/mcp.py` (~line 656)
- Sources: RT-007 (low), RT-006 (low)
- Problem: `sanitize_text(interrupt.reason)` has no `str()`, unlike the message on the next line. A `None`/int/Enum reason raises TypeError in the except block; `_dispatch` returns -32603, and the GH-209 gate cannot see the interrupt.
- Fix: `sanitize_text(str(interrupt.reason))`. Add a test raising `ToolInterrupt(None, "msg")` that asserts `isError` with the suffix.

### D-11 — Tier 2 test returns silently; 404 no-echo check missing
- File: `tests/test_gh221_mcp_conformance.py` (~line 52)
- Sources: RT-009 (low), RT-008 (low), RT-007 (low)
- Problem: `test_tier2_tool_looks_like_unknown` does `if not tier2: return`, so the DESIGN §5.6 criterion goes untested if the example agent (today `agent_sdk/example/agent.py:56`, `:71`) drops its Tier 2 tools. `test_posted_response_unknown_session_is_404` skips the no-echo check.
- Fix: `assert tier2, "fixture must register a tier-2 tool"` or register one in a local ToolSet. Add `assert "0" * 32 not in r.text` to the 404 test.

### D-12 — GH-218 slash tests are too weak
- Files: `tests/test_gh218_mcp_trailing_slash.py` (~line 42), `tests/test_gh221_mcp_conformance.py` (`test_get_slash_reaches_mcp_get`)
- Sources: RT-008 (low, two rounds)
- Problem: `test_delete_slash_matches_delete` passes even if `DELETE /mcp/` removes nothing, because DELETE returns 204 for unknown ids. The GET slash test only checks the 400 bad-version path, not a real SSE open.
- Fix: after `DELETE /mcp/`, assert the session is gone from `_sessions(app)` or a follow-up POST with that id returns 404. Add a happy-path `GET /mcp/` asserting 200 `text/event-stream`.

### D-13 — CHANGELOG GH-221: no "### Changed" entry as the ACs require
- File: `CHANGELOG.md`
- Sources: RT-004 (low)
- Problem: two GH-221 ACs ask for a [Unreleased] "Changed" entry for -32601 -> -32602 that lists DESIGN.md §5.5 and docs/protocols.md. The entry only sits under "### 🔴 Breaking changes".
- Fix: add a one-line `### Changed` entry pointing to the Breaking entry, or record in the todo that Breaking replaces Changed here.

### D-14 — REVIEWS.md still calls -32602 the deviation
- File: `REVIEWS.md` (~line 218)
- Sources: RT-005 (low)
- Problem: the deferred MCP LOW row treats -32602 as wrong. GH-221 made -32602 the spec-correct code and reversed wave-10 L-1 (-32601). REVIEWS.md now contradicts DESIGN.md §5.5 (LRN-118).
- Fix: mark the row superseded by GH-221 (unknown or Tier 2 tool -> -32602 per MCP 2025-06-18 Tools "Error Handling"), or move it to a resolved note.

### D-15 — SI-2 log test cannot catch argument leaks
- File: `tests/test_rt003_rt004_mcp_error_mapping.py` (`gh204_noisy_tool` ~line 97, test ~line 283)
- Sources: RT-009 (low)
- Problem: the tool takes no arguments, so a regression that logs arguments would not be caught.
- Fix: give the tool a `secret: str` argument, call it with "ARGMARK-123", and assert the marker is not in the captured log line.
