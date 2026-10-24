# w065 — group G3 — deferred medium/low findings

- Wave: w065
- Scope: unit:G3
- Date: 2026-10-24
- Source: every redteam round of unit G3, deduped by file + description

> Non-blocking — these did not block w065's archive. Address opportunistically or fold into a future wave.

All items are sdkCandidate: true.

## Medium

### D-01 MCP POST drops 202 for null-id / id-less error responses (RT-001)
- File: agent_sdk/routes/mcp.py:1102 (`and message.get("id") is not None`)
- Problem: on both POST /mcp and POST /mcp/messages, a client JSON-RPC error response with `id: null` or no id (e.g. `{"jsonrpc":"2.0","id":null,"error":{...}}`) is no longer recognised as a response. The old `message.get("id") is None -> 202` fallback is gone, so it falls into `_dispatch` and gets HTTP 200 with a -32600 "missing method" body (probe confirmed). MCP Streamable HTTP: a POSTed response/notification MUST get 202 with empty body; JSON-RPC 2.0: server never replies to a Response; MCP 2025-11-25 schema makes id optional on error responses. DESIGN.md (POST /mcp bullet) still promises 202.
- Fix: treat any message with no `method` and with `result` or `error` as a response, whatever its id: `return "method" not in message and ("result" in message or "error" in message)`. Tests in tests/test_gh246_mcp_route.py: error response with `id: null` and with no id get 202 + empty body on /mcp, and an empty queue on /mcp/messages.
- Codify: when removing a catch-all fallback (id-is-None -> 202), list every message shape it absorbed (null-id error responses as well as notifications) and pin each with a test before deleting it.

### D-02 GH-246 wire change filed under Fixed, not Breaking (RT-002)
- File: CHANGELOG.md:16
- Problem: GH-246 changes stable-core wire behaviour: a non-notification request with no/null id used to run the tool and get 202, now gets -32600 and the tool does not run; /mcp/messages used to accept any Content-Type, now answers 415. The entry sits under `### Fixed` with an inline `**Migration:**` note, not `### 🔴 Breaking changes` (used for GH-240/GH-241 in 0.21.0). Release step can under-bump the version; integrators scanning only Breaking miss it.
- Fix: add `### 🔴 Breaking changes` under [Unreleased]; list the id-less/null-id -32600 change and the /mcp/messages 415 there with the migration note and ruling URL (https://github.com/wailuen/a2a-sdk/issues/246#issuecomment-6381440418). Keep the rest of GH-246 under Fixed.
- Codify: a wire change that makes a previously accepted request fail (or stop running) is breaking even when a ruling approves it; it goes under Breaking, not Fixed.

### D-03 JSON Content-Type check duplicated three ways, AG-UI case-sensitive (RT-003)
- File: agent_sdk/routes/mcp.py:477 (`def _is_json_content_type`); also agent_sdk/routes/a2a.py:467, agent_sdk/routes/ag_ui.py:633
- Problem: private helper in mcp.py; a2a.py copies the logic inline; ag_ui.py uses a case-sensitive substring test (`"application/json" not in ct`), so `Application/JSON` gets 415 on AG-UI but passes on MCP and A2A. Reusable ingress capability, three copies, no registered component (Dimension 8).
- Fix: move `_is_json_content_type` into agent_sdk/common/body.py as a public helper next to `read_capped_body`; use it in mcp.py, a2a.py, ag_ui.py. Register in workspace/components/README.md (own row or part of C-077). Add an AG-UI case-insensitivity test.

## Low

### D-04 Missing-method error echoes an invalid id verbatim (RT-004)
- File: agent_sdk/routes/mcp.py:501 (`return _error(request_id, _INVALID_REQUEST, "missing method")`)
- Problem: missing-method branch runs before `_valid_request_id`, so an invalid id (object, list, float, bool) is echoed back word for word. Probe: `{"jsonrpc":"2.0","id":{"big":"MARK"}}` returned `"id":{"big":"MARK"}`. GH-246 item 2 intends `id: null`; the echo can be up to the 2 MiB body cap.
- Fix: normalise once at the top of `_dispatch`: `reply_id = request_id if _valid_request_id(request_id) else None`; use reply_id in the missing-method error and every other pre-handler error. Test: hostile object id with no method gets `id: null`.

### D-05 Stale comments after the refactor (RT-005)
- File: agent_sdk/routes/mcp.py:1119, ~:1521
- Problem: line 1119 refers to an `if ct` guard that no longer exists (logic moved into `_is_json_content_type`). In mcp_messages, the `RT-001/RTGA-006: parse the body FIRST ... mirroring mcp_post (lines 451-487)` comment now sits above the new 415 check, not the body read, and cites stale line numbers.
- Fix: reword 1119 to say an absent Content-Type is allowed through by `_is_json_content_type`. In mcp_messages, move the 415 check above the RT-001 comment so it sits on the `read_capped_body`/`loads_strict` block; drop the line-number reference.

### D-06 read_capped_body untested branches (RT-006)
- File: tests/test_gh246_mcp_route.py:85
- Problem: no test for a non-numeric Content-Length (`except ValueError: pass` fallback) or a Content-Length claiming less than the cap while the body streams past it (the lying-header case the module docstring defends against). A change trusting the declared length would pass all current tests.
- Fix: (a) headers `[(b"content-length", b"abc")]` with a body under the cap returns the body; (b) headers `[(b"content-length", b"5")]` with chunks totalling more than the cap raises `BodyTooLarge`, and `served[0]` stays small.
