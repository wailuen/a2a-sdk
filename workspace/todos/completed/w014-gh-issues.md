# w014 — GitHub issues 32–35 + 38

Sourced from open issues on wailuen/a2a-sdk. Items in group:A are independent.
GH-33 and GH-35 share `oauth.py` and must run as group:B (same agent or sequentially).
Target: v0.5.6.

---

- [ ] `GH-32` POST /v1/tasks/{id}:resubscribe → :subscribe ‖ group:A
  - Creates: (modifies `agent_sdk/routes/a2a.py`)
  - Reads: `agent_sdk/routes/a2a.py`, `docs/protocols.md`
  - Severity: high
  - Root cause: Route decorator at a2a.py:374 registers `/v1/tasks/{task_id}:resubscribe` but
    docs/protocols.md lines 16 and 31, the handler name `tasks_subscribe`, and A2A v0.3.0 §2
    all mandate `:subscribe`. External consumers get 404 on the spec-correct path.
  - AC-1: `@router.post("/v1/tasks/{task_id}:subscribe")` in a2a.py (not :resubscribe)
  - AC-2: Test asserts POST /v1/tasks/{id}:subscribe returns SSE (not 404)
  - GH: https://github.com/wailuen/a2a-sdk/issues/32

- [ ] `GH-34` @tool decorator: add tags= param for semantic capability tags ‖ group:A
  - Creates: (modifies `agent_sdk/agent/registry.py`, `agent_sdk/routes/agent_card.py`)
  - Reads: `agent_sdk/agent/registry.py`, `agent_sdk/routes/agent_card.py`,
    `agent_sdk/models/a2a.py`
  - Severity: high
  - Root cause: `ToolDecl` has no `tags` field; `ToolSet.tool()` accepts no `tags=` kwarg;
    `_skill_for()` sets `AgentSkill.tags = ["tier-N"]` hardcoded. A2A spec §1 defines
    `tags: string[]` as a consumer-facing discoverability field, not an internal routing label.
  - AC-1: `@tool(tier=1, tags=["search", "news"])` flows through `ToolDecl.tags` to
    `AgentSkill.tags` on the card
  - AC-2: Tier-N label moves from `tags` into the existing `x-sdk` dict
  - AC-3: `@tool` calls without `tags=` produce `tags: []` (not `["tier-N"]`) — backwards-
    compatible; `AgentSkill.tags` already has `default_factory=list`
  - AC-4: Test asserts card skill has semantic tags when `tags=` supplied; tier in x-sdk
  - GH: https://github.com/wailuen/a2a-sdk/issues/34

- [ ] `GH-38` TaskStatus missing error field for failed tasks ‖ group:A
  - Creates: (modifies `agent_sdk/models/a2a.py`, `agent_sdk/agent/runner.py`)
  - Reads: `agent_sdk/models/a2a.py`, `agent_sdk/agent/runner.py`,
    `agent_sdk/models/errors.py`
  - Severity: high
  - Root cause: `TaskStatus` has no `error` field. A2A v0.3.0 spec requires terminal tasks
    to include `status.error: {code: int, message: str, data?: any}`. On failure, the SDK
    only sets `status.message` (human-readable Message object). `WireError` with the correct
    shape already exists in `errors.py` but is never wired into `TaskStatus`.
  - AC-1: `TaskStatus` gains `error: WireError | None = None` field in `a2a.py`
  - AC-2: `runner.py` failure paths populate `status.error` with a `WireError` (code from
    `AgentError.a2a_code` when available, else -32603 for internal errors); `status.message`
    still set for human-readable context
  - AC-3: Test asserts a failed task's `status.error` serializes as `{code: int, message: str}`
  - GH: https://github.com/wailuen/a2a-sdk/issues/38

- [ ] `GH-33 + GH-35` WWW-Auth route-aware PRM + AS metadata resource_indicators ‖ group:B
  - Creates: (modifies `agent_sdk/auth/middleware.py`, `agent_sdk/app.py`,
    `agent_sdk/routes/oauth.py`)
  - Reads: `agent_sdk/auth/middleware.py`, `agent_sdk/app.py`, `agent_sdk/routes/oauth.py`
  - Severity: high (GH-33) + medium (GH-35)
  - Root cause GH-33: All protected routes (A2A /v1/*, AG-UI /ag-ui/*) emit the same
    `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"`.
    RFC 9728 §3.1 and RFC 8707 require the resource_metadata URI to identify the accessed
    resource. The bare PRM `/.well-known/oauth-protected-resource` already exists but returns
    `resource="{base_url}/mcp"` — wrong for non-MCP routes. Fix: (1) add a second
    `bare_prm_url` field on `AuthRuntime` pointing to the bare PRM path; (2) change the bare
    PRM handler to return `resource=base_url`; (3) in `_prm_challenge` / `_unauthorized`,
    use `mcp_prm_url` for `/mcp` routes and `bare_prm_url` for all others.
  - Root cause GH-35: AS metadata dict in `oauth_authorization_server` handler omits
    `resource_indicators_supported: True` despite the AS validating the `resource` parameter
    at token time per RFC 8707 §3.1.
  - AC-1 (GH-33): Non-MCP routes (`/v1/`, `/ag-ui/`) emit
    `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource"`
  - AC-2 (GH-33): `GET /.well-known/oauth-protected-resource` returns
    `{"resource": "<base_url>", ...}` (not `<base_url>/mcp`)
  - AC-3 (GH-33): MCP routes (`/mcp`) still emit the path-suffixed MCP PRM (unchanged)
  - AC-4 (GH-35): `GET /.well-known/oauth-authorization-server` response includes
    `"resource_indicators_supported": true`
  - AC-5: `test_http_protocol.py` updated — WWW-Auth assertions per surface
  - GH-33: https://github.com/wailuen/a2a-sdk/issues/33
  - GH-35: https://github.com/wailuen/a2a-sdk/issues/35
