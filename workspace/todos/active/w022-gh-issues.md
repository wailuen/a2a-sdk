# w022 — GitHub issues #73–#77

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: 0.5.20.

---

- [ ] `GH-74` ag_ui: A2UI_UPDATE must not fire without client opt-in — make AG-UI transport fail-closed ‖ group:G
  - Modifies: `agent_sdk/routes/ag_ui.py`, `agent_sdk/a2ui/translator.py`
  - Reads: `agent_sdk/routes/ag_ui.py`, `agent_sdk/a2ui/translator.py`
  - Severity: high
  - Root cause: `_capabilities()` in `ag_ui.py:315–318` calls `A2uiCapabilities.from_metadata(None)` when `forwardedProps.a2uiClientCapabilities` is absent, which returns the default `A2uiCapabilities(tier='core')` — fail-open. Every AG-UI client that omits the capability key silently receives A2UI_UPDATE CUSTOM events it never requested. The A2A transport was made fail-closed (requires explicit `X-A2A-Extensions` header); the AG-UI transport was never given the same treatment. The fix must be at the route layer, not inside `from_metadata()`, which may have legitimate callers that want the `core` default.
  - AC:
    - `_capabilities()` in `ag_ui.py` returns `A2uiCapabilities(tier='none')` when `forwardedProps.a2uiClientCapabilities` is absent
    - An AG-UI run request with no `forwardedProps.a2uiClientCapabilities` key produces zero `A2UI_UPDATE` frames in the SSE stream
    - An AG-UI run request with `forwardedProps.a2uiClientCapabilities: {"tier": "core"}` still produces `A2UI_UPDATE` frames
    - `from_metadata()` itself is not changed (preserves existing callers)
    - `A2uiCapabilities.for_custom_emit()` added to `translator.py`: returns self when `tier=='none'`, otherwise returns a `core+extended` caps instance — allows the AG-UI emit path to bypass catalog-membership gating (LRN-049) without changing the A2A DataPart gate; `ag_ui.py` uses this instead of passing `self.capabilities` directly to `translate()`
  - GH: https://github.com/wailuen/a2a-sdk/issues/74

- [ ] `GH-73` agent_card: add urn:agui:run:v1 to capabilities.extensions ‖ group:G
  - Modifies: `agent_sdk/routes/agent_card.py`
  - Reads: `agent_sdk/routes/agent_card.py`
  - Severity: medium
  - Root cause: `build_agent_card()` populates `capabilities.extensions` with only `a2ui_extension()` and optionally `credential_forwarding_extension()`; `urn:agui:run:v1` is absent. A comment at lines 117–121 incorrectly claims `capabilities.extensions` is reserved for A2A-defined extensions, but this prevents AG-UI consumers that perform capability negotiation via the normative URI from discovering the surface. The `x-agui` vendor block is present but is not a substitute.
  - AC:
    - `build_agent_card()` includes `urn:agui:run:v1` in `capabilities.extensions`
    - The misleading comment at lines 117–121 is removed or corrected
    - A unit test asserts the built card's `capabilities.extensions` contains `urn:agui:run:v1`
  - GH: https://github.com/wailuen/a2a-sdk/issues/73

- [ ] `GH-77` mcp: return 400 when MCP-Protocol-Version absent on post-init requests ‖ group:G
  - Modifies: `agent_sdk/routes/mcp.py`
  - Reads: `agent_sdk/routes/mcp.py`
  - Severity: medium
  - Root cause: `_negotiated_version()` at `mcp.py:171–179` returns `_DEFAULT_PROTOCOL_VERSION` (`"2025-03-26"`) when the `MCP-Protocol-Version` header is absent — it never returns `None` for the absent case, only for present-but-unrecognized. The call site at lines 472–479 only branches to HTTP 400 when `version is None AND not is_initialize`, so absent-header post-init requests always silently fall back. MCP spec §10 requires 400 for absent header post-initialization. A comment at lines 74–76 documents the silent fallback as intentional — both code and comment need fixing.
  - AC:
    - `_negotiated_version()` distinguishes absent header (→ sentinel) from present-but-unrecognized (→ `None`)
    - Call site returns HTTP 400 when header is absent on a non-initialize post-init request
    - Comment at lines 74–76 removed or corrected
    - Test: POST to a non-initialize MCP endpoint with no `MCP-Protocol-Version` header → 400
    - Regression test: POST to `initialize` with no `MCP-Protocol-Version` header still proceeds normally
  - GH: https://github.com/wailuen/a2a-sdk/issues/77

- [ ] `GH-75` a2a: rename tasks/:subscribe route to :resubscribe per A2A HTTP+JSON binding ‖ group:G
  - Modifies: `agent_sdk/routes/a2a.py`, `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`
  - Reads: `agent_sdk/routes/a2a.py`, `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`
  - Severity: low
  - Root cause: Route decorator at `a2a.py:400` registers `POST /v1/tasks/{task_id}:subscribe`. The A2A HTTP+JSON binding §5.3 specifies the action suffix must be `:resubscribe`. A spec-conformant consumer sending `tasks/{id}:resubscribe` receives a 404.
  - AC:
    - Route path changed from `/v1/tasks/{task_id}:subscribe` to `/v1/tasks/{task_id}:resubscribe`
    - Handler renamed `tasks_resubscribe` for consistency
    - Any test fixtures referencing `:subscribe` updated to `:resubscribe`
    - **Breaking interface change (TaskStore):** `TaskStore.list_tasks_for_identity()` return type extended from `tuple[list[Task], str | None]` to `tuple[list[Task], str | None, int]`; the third element is the total count of all matching tasks regardless of cursor position. This fixes `totalSize` in `GET /v1/tasks` responses, which previously returned `len(page)` (current page only) instead of the full match count. The abstract method in `store.py`, concrete implementation in `memory.py`, and the sole caller at `a2a.py:345` are all updated together. External `TaskStore` subclass implementors must update their `list_tasks_for_identity` return to include the total count.
    - LRN-048 hardening in `a2a.py`: `_create_task_record` and `_resume_or_error` now archive a `model_copy` of the inbound `Message` with server-assigned `contextId` rather than mutating the original object, eliminating the contextId mutation side-effect on caller-held references.
  - GH: https://github.com/wailuen/a2a-sdk/issues/75

- [ ] `GH-76` agent_card: A2UI_UPDATE valueSchema messages missing items definition ‖ group:G
  - Modifies: `agent_sdk/routes/agent_card.py`
  - Reads: `agent_sdk/routes/agent_card.py`
  - Severity: low
  - Root cause: `_CUSTOM_EVENT_SCHEMAS` at `agent_card.py:53` declares `"messages": {"type": "array"}` with no `items` key. JSON Schema without `items` leaves the array element type undeclared; schema-validating AG-UI consumers cannot verify payload structure.
  - AC:
    - `"items": {"type": "object"}` added to the `A2UI_UPDATE` `messages` property in `_CUSTOM_EVENT_SCHEMAS`
    - A unit test asserts the agent card's `A2UI_UPDATE` schema contains `messages.items.type == "object"`
  - GH: https://github.com/wailuen/a2a-sdk/issues/76
