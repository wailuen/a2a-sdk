# Deferred: w022 group:G — budget exhausted

- **Wave ID:** w022
- **Group:** group:G
- **Date:** 2026-06-15
- **Rounds completed:** 5 (budget exhausted)
- **Status:** Findings open — fix then re-run `/wave w022`

---

## Instruction

Fix remaining findings, then re-run `/wave w022`.

---

## Findings

### RT-001 — low — OPEN
**File:** `tests/test_mcp_gh77_absent_version_header.py`

GH-77's fix was extended to the legacy POST /mcp/messages path (mcp.py:706-716) for consistency, but the new test file only exercises the Streamable HTTP path (POST /mcp); the legacy SSE-pair absent-header 400 branch has no integration test, so a future regression there would pass CI silently.

**Fix:** Add an integration test that opens a legacy SSE session via GET /mcp/sse, then POSTs a non-initialize JSON-RPC message to /mcp/messages?session_id=... with no MCP-Protocol-Version header and asserts 400; plus a regression case that an initialize on that path with no header still proceeds.

**SDK candidate:** No

---

### RT-002 — low — OPEN
**File:** `agent_sdk/routes/a2a.py:364`

tasks_get returns A2A_UNSUPPORTED_OPERATION (-32004 -> HTTP 501) when ':' appears in task_id (e.g. a client GETs /v1/tasks/{id}:cancel). DESIGN §5.1 specifies GET /v1/tasks/{id} returns 404 + -32001 for unknown ids; surfacing 501 for what is effectively a routing/method miss is semantically inconsistent with the documented unknown-resource behavior and may confuse consumers that branch on the method->code table.

**Fix:** Return a2a_error(A2A_TASK_NOT_FOUND, 'task not found') (404 + -32001) for the ':'-in-task_id guard, matching the unknown-id contract in DESIGN §5.1, or document the deliberate 501 choice with a spec citation in the handler.

**SDK candidate:** No
