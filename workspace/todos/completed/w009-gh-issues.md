# w009 — Protocol conformance sweep (GH #14–#17 + agent-stack-check)

Sourced from: open GitHub issues #14–#17 + 2026-06-15 static `/agent-stack-check` audit.
Goal: zero Critical/High findings and acknowledged Medium/Low punch-list → stack-check OVERALL: COMPLIANT.
All items are independent unless noted. Run in parallel within each group.
Target: v0.5.0 (minor — new capabilities in Group A, E, F).

Groups:
  A — A2A protocol (server)
  B — AG-UI protocol (server)
  C — MCP protocol (server)
  D — A2UI protocol (server)
  E — ChatDriver consumer (testing utility)
  F — Cross-cutting / infrastructure

---

## Group A — A2A protocol (server)

- [ ] `SC-A1` Add bare-Message return path to message/send ‖ group:A
  - Creates: modifies `agent_sdk/routes/a2a.py`, `agent_sdk/agent/agent.py` (or app.py)
  - Reads: `agent_sdk/routes/a2a.py:192-212`, `agent_sdk/agent/runner.py`
  - Severity: high  ← stack-check HIGH; release blocker for v0.5.0
  - Root cause: `message_send()` always creates a Task even for trivial synchronous responses.
    A2A v0.3.0 §2 allows a server to return a bare `Message` directly for quick/synchronous
    responses without task creation. The SDK never exercises this path, so agents built on it
    cannot implement the optional quick-response pattern.
  - Fix: Add an optional `sync_reply: Callable[[Message], str | None] | None` hook to
    `Agent` (or as an `Agent.set_sync_reply(fn)` method). In `message_send()`, call it
    before task creation; if it returns a non-empty string, skip task creation and return:
    ```python
    Message(
        kind="message", role="agent", messageId=uuid4().hex,
        contextId=params.contextId or uuid4().hex,
        parts=[TextPart(kind="text", text=reply_text)]
    )
    ```
    as a JSON response (no task, no stream). The hook receives the incoming Message and
    returns `str | None`; returning `None` falls through to the normal Task path.
  - AC: A test that registers a sync_reply hook returning "pong" for "ping" messages asserts
    `message_send` response is a bare `Message` (kind=="message") with no task created.
    A second test with no hook asserts the normal Task-creation path is unaffected.

- [ ] `GH-15` A2A non-JSON Content-Type returns -32602/HTTP 400 instead of -32005/HTTP 415 ‖ group:A
  - Creates: modifies `agent_sdk/routes/a2a.py`
  - Reads: `agent_sdk/routes/a2a.py:98-116`, `agent_sdk/models/errors.py`, `agent_sdk/common/wire_errors.py`
  - Severity: medium
  - Root cause: `_parse_send()` calls `json.loads()` without first inspecting the Content-Type
    header. Non-JSON Content-Type triggers json.JSONDecodeError → -32602/HTTP 400. A2A v0.3.0
    maps ContentTypeNotSupported to -32005/HTTP 415. All machinery exists; only the guard is
    missing. Add at top of `_parse_send()`:
    ```python
    ct = request.headers.get("content-type", "").split(";")[0].strip()
    if ct != "application/json":
        return a2a_error(A2A_CONTENT_TYPE_NOT_SUPPORTED, "Content-Type must be application/json")
    ```
  - AC: (1) POST with Content-Type: text/plain → HTTP 415 + code -32005.
    (2) Content-Type: application/json; charset=utf-8 → proceeds normally.
  - GH: https://github.com/wailuen/a2a-sdk/issues/15

- [ ] `GH-16` A2A terminal task re-message returns -32001 (TaskNotFound) despite task existing ‖ group:A
  - Creates: modifies `agent_sdk/routes/a2a.py`, `agent_sdk/models/errors.py`
  - Reads: `agent_sdk/routes/a2a.py:155-175`, `agent_sdk/models/errors.py`
  - Severity: medium
  - Root cause: `_resume_or_error()` at a2a.py:161-164 returns A2A_TASK_NOT_FOUND (-32001,
    HTTP 404) for terminal tasks — misleading because GET /v1/tasks/{id} confirms the task
    exists. Add `A2A_TASK_NOT_CANCELABLE = -32002` reuse with message
    "task is terminal and cannot be resumed" (lower risk than a new -32008 code since -32002
    already conveys "task state prevents this operation"). Update _resume_or_error() terminal
    branch and add entry to A2A_HTTP_STATUS (409 Conflict).
  - AC: GET /v1/tasks/{id} → HTTP 200 for the same taskId that POST /v1/message:send rejects
    with -32002/HTTP 409 (not -32001/HTTP 404).
  - GH: https://github.com/wailuen/a2a-sdk/issues/16

- [ ] `SC-A2` A2A plain scalar ArtifactEvent.model emits TextPart only — missing DataPart ‖ group:A
  - Creates: modifies `agent_sdk/agent/runner.py`
  - Reads: `agent_sdk/agent/runner.py:125-135`
  - Severity: medium  ← stack-check A2A D3 / SEAM S2
  - Root cause: In `_build_artifact_parts()` the else-branch at runner.py:130-131 emits only
    `[TextPart(text=str(payload))]` when the artifact is a plain scalar (not ContentModel or
    BaseModel). A2A §3 requires structured artifacts to include a DataPart alongside TextPart.
    Fix: wrap the scalar in `DataPart(kind="data", data={"value": payload},
    metadata={"mimeType": "application/json"})` alongside the existing TextPart.
  - AC: A test that emits an ArtifactEvent with model=42 (int) asserts the artifact has
    two parts: a TextPart with text "42" and a DataPart with data={"value": 42}.

- [ ] `SC-A3` GET /v1/card endpoint lacks require_identity dependency ‖ group:A
  - Creates: modifies `agent_sdk/routes/agent_card.py`
  - Reads: `agent_sdk/routes/agent_card.py:160-172`
  - Severity: low  ← stack-check A2A D2
  - Root cause: `extended_card()` at agent_card.py:164 has no `Depends(require_identity)`.
    It always returns -32007 (supportsAuthenticatedExtendedCard=false) but is publicly
    reachable without auth, which is inconsistent with A2A §1 intent.
    Add `identity: Identity = Depends(require_identity)` parameter to the route.
  - AC: GET /v1/card without Authorization → HTTP 401. GET /v1/card with valid bearer → HTTP
    200 with -32007 body (behavior unchanged, now auth-gated).

- [ ] `SC-A4` Credential-forwarding extension advertised in card but never echoed ‖ group:A
  - Creates: modifies `agent_sdk/routes/a2a.py`
  - Reads: `agent_sdk/routes/a2a.py:58-65`, `agent_sdk/credentials/card.py:27`
  - Severity: low  ← stack-check A2A D6
  - Root cause: `_echo_extensions()` at a2a.py:61-64 only activates the A2UI extension URI.
    The credential-forwarding extension URI (`urn:agent-sdk:credential-forwarding:v1`) is
    declared in the card but a client requesting it via X-A2A-Extensions will never see it
    echoed back, so per D7.11 rules it cannot rely on it being activated.
    Extend `_echo_extensions()` to also activate and echo `CREDENTIAL_FORWARDING_URI` when
    requested.
  - AC: POST /v1/message:send with X-A2A-Extensions: urn:agent-sdk:credential-forwarding:v1
    → response X-A2A-Extensions header includes that URI.

---

## Group B — AG-UI protocol (server)

- [ ] `GH-14` AG-UI resume path emits TOOL_CALL_START→END without required TOOL_CALL_ARGS ‖ group:B
  - Creates: modifies `agent_sdk/routes/ag_ui.py`
  - Reads: `agent_sdk/routes/ag_ui.py:222-233`
  - Severity: medium
  - Root cause: Synthetic resume path (ToolResultEvent with unseen tool_call_id) emits
    TOOL_CALL_START → TOOL_CALL_END with no TOOL_CALL_ARGS in between. AG-UI spec requires
    ≥1 TOOL_CALL_ARGS between START and END. Insert synthetic TOOL_CALL_ARGS with delta="{}"
    between the synthetic START (line 230) and END (line 232).
  - AC: Test feeds ToolResultEvent with unseen tool_call_id through mapper; asserts sequence
    is [TOOL_CALL_START, TOOL_CALL_ARGS(delta="{}"), TOOL_CALL_END, TOOL_CALL_RESULT].
  - GH: https://github.com/wailuen/a2a-sdk/issues/14

- [ ] `GH-17` AG-UI messages[].content array coerced via str() instead of text extraction ‖ group:B
  - Creates: modifies `agent_sdk/routes/ag_ui.py`
  - Reads: `agent_sdk/routes/ag_ui.py:60-85`
  - Severity: medium
  - Root cause: `_fold_history()` at lines 70-72 coerces non-string content via str(content).
    ContentPart[] arrays (used by CopilotKit) produce Python repr instead of extracted text.
    Replace with:
    ```python
    if isinstance(content, list):
        content = "".join(
            p["text"] for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        )
    elif not isinstance(content, str):
        content = str(content)
    ```
  - AC: (a) str → unchanged; (b) [{"type":"text","text":"hi"}] → "hi";
    (c) mixed text+image list → only text joined; (d) no-text list → "".
  - GH: https://github.com/wailuen/a2a-sdk/issues/17

- [ ] `SC-B1` AG-UI SSE stream has no heartbeat — long tool chains silently drop under load balancers ‖ group:B
  - Creates: modifies `agent_sdk/routes/ag_ui.py`
  - Reads: `agent_sdk/routes/ag_ui.py:355-421`, `agent_sdk/common/sse.py:18`
  - Severity: medium  ← stack-check AG-UI C4
  - Root cause: The stream() generator in ag_ui.py has no timeout-based heartbeat. Bedrock
    Converse is non-streaming; a multi-tool chain can produce minutes of SSE silence. Load
    balancers and CDN edges (nginx, ALB, Cloudflare) terminate idle SSE at 30–90s. The
    HEARTBEAT constant (b": ping\n\n") already exists in common/sse.py:18 and is used by
    mcp.py. The AG-UI route needs the same pattern:
    ```python
    try:
        item = await asyncio.wait_for(sub.get(), timeout=15.0)
    except asyncio.TimeoutError:
        yield HEARTBEAT
        continue
    ```
  - AC: Test that pauses the subscription queue for >15s asserts a heartbeat comment frame
    is emitted before the queue is drained.

---

## Group C — MCP protocol (server)

- [ ] `SC-C1` MCP structuredContent silently dropped for non-BaseModel emits ‖ group:C
  - Creates: modifies `agent_sdk/routes/mcp.py`
  - Reads: `agent_sdk/routes/mcp.py:304-320`
  - Severity: medium  ← stack-check MCP D6
  - Root cause: `_handle_tools_call()` at mcp.py:310-315 gates structuredContent on
    `isinstance(artifact, BaseModel)`. A tool declaring `emits=SomeModel` that returns a raw
    dict will advertise outputSchema in tools/list but never emit structuredContent in
    tools/call, violating MCP §4 MUST. Fix: after the artifact is produced, attempt
    `entry.decl.emits.model_validate(artifact)` if artifact is not already a BaseModel, then
    serialize to structuredContent. If model_validate fails, emit isError=True.
  - AC: Test with a tool that declares `emits=SomeModel` but returns a plain dict asserts
    tools/call response includes structuredContent matching SomeModel.model_json_schema().

- [ ] `SC-C2` MCP tools/list lacks cursor/nextCursor pagination ‖ group:C
  - Creates: modifies `agent_sdk/routes/mcp.py`
  - Reads: `agent_sdk/routes/mcp.py:236-254`
  - Severity: low  ← stack-check MCP D2
  - Root cause: `_handle_tools_list()` ignores the `cursor` param and never returns
    `nextCursor`. MCP §4 MUST supports pagination. For small registries this is not an
    operational block but fails MCP Inspector conformance tests.
    Accept `params.get("cursor")` (opaque int offset encoded as base64 string); return
    `nextCursor` when `len(tools) > PAGE_SIZE` (e.g. 64). Return all tools for small lists
    (no cursor needed when len ≤ PAGE_SIZE).
  - AC: Test with 65 registered tools: first tools/list call returns 64 tools + nextCursor;
    second call with that cursor returns remaining 1 tool + no nextCursor.

- [ ] `SC-C3` MCP WWW-Authenticate challenge missing scope= parameter ‖ group:C
  - Creates: modifies `agent_sdk/auth/middleware.py`
  - Reads: `agent_sdk/auth/middleware.py:60-68`
  - Severity: low  ← stack-check MCP D5
  - Root cause: The 401 challenge emitted at middleware.py:65 is
    `Bearer resource_metadata="..."` with no `scope=` parameter. RFC 9728 §5.1 RECOMMENDS
    including `scope=`. Change to:
    ```python
    challenge = f'Bearer resource_metadata="{runtime.prm_url}", scope=""'
    ```
    (empty string is correct when no scopes are enforced).
  - AC: Unauthenticated request to /mcp → 401 WWW-Authenticate header contains `scope=`.

- [ ] `SC-C4` MCP example tools lack annotations (destructiveHint defaults to true) ‖ group:C
  - Creates: modifies `agent_sdk/example/agent.py` (or wherever example tools are defined)
  - Reads: `agent_sdk/example/agent.py`
  - Severity: low  ← stack-check MCP D8
  - Root cause: The example tools (`echo`, `demo_kpis`) have no `annotations` in their
    @tools.tool() decorator. MCP defaults `destructiveHint=true` when annotations are absent,
    which is wrong for read-only query tools. Adding `read_only=True` sets
    `destructiveHint=false` and serves as the SDK documentation pattern.
  - AC: `echo` and `demo_kpis` tools in examples emit `annotations.destructiveHint=false`
    in tools/list response.

- [ ] `SC-C5` MCP tool name length (≤64 chars for Directory) not validated at registration ‖ group:C
  - Creates: modifies `agent_sdk/agent/registry.py`
  - Reads: `agent_sdk/agent/registry.py:195-210`
  - Severity: low  ← stack-check MCP D8
  - Root cause: No guard prevents tool names exceeding 64 characters at registration time.
    MCP Directory submission requires tool names ≤64 chars. Add at registration:
    ```python
    if len(decl.name) > 64:
        raise ValueError(f"tool name {decl.name!r} exceeds 64-char MCP Directory limit")
    ```
  - AC: Registering a tool with a 65-char name at build_app() time raises ValueError.

---

## Group D — A2UI protocol (server)

- [ ] `SC-D1` A2UI pre-wire validation missing for domain card wire() output ‖ group:D
  - Creates: modifies `agent_sdk/agent/runner.py`
  - Reads: `agent_sdk/agent/runner.py:95-115`, `agent_sdk/a2ui/translator.py`
  - Severity: medium  ← stack-check A2UI A1
  - Root cause: Standard Profile types are safe because they inherit `_Wire.wire()` via
    Pydantic. But domain cards implementing their own `wire()` bypass all validation before
    DataPart / CUSTOM event delivery. Add a structural assertion in `build_artifact()` after
    `translate()` is called: assert the resolved data is a non-empty list of dicts, each with
    required keys ("type" / "version"). If the check fails, raise a clear error before
    delivery rather than sending a malformed payload silently.
  - AC: A domain card whose `wire()` returns `{}` (a dict, not a list) triggers a ValueError
    at artifact-build time with a message identifying the content type.

- [ ] `SC-D2` A2UI no allowed_components filtering mechanism ‖ group:D
  - Creates: modifies `agent_sdk/a2ui/catalog.py`, `agent_sdk/models/content_types.py`
  - Reads: `agent_sdk/a2ui/catalog.py`, `agent_sdk/app.py:252-255`
  - Severity: low  ← stack-check A2UI A1
  - Root cause: There is no way to restrict which Profile component types are available to
    the LLM per-agent. The external a2ui-agent-sdk offers `allowed_components=[...]` on
    `generate_system_prompt()`. Implement an `a2ui_allowed_components: list[str] | None`
    setting on `BaseAgentSettings`; pass it to the catalog at boot so only listed types are
    registered and advertised in the agent card's `supportedCatalogIds` params.
    Default `None` = all registered types (current behavior, fully backwards compatible).
  - AC: Agent with `a2ui_allowed_components=["KpiCard"]` has only KpiCard in its registered
    catalog; emitting a TimeSeriesChart raises an unregistered-type error.

---

## Group E — ChatDriver A2A consumer (agent_sdk/testing/)

- [ ] `SC-E1` ChatDriver does not inject Authorization headers ‖ group:E
  - Creates: modifies `agent_sdk/testing/chat.py`
  - Reads: `agent_sdk/testing/chat.py:64-90`
  - Severity: medium  ← stack-check A2A D7.7
  - Root cause: `ChatDriver.__init__` accepts only `client: Any` and never reads the agent
    card's securitySchemes to inject credentials. Auth is the caller's responsibility with
    no guidance. Add `credentials: dict[str, str] | None = None` to `__init__`; merge into
    every outbound request header dict. The card's `security` field declares bearer scheme;
    accept `{"Authorization": "Bearer <token>"}` as the canonical form.
  - AC: ChatDriver instantiated with credentials={"Authorization": "Bearer test"} sends that
    header on every /v1/message:send and /v1/tasks/{id} request.

- [ ] `SC-E2` ChatDriver card discovery has no legacy agent.json fallback ‖ group:E
  - Creates: modifies `agent_sdk/testing/chat.py`
  - Reads: `agent_sdk/testing/chat.py:95-105`
  - Severity: low  ← stack-check A2A D7.1
  - Root cause: `_discover_card()` only fetches `/.well-known/agent-card.json`. A2A §7 SHOULD
    try `/.well-known/agent.json` as fallback for v0.2.x agents. On 404, retry with the
    legacy path before raising.
  - AC: ChatDriver pointed at a server serving only /.well-known/agent.json successfully
    discovers the card.

- [ ] `SC-E3` ChatDriver no additionalInterfaces transport fallback ‖ group:E
  - Creates: modifies `agent_sdk/testing/chat.py`
  - Reads: `agent_sdk/testing/chat.py:200-210`
  - Severity: low  ← stack-check A2A D7.2
  - Root cause: `a2a_turn()` reads `preferredTransport` and raises immediately if unsupported;
    no attempt to iterate `additionalInterfaces`. A2A §7 SHOULD fall back. Add a loop over
    `card.get("additionalInterfaces", [])` if preferred transport is unavailable.
  - AC: ChatDriver pointed at an agent whose preferredTransport is "GRPC" (unsupported) but
    whose additionalInterfaces includes HTTP+JSON successfully falls back to HTTP+JSON.

- [ ] `SC-E4` ChatDriver does not internally resume interrupted tasks ‖ group:E
  - Creates: modifies `agent_sdk/testing/chat.py`
  - Reads: `agent_sdk/testing/chat.py:245-255`
  - Severity: low  ← stack-check A2A D7.8
  - Root cause: On input-required / auth-required interrupt, ChatDriver fires the interrupt
    callback and raises A2AError. The caller must manually re-call with the same taskId +
    contextId. Add a `resume(task_id: str, context_id: str, reply: str)` method that
    constructs and sends the follow-up message with the existing task context, satisfying
    A2A §7 D7.8 "MUST continue using the SAME taskId + contextId".
  - AC: After triggering an input-required interrupt, calling `driver.resume(task_id,
    context_id, "answer")` sends a message with the original taskId and contextId.

- [ ] `SC-E5` ChatDriver doesn't distinguish A2A error codes ‖ group:E
  - Creates: modifies `agent_sdk/testing/chat.py`
  - Reads: `agent_sdk/testing/chat.py:83-95`
  - Severity: low  ← stack-check A2A D7.10
  - Root cause: `_raise_a2a_error()` packages code into A2AError but doesn't enumerate the
    seven A2A codes to provide code-specific behavior. While the code is preserved on the
    exception, callers have no SDK-level guidance. Add class-level constants or a mapping
    in A2AError so callers can `except A2AError as e: if e.code == A2A_TASK_NOT_FOUND: ...`
    without hardcoding -32001.
  - AC: `A2AError` exposes `TASK_NOT_FOUND = -32001`, `TASK_NOT_CANCELABLE = -32002`, etc.
    as class attributes. Existing raise sites unaffected.

---

## Group F — Cross-cutting

- [ ] `SC-F1` MCP structuredContent / A2A DataPart root cause is shared — enforce emits return type ‖ group:F
  - Creates: modifies `agent_sdk/app.py` or `agent_sdk/agent/registry.py`
  - Reads: `agent_sdk/app.py:118-134` (`_validate_emits`), `agent_sdk/agent/runner.py:125-135`
  - Severity: medium  ← root cause shared by SC-C1 and SC-A2
  - Root cause: `_validate_emits()` at app.py verifies that the `emits=` type is a registered
    content type, but does NOT enforce that the tool function's return type annotation matches
    the declared emits type. A tool annotated `-> dict` but declared `emits=KpiCard` will pass
    _validate_emits at boot, emit wrong artifacts at runtime (SC-A2), and omit structuredContent
    in MCP (SC-C1). Add a return-type check in `_validate_emits`: if the tool function has a
    return annotation that is not `emits` (or a supertype), raise at build_app() time.
    Accept `Any`, no annotation, or the exact emits type / a parent class; reject concrete
    non-matching types (e.g. `-> dict` when emits=KpiCard).
  - AC: `build_app()` with a tool declared `emits=KpiCard` but annotated `-> dict` raises
    ValueError at startup. `-> KpiCard`, `-> Any`, and unannotated all pass.
