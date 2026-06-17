wave: w015
group: A
date: 2026-06-15
round_count: 5
status: budget-exhausted

## Findings

### RT-PARSE-400
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: POST /mcp parse-error and invalid-request responses return HTTP 200 instead of HTTP 400. Lines 453-456 and 458-461 return `JSONResponse(content=_error(...), headers=...)` without a `status_code` argument, so FastAPI defaults to 200. MCP Streamable HTTP 2025-06-18 §3.2.1 says 'the server SHOULD return HTTP 400 status code' for unparseable or non-JSON-RPC payloads. Strict MCP client implementations that check the HTTP status before parsing the body will not see the JSON-RPC error object. The legacy POST /mcp/messages path at lines 685-688 correctly enqueues the error via the SSE channel (202 is correct there), so this only affects the Streamable HTTP POST path.
- fix: Add `status_code=400` to both JSONResponse returns at lines 453-456 and 458-461:
  ```python
  return JSONResponse(
      status_code=400,
      content=_error(None, _PARSE_ERROR, "parse error"),
      headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},
  )
  ```
  and similarly for the INVALID_REQUEST case. Add a test that sends malformed JSON to POST /mcp and asserts HTTP 400.
- codify: MCP POST /mcp parse-error must return HTTP 400 (not 200) — MCP Streamable HTTP §3.2.1 SHOULD; omitting status_code from JSONResponse silently defaults to 200

### RT-DELETE-LEN-GUARD
- severity: low
- file: agent_sdk/routes/mcp.py
- description: DELETE /mcp does not enforce the 64-character cap on the Mcp-Session-Id header, unlike POST /mcp (lines 488-492 cap at 64 chars). An oversized session id sent to DELETE /mcp just falls through to `sessions.get(session_id)` which returns None and the handler exits with 204. The security impact is negligible (the session lookup is a pure dict.get with no side effects), but the defense-in-depth consistency is broken: POST caps it, DELETE does not.
- fix: Add a length guard to `mcp_delete` immediately after the origin check:
  ```python
  if session_id and len(session_id) > 64:
      return Response(status_code=400)
  ```
  This mirrors the guard already present in `mcp_post`.
- sdkCandidate: false

### RT-NOTIFY-TEST-COV
- severity: low
- file: agent_sdk/routes/mcp.py
- description: No test exercises the `notifications/*` dispatch path via POST /mcp (the Streamable HTTP path). The code at line 190 returns None for any method starting with 'notifications/', and line 520-522 converts that to a 202 response. The behavior is correct by inspection but is untested. Claude.ai sends `notifications/initialized` immediately after the initialize handshake, so this path is hit in production. A regression here (e.g. accidentally returning 200 with the request echoed) would break the live connector silently.
- fix: Add a test in test_mcp_conformance_w9.py or test_mcp_rtga_006_007_010.py:
  ```python
  async def test_notifications_initialized_returns_202(client):
      headers = await _mcp_init(client)
      r = await client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, headers=headers)
      assert r.status_code == 202
      assert r.content == b""
  ```
  Also add a variant that sends a notification WITH a fabricated `id` field to confirm 202 is returned regardless.
- sdkCandidate: false

### RT-BATCH-TEST-COV
- severity: low
- file: agent_sdk/routes/mcp.py
- description: No test covers the JSON-RPC batch request path (JSON array body). Line 457 correctly rejects `isinstance(message, dict) == False` with `_INVALID_REQUEST`, returning HTTP 200. Some MCP clients attempt batch requests; the behaviour is correct but untested.
- fix: Add a test:
  ```python
  async def test_batch_request_returns_invalid_request(client):
      r = await client.post("/mcp", content=b'[{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}]', headers={"Content-Type": "application/json"})
      assert r.status_code == 200
      body = r.json()
      assert body["error"]["code"] == -32600
  ```
- sdkCandidate: false

### DOC-DESIGN-MCP-VERSION-DRIFT
- severity: low
- file: DESIGN.md
- description: Two documentation inconsistencies regarding the primary MCP protocol version. First: the pinned conformance table (§1, line 33) correctly states 'MCP | 2025-11-25' as the primary version, but the section heading at §5.5 still reads 'MCP (2025-06-18) + OAuth 2.1', making it appear that 2025-06-18 is the primary implementation. Second: the mcp.py module docstring (line 1) says 'MCP 2025-06-18 Streamable HTTP routes' when the code supports 2025-11-25 as the highest and primary version. These are stale titles from before 2025-11-25 support was added.
- fix: Update DESIGN.md §5.5 heading to 'MCP (2025-11-25) + OAuth 2.1'. Update mcp.py module docstring first line to 'MCP 2025-11-25 Streamable HTTP routes (also accepts 2025-06-18, 2025-03-26).'
- sdkCandidate: false

### DOC-DESIGN-OUTPUT-SCHEMA-MISLEADING
- severity: low
- file: DESIGN.md
- description: DESIGN.md §5.5 describes tools/list as returning 'each tool with inputSchema AND outputSchema' (emphasis on 'and'), implying outputSchema is always present. In reality, outputSchema is only emitted when the tool declares `emits=` (implemented correctly in `_handle_tools_list` lines 303-305). This misleads SDK consumers who may expect all tools to carry an outputSchema.
- fix: Update the sentence in DESIGN.md §5.5 to: 'tools/list — Tier 1 only, each tool with `inputSchema`; `outputSchema` only when the tool declares `emits` (structuredContent is never emitted unclaimed)'.
- sdkCandidate: false

### DOC-DESIGN-NO-MODULE-GLOBAL-AMBIGUOUS
- severity: low
- file: DESIGN.md
- description: DESIGN.md §4.3 instructs domain-card authors to 'register the class (import the module so registration runs at boot — no module-level global)'. The phrase 'no module-level global' is self-contradictory: the example immediately below shows `register_content_type(CompanyProfile)` called at module scope, which IS a module-level statement. The intent appears to be 'do not access the private `_REGISTRY` dict directly', but the wording confusingly prohibits the very pattern it then demonstrates.
- fix: Replace the phrase in DESIGN.md §4.3 with: 'register the class (import the module so registration runs at boot — call `register_content_type()` at module scope; do not manipulate `_REGISTRY` directly)'.
- sdkCandidate: false

## Instruction

Fix remaining findings, then re-run /wave w015.
