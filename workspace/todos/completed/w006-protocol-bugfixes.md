# w006 — Protocol bug fixes (GH #4–#8)

All 5 items are independent. Run in parallel (group:F).
Target: 0.4.1 patch release.

---

- [x] `P6-00` Fix MCP `Mcp-Protocol-Version` response header on `initialize` (GH #4) ‖ group:F
  - Creates: (modifies `agent_sdk/routes/mcp.py`)
  - Reads: `agent_sdk/routes/mcp.py`
  - Severity: High
  - Root cause: `_negotiated_version(request)` reads the *request* `MCP-Protocol-Version` header. On first `initialize`, the client sends no such header → falls back to `_DEFAULT_PROTOCOL_VERSION = "2025-03-26"` → locked into `base_headers`. But `_handle_initialize` separately reads `params["protocolVersion"]` and correctly returns the negotiated version in the response body.
  - AC: In `mcp_post()`, after `_dispatch`, when `is_initialize and "result" in response`: read `response["result"].get("protocolVersion")` and, if present, override `headers[_PROTOCOL_VERSION_HEADER]` with it before returning the `JSONResponse`. Body and header must match. All existing MCP tests pass. New test: a POST with `params.protocolVersion="2025-06-18"` and no `MCP-Protocol-Version` request header → response header is `2025-06-18`, not `2025-03-26`.

- [x] `P6-01` Add `valueSchema` to `x-agui.customEvents` entries (GH #5) ‖ group:F
  - Creates: (modifies `agent_sdk/routes/agent_card.py`)
  - Reads: `agent_sdk/routes/agent_card.py`, `agent_sdk/agent/events.py`
  - Severity: Medium
  - Root cause: `"customEvents": list(CUSTOM_EVENTS)` at line 91 emits a flat `string[]`. AG-UI CUSTOM event conformance requires each entry to be `{name, valueSchema}`.
  - AC: Change to a list of objects. Schemas derived from `events.py` dataclasses:
    ```python
    _CUSTOM_EVENT_SCHEMAS = [
        {"name": "AGENT_ARTIFACT", "valueSchema": {"type": "object", "properties": {
            "dataType": {"type": "string"}, "toolName": {"type": "string"}, "data": {}}}},
        {"name": "A2UI_UPDATE",    "valueSchema": {"type": "object", "properties": {
            "messages": {"type": "array"}}}},
        {"name": "AGENT_PROGRESS", "valueSchema": {"type": "object", "properties": {
            "message": {"type": "string"}}}},
        {"name": "AGENT_NOTE",     "valueSchema": {"type": "object", "properties": {
            "note": {"type": "string"}}}},
    ]
    ```
    Agent card test: `card["extensions"]["x-agui"]["customEvents"]` is a list of dicts, each with `"name"` and `"valueSchema"` keys. Names unchanged.

- [x] `P6-02` Emit `DataPart` for `ContentModel` artifacts regardless of A2UI capability (GH #6) ‖ group:F
  - Creates: (modifies `agent_sdk/agent/runner.py`)
  - Reads: `agent_sdk/agent/runner.py`, `agent_sdk/a2ui/translator.py`
  - Severity: High
  - Root cause: In `build_artifact()`, the `ContentModel` branch appends a `DataPart` only when `a2ui_messages is not None` — i.e., only when the client has activated the A2UI extension via `X-A2A-Extensions`. When the client uses plain A2A (no extension), `translate()` returns `None` and no `DataPart` is emitted, violating A2A §D3 (structured artifacts must carry a DataPart).
  - AC: For `ContentModel` payloads, ALWAYS emit a raw `DataPart` alongside the `TextPart`. When A2UI IS active, use the A2UI DataPart (current behaviour). When A2UI is NOT active, emit `DataPart(data=model.model_dump(mode="json", by_alias=True, exclude_none=True), metadata={"data_type": event.data_type, "tool_name": event.tool_name})` instead. No 3-part artifacts — exactly 2 parts in both cases. New test: `build_artifact()` with `capabilities.a2ui_enabled=False` returns 2 parts (TextPart + DataPart with raw dump); with `capabilities.a2ui_enabled=True` returns 2 parts (TextPart + A2UI DataPart).

- [x] `P6-03` Emit `resource_metadata` on all 401 responses, not just `/mcp` (GH #7) ‖ group:F
  - Creates: (modifies `agent_sdk/auth/middleware.py`)
  - Reads: `agent_sdk/auth/middleware.py`
  - Severity: Medium
  - Root cause: `_unauthorized()` at line 65–68 checks `request.url.path == "/mcp"` before adding `resource_metadata`. All other routes (A2A `/v1/message:send`, AG-UI run endpoint, admin) return bare `Bearer realm="agent"`, breaking RFC 9728 OAuth discovery for non-MCP clients.
  - AC: Remove the `if/else` path check. Always use `f'Bearer resource_metadata="{runtime.prm_url}"'`. The `realm="agent"` form is retired. New test: a 401 on `/v1/message:send` carries `WWW-Authenticate: Bearer resource_metadata="..."`. Existing MCP 401 test still passes.

- [x] `P6-04` Add `Access-Control-Expose-Headers` to CORS preflight 204 response (GH #8) ‖ group:F
  - Creates: (modifies `agent_sdk/common/cors.py`)
  - Reads: `agent_sdk/common/cors.py`
  - Severity: Medium
  - Root cause: The preflight branch (lines 79–93) builds `response_headers` with `allow-origin`, `allow-methods`, `allow-headers` but omits `access-control-expose-headers`. Some user-agents refuse to expose response headers not listed in a preceding preflight's `Access-Control-Expose-Headers`, silently preventing browsers from reading the `WWW-Authenticate` 401 challenge.
  - AC: Add `(b"access-control-expose-headers", _EXPOSE_HEADERS)` inside the `if origin is not None:` block of the preflight path (same block that adds `allow-origin`). New test: an OPTIONS request from an allowed origin returns `Access-Control-Expose-Headers: WWW-Authenticate, Mcp-Session-Id, X-A2A-Extensions`. Non-preflight response retains the header (existing behaviour unchanged).
