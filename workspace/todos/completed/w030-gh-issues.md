# w030 — GitHub issues 104–105

Sourced from open issues on wailuen/a2a-sdk. Both items required a developer
intent-change decision before being wave-ized (see /gh-review 2026-07-11 triage);
both were approved. All items are independent. Run in parallel (group:G).
Target: 0.5.40.

---

- [x] `GH-104` protocol/a2a: HTTP 404 has no `_A2A_CODE` mapping, defaults to -32603 instead of spec-correct -32601 ‖ group:G
  - Creates: (modifies `agent_sdk/app.py`, `agent_sdk/models/errors.py` (comment-only, A2A_HTTP_STATUS reverse-map doc), `tests/test_a2a_error_envelope.py`)
  - Reads: `agent_sdk/app.py`, `agent_sdk/models/errors.py`, `agent_sdk/routes/mcp.py`, `tests/test_a2a_error_envelope.py`, `workspace/todos/completed/w021-group-group:G-budget-exhausted.md`
  - Severity: high
  - Root cause: `agent_sdk/app.py`'s `_A2A_CODE` HTTP-status→JSON-RPC-error-code table has no `404` entry, so any unmatched `/v1/*` route falls through to the generic `-32603` (Internal Error) default. This was a deliberate w021/RT-003 ruling (2026-06-19) that removed a prior, wrong `404→-32001` mapping and intentionally left 404 unmapped — but never considered `-32601` (Method not found), which is the semantically correct standard JSON-RPC code and is already used identically for MCP method-dispatch misses (`agent_sdk/routes/mcp.py:94`). Developer approved reversing the w021 default in favor of `-32601` (2026-07-11 /gh-review decision).
  - AC: `agent_sdk/app.py`'s `_A2A_CODE` dict maps `404 → -32601`; the rationale comment above it (~lines 630-636) is rewritten to explain the `-32601` mapping and note it supersedes the w021/RT-003 `-32603`-default ruling.
  - AC: `tests/test_a2a_error_envelope.py::test_unknown_v1_route_404_a2a_envelope` asserts `-32601` (not `-32603`) and its docstring is updated to match.
  - AC: grep confirms no other test or `DESIGN.md` passage still asserts `-32603` for an unmatched `/v1/*` route.
  - GH: https://github.com/wailuen/a2a-sdk/issues/104

- [x] `GH-105` mcp: prose-exception ContentModels leak bare-string outputSchema/structuredContent instead of a JSON object ‖ group:G
  - Creates: (modifies `agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/agent_card.py`, `tests/test_mcp_conformance_w9.py`)
  - Reads: `agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/agent_card.py`, `agent_sdk/models/content_types.py`, `tests/test_mcp_conformance_w9.py`
  - Severity: high
  - Root cause: `MarketBriefing` is the SDK's one "prose exception" `ContentModel` (`agent_sdk/models/content_types.py`) — `registry.py:246-264`'s `output_schema()` special-cases it to `{"type": "string"}` and `routes/mcp.py:410-427`'s structuredContent assembly special-cases it to a bare markdown string via `to_markdown()`. Both violate MCP 2025-06-18, which requires `Tool.outputSchema` and `CallToolResult.structuredContent` to always be JSON objects. This bare-string shape is a ratified design decision for AG-UI/A2A (RTGA-001/RTGA-005, DESIGN §4.3) and is locked by `tests/test_mcp_conformance_w9.py::test_sc_c7_market_briefing_structured_content_is_string` — but that ratification never accounted for MCP's stricter object-only requirement. Developer approved: wrap the markdown in an object on the MCP surface only (2026-07-11 /gh-review decision); the AG-UI/A2A bare-string wire contract in `translator.py` is explicitly out of scope and stays untouched.
  - AC: On the MCP surface only, `MarketBriefing`'s `output_schema()` returns `{"type": "object", "properties": {"markdown": {"type": "string"}}, "required": ["markdown"]}` (or equivalent object schema) instead of `{"type": "string"}`.
  - AC: `routes/mcp.py`'s structuredContent assembly sets `structuredContent = {"markdown": artifact.to_markdown()}` for `MarketBriefing` instead of the bare string; the `content[0].text` block continues to carry the raw markdown unchanged.
  - AC: `tests/test_mcp_conformance_w9.py::test_sc_c7_market_briefing_structured_content_is_string` is rewritten to assert the new object shape (rename if the "is_string" name no longer fits).
  - AC: `agent_sdk/a2ui/translator.py` and any AG-UI/A2A-path tests for `MarketBriefing` are unchanged and still pass — confirms the bare-string wire contract is preserved outside MCP.
  - Transitive consequence (RT-004, not a separate AC): `registry.py`'s `output_schema()` is shared by both the MCP surface and `agent_sdk/routes/agent_card.py`'s `_skill_for()` (`x-sdk.outputSchema`), so fixing it for MCP also flips the agent card's advertised `outputSchema` for `MarketBriefing`-emitting tools from `{"type": "string"}` to the object schema. This is intended — the card's `x-sdk.outputSchema` is documentation of the shared registry schema, not a wire contract — and is pinned by `tests/test_mcp_conformance_w9.py::test_rt004_agent_card_output_schema_mirrors_mcp_for_market_briefing`. The A2A DataPart wire shape (`translator.py`) is unaffected and stays a bare markdown string.
  - GH: https://github.com/wailuen/a2a-sdk/issues/105
