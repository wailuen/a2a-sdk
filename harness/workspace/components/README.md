# Components index

Reusable SDK components referenced by PRD FRs (`Reuses: C-NNN`).

| ID | Component | Location | Status |
|----|-----------|----------|--------|
| C-001 | `ToolEntry` registry + `ToolRegistry.register/get_tool` | `agent_sdk/agent/registry.py` | present |
| C-002 | `EncryptedSqliteStore` credential store | `agent_sdk/credentials/store.py` | present |
| C-003 | OAuth 2.1 routes (authorize/token/register/revoke/discovery) | `agent_sdk/routes/oauth.py` | present |
| C-004 | A2A v0.3.0 routes (`message:send`, `message:stream`, `tasks/{id}`) | `agent_sdk/routes/a2a.py` | present |
| C-005 | AG-UI SSE route (`/ag-ui/run`) | `agent_sdk/routes/ag_ui.py` | present |
| C-006 | MCP routes (Streamable-HTTP + SSE) | `agent_sdk/routes/mcp.py` | present |
| C-007 | A2UI translator | `agent_sdk/a2ui/translator.py` | present |
| C-008 | `SourceAdapter` ABC + `resolver_for_source` | `agent_sdk/sources/__init__.py` | present |
| C-009 | `ChatDriver` multi-turn test driver | `agent_sdk/testing/chat.py` | present |
| C-010 | `FakeModelClient` unit-test model stub | `agent_sdk/testing/fake_model.py` | present |
| C-011 | Admin console + bootstrap flow | `agent_sdk/routes/admin.py` | present |
| C-012 | `api_keys` mint/revoke/hash | `agent_sdk/auth/api_keys.py` | present |
