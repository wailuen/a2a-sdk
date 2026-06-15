# w012 — GH-25/27/28/31 + opus compliance sweep

Sourced from open GH issues + exhaustive 4-advisor opus compliance audit (2026-06-15).
Root problem: HTTP-layer protocol behaviors are not unit-tested, so regressions ship silently
and surface only during downstream `/agent-verify` runs. This wave fixes the violations AND
pins them with regression tests so downstream agents inherit correctness automatically.

All items are independent unless noted. Run in parallel (group:G).
Target: 0.5.4.

---

## GH issues (triage complete)
- GH-26: CLOSED — already fixed in v0.5.3 (prm_url path-suffixed)
- GH-30: CLOSED — already fixed in v0.5.3 (_a2a_auth_envelope handler)
- GH-29: INTENT_CHANGE — x-sdk fields are intentional per DESIGN §4.5 (A2A advisor confirmed D1 PASS)

---

## Items

- [ ] `GH-25` + A2A-C1/C2/H1 — Comprehensive A2A HTTP error envelope ‖ group:A
  - Modifies: `agent_sdk/app.py:358-366`
  - Reads: `agent_sdk/common/wire_errors.py`, `agent_sdk/models/errors.py`, `tests/test_protocol_wire.py`
  - Severity: Critical (leaks FastAPI `{"detail":...}` on every wrong-method, unknown-/v1/-route, and query-validation failure)
  - Root cause (A2A advisor): `_a2a_auth_envelope` handler only covers 401/403. FastAPI's default
    exception handler serves the rest: 405 Method Not Allowed → `{"detail":"Method Not Allowed"}`,
    unknown /v1/ path 404 → `{"detail":"Not Found"}`, 422 validation error → `{"detail":[...]}`
    with input echo (SI-2 violation). A2A §5.1 requires all /v1/ errors in the A2A error envelope.
  - AC-1: `_a2a_auth_envelope` in `app.py` covers ALL `StarletteHTTPException` on `/v1/` paths:
    map 401/403→-32000, 404→-32001 (not found), 405→-32004 (method not supported), 415→-32005,
    any other→-32603 (internal). Return `{"error":{"code":<n>,"message":"..."}}`, preserve
    status + headers.
  - AC-2: Register a `RequestValidationError` handler for `/v1/` paths that returns HTTP 400,
    code -32602, with field LOCATIONS only (never echo the submitted value — match the hygiene
    already applied in `_parse_send` at `a2a.py:122-128`).
  - AC-3: Add route param guard in `tasks_get` (and optionally `tasks_cancel`) so `task_id`
    values containing `:` are rejected with -32601 "method not found" (prevents
    `/v1/tasks/abc:cancel` being swallowed by the GET route with a misleading -32001).
  - AC-4: `test_protocol_wire.py:109-118` that previously tolerated a 422 is updated to assert
    the 400 A2A envelope. New parametrized test asserts every /v1/ route with a wrong HTTP verb
    returns JSON with `error.code` (int) and `error.message` (str) and no `detail` key.
  - GH: https://github.com/wailuen/a2a-sdk/issues/25

- [ ] `GH-27` + MCP-C1 — Remove `scope=""` from WWW-Authenticate, unify challenge helper ‖ group:A
  - Modifies: `agent_sdk/auth/middleware.py:65`, `tests/test_mcp_conformance_w9.py:264-273`
  - Reads: `agent_sdk/routes/oauth.py` (lines 455, 602, 612), `agent_sdk/routes/admin.py:250`
  - Severity: Critical — RFC 6750 §3: `scope` ABNF requires ≥1 non-empty token; empty string is
    malformed. Strict OAuth clients may reject the challenge. Also: `scope=""` is present ONLY
    in the `require_identity` path; oauth.py:455/602/612 and admin.py:250 already emit the
    challenge without scope — four sites are correct, one is wrong.
  - Root cause (MCP advisor): `middleware.py:65`:
    `challenge = f'Bearer resource_metadata="{runtime.prm_url}", scope=""'`
    The symmetry bug that the token body correctly avoids (`oauth.py:500-503` omits scope when
    empty) is present in the WWW-Authenticate challenge. The flip-flopping is caused by
    `test_mcp_conformance_w9.py:264` which asserts `"scope=" in www_auth` — WRONG invariant —
    so a fix attempt breaks the test and gets reverted.
  - AC-1: Remove `, scope=""` from `middleware.py:65`. Introduce `_prm_challenge(prm_url)` helper
    returning `f'Bearer resource_metadata="{prm_url}"'`. Use it at all five challenge sites
    (middleware.py:65, oauth.py:455, oauth.py:602, oauth.py:612, admin.py:250) so they cannot
    diverge again.
  - AC-2: Flip `test_mcp_conformance_w9.py:264-273` SC-C3 to assert:
    `assert "scope=" not in www_auth` and `assert 'resource_metadata="' in www_auth`.
  - AC-3: New test asserts the FULL challenge string equals `f'Bearer resource_metadata="{prm_url}"'`
    (exact match, no extra params). Run on the A2A, MCP, and AG-UI surfaces (all three call
    require_identity and should emit the same challenge). This prevents future divergence.
  - GH: https://github.com/wailuen/a2a-sdk/issues/27

- [ ] `GH-31` + AG-UI-C1/C2 — TOOL_CALL_ARGS + TOOL_CALL_END handler with safe JSON reassembly ‖ group:A
  - Modifies: `agent_sdk/console/static/chat.js:445-473`
  - Reads: `agent_sdk/routes/ag_ui.py:200-208`, `agent_sdk/console/static/api.js:107-114`
  - Severity: Critical — AG-UI server emits `TOOL_CALL_START → TOOL_CALL_ARGS → TOOL_CALL_END →
    TOOL_CALL_RESULT` lifecycle. Consumer handles only START and RESULT. ARGS and END fall into
    `default: break` and are silently discarded — tool arguments are never surfaced in the UI.
    The SDK's own console is the reference consumer; downstream agents copy it.
  - Root cause (AG-UI advisor): no `case "TOOL_CALL_ARGS":` or `case "TOOL_CALL_END":` in the
    switch (chat.js:445-473). A `TOOL_CALL_ARGS.delta` is a JSON FRAGMENT (not always valid JSON
    on its own — LLMs stream partial JSON across multiple frames). A naive `JSON.parse(delta)`
    on each frame would throw on partial input. Must buffer fragments per toolCallId and parse
    only at TOOL_CALL_END, wrapped in try/catch so a parse failure degrades to raw text display
    rather than aborting the `readSse` loop.
  - AC-1: Add `const toolArgBuffers = new Map()` at the start of `sendAgui`.
  - AC-2: Add `case "TOOL_CALL_ARGS": { const buf = toolArgBuffers.get(json.toolCallId) ?? "";
    toolArgBuffers.set(json.toolCallId, buf + (json.delta ?? "")); break; }`
  - AC-3: Add `case "TOOL_CALL_END": { const raw = toolArgBuffers.get(json.toolCallId) ?? "";
    toolArgBuffers.delete(json.toolCallId); try { const parsed = JSON.parse(raw);
    systemLine(\`tool args: \${fmtJson(parsed)}\`); } catch { systemLine(\`tool args (raw): \${raw}\`); }
    break; }`
  - AC-4: Tighten `tests/test_card_console.py:57-61`: the routing-parity check must assert that
    TOOL_CALL_ARGS and TOOL_CALL_END appear in the switch BODY, not just anywhere in the file.
  - GH: https://github.com/wailuen/a2a-sdk/issues/31

- [ ] `GH-28` + A2UI-HIGH1/2 — Console renderer: JSON fallback + catalog sync test ‖ group:B
  - Modifies: `agent_sdk/console/static/a2ui.js:155-165`, `tests/test_card_console.py`
  - Reads: `agent_sdk/a2ui/catalog.py`, `agent_sdk/models/content_types.py`
  - Severity: Medium — when a domain agent registers a new ContentModel type, the console
    renders it as flat fallback text (losing all structured data). There is no mechanism to
    sync Python's content-type registry with the JS renderer table.
  - Root cause (A2UI advisor): `a2ui.js:700-715` RENDERERS is a hardcoded object literal.
    Dispatch at :157 hits `if (!renderer)` for unknown components and calls `fallbackNode()`
    which renders only `to_plain_text()` output — the resolved structured `data` object is
    discarded. `chat.js:391/490` already uses `fmtJson()` for DataParts and AGENT_ARTIFACTs,
    so the console is internally inconsistent.
  - AC-1: In `a2ui.js:158-161` unknown-component branch: when `value` is a non-null object,
    render the surface card with `el("pre", {class:"code-output mono"}, fmtJson(value))` so
    structured data is inspectable before a custom renderer is added.
  - AC-2: Add a catalog-sync test in `tests/test_card_console.py` that parses `a2ui.js`'s
    RENDERERS keys (regex extract `RENDERERS = {` block) and asserts they cover every frozen
    PROFILE_TYPES component name from `agent_sdk/models/content_types.py`. This prevents
    silent drift where a new Profile type ships in Python without a JS renderer entry.
  - Note: Full `registerRenderer()` extensibility seam (A2UI-HIGH1) is deferred — this wave
    delivers the immediate fallback fix and the drift-detection test.
  - GH: https://github.com/wailuen/a2a-sdk/issues/28

- [ ] A2UI-H3/H4 — KpiTrend + TimeSeriesChart non-conformant wire fields ‖ group:B
  - Modifies: `agent_sdk/models/content_types.py`
  - Reads: `agent_sdk/console/static/a2ui.js:231-251,300`
  - Severity: High — A2UI Standard Profile v1 frozen contracts violated on two types
  - Root cause (A2UI advisor):
    1. `MetricItem.trend` accepts a `KpiTrend` object `{direction, delta_pct, period}`. Profile
       v1 specifies `trend` as a string direction hint only (`"up"/"down"/"flat"`). The console
       renderer at `a2ui.js:231-251` reads `trend.direction`/`trend.delta_pct` only when `trend`
       IS an object — so there IS console support — but the wire format violates the spec. Any
       third-party renderer following the spec would see a dict where a string is expected.
    2. `TimeSeriesChart` emits `series: [{name, points}]` at both per-point and top-level
       levels. Profile v1 `time_series` only defines a flat `data:[{date, value, label?}]` array.
       The console reads only `p.value` (`:300`) confirming multi-series data is silently lost.
  - AC-1: Constrain `MetricItem.trend` wire output to the string form: either drop `KpiTrend`
    and use `Literal["up","down","flat"] | None`, or keep `KpiTrend` as a Python helper but
    serialize it as its `.direction` string in `wire()` and move `delta_pct`/`period` into
    separate optional fields (`trend_delta_pct`, `trend_period`) that are conformant extras.
  - AC-2: Remove the `series`/`SeriesMeta` fields from `TimeSeriesChart` and
    `TimeSeriesDataPoint` wire output. The `data` array remains (point-level `series` key also
    removed from wire). If multi-series display is needed, route those tools to `MultiCategoryChart`
    or a new domain type.
  - AC-3: Tests asserting `KpiCard(...).wire()["metrics"][0]["trend"]` is a string or absent,
    never a dict; and `TimeSeriesChart(...).wire()` has no `series` key at any level.
  - AC-4: Update the console `a2ui.js:231-251` to read only the string trend value (remove the
    object-form branch) after AC-1 removes the object wire format.

- [ ] MCP-H2 — Origin validation on MCP routes (DNS-rebinding defense) ‖ group:A
  - Modifies: `agent_sdk/routes/mcp.py:371` (`mcp_post`), `:444` (`mcp_get`)
  - Reads: `agent_sdk/app.py:345`, `agent_sdk/common/cors.py`
  - Severity: High — MCP spec §10/§12: HTTP MCP servers MUST validate the `Origin` header to
    prevent DNS-rebinding attacks. The CORS middleware governs `Access-Control-*` headers for
    browsers but does NOT reject requests with a non-allowlisted `Origin`. A request from
    `Origin: http://evil.local` with a valid bearer token reaches MCP route handlers unchanged.
  - Root cause (MCP advisor): no `Origin` check in `mcp_post`/`mcp_get`. The `cors_origins`
    allowlist already exists at `app.py:345` (`{settings.cors_origins} | {"https://claude.ai"}`).
  - AC-1: In both `mcp_post` and `mcp_get`, at the top of the handler body, read
    `origin = request.headers.get("origin")`. If `origin is not None` and `origin not in
    app.state.cors_origins`, raise `HTTPException(status_code=403, detail="origin not allowed")`.
    Requests without an `Origin` header (non-browser, CLI tools, proxied requests) pass through.
  - AC-2: Store the computed origin set on `app.state.cors_origins` in `build_app()` (alongside
    the middleware init) so routes can reference it without reimporting.
  - AC-3: Test: authenticated `POST /mcp` with `Origin: https://evil.example.com` → 403;
    same request without `Origin` header → proceeds normally.

- [ ] AG-UI-H1 — Fix AGENT_ARTIFACT value casing in docs (snake_case → camelCase) ‖ group:C
  - Modifies: `docs/protocols.md:45`, `DESIGN.md:320` (if line exists)
  - Reads: `agent_sdk/routes/ag_ui.py:271-273`, `agent_sdk/routes/agent_card.py:42-44`
  - Severity: High (docs — causes downstream consumer break when implementing from docs)
  - Root cause (AG-UI advisor): docs say `{data_type, tool_name, data}` (snake_case); the actual
    wire format at `ag_ui.py:272` and the card schema at `agent_card.py:42-44` both use camelCase
    `{dataType, toolName, data}`. Downstream agent authors implementing a custom consumer from
    the docs read `value.data_type` → `undefined`.
  - AC-1: Update `docs/protocols.md` AGENT_ARTIFACT value description to `{dataType, toolName, data}`.
  - AC-2: If `DESIGN.md` has a matching entry, update it too.
  - AC-3: Add a test asserting `_CUSTOM_EVENT_SCHEMAS[0]["valueSchema"]["properties"]` keys equal
    `{"dataType", "toolName", "data"}` — so a future rename in agent_card.py will fail the test.

- [ ] Tests-H — Comprehensive regression tests for HTTP protocol behaviors ‖ group:C
  - Creates: `tests/test_http_protocol.py` (new), updates: `tests/test_oauth_flow.py` (new or
    appends to existing), `tests/test_mcp_conformance_w9.py:264-273` (SC-C3 flip already in
    GH-27 item)
  - Reads: All test files in `tests/`, `agent_sdk/auth/`, `agent_sdk/routes/`
  - Severity: Critical (systemic fix — this is the "nipping the bud" change)
  - Root cause: HTTP wire behaviors are not unit-tested. Static LLM conformance checks can miss
    specific error formats, header values, and edge cases. These behaviors are discovered only
    when downstream agents run `/agent-verify` against a live endpoint. Every conformance
    regression that made it to downstream discovery had no test pinning the correct behavior.
  - AC-1 — `tests/test_http_protocol.py` (new file, run against a minimal `TestClient` app):
    - WWW-Authenticate challenge exact string: unauthenticated request to /v1/, /ag-ui/run, /mcp
      all produce `WWW-Authenticate: Bearer resource_metadata="<path-suffixed-prm>"` with
      NO `scope=` param anywhere.
    - 405 on /v1/ routes: assert `error.code` present, no `detail` key, correct HTTP status.
    - 422 on /v1/ with bad query param (`?historyLength=notanint`): assert 400, `error.code == -32602`,
      and the string "notanint" does NOT appear in the response body.
    - Unknown /v1/ path (GET /v1/bogus): assert `error.code` present, no `detail` key.
    - MCP route with disallowed Origin header: assert 403.
    - `GET /mcp` authenticated → `content-type: text/event-stream`.
  - AC-2 — `tests/test_oauth_flow.py` (new file):
    - POST /oauth/token with valid code → 200, `access_token` present, `scope` key ABSENT
      (pins oauth.py:500-503 no-empty-scope rule).
    - POST /oauth/token with bad code → 400 `{"error":"invalid_grant"}`.
    - POST /oauth/token with wrong grant_type → 400 `{"error":"unsupported_grant_type"}`.
    - POST /oauth/register with valid redirect_uri → 201, `client_id` present, 
      `token_endpoint_auth_method: "none"`.
    - POST /oauth/register with non-https redirect → 400 `{"error":"invalid_redirect_uri"}`.
    - Token endpoint has no auth requirement (no Bearer needed): POST with no Authorization → proceeds.
  - AC-3 — A2UI wire conformance (append to `tests/test_content_types.py` or new file):
    - `translate()` output: assert it's a list of 4 dicts, each has `version`, first has
      `type=="createSurface"` with `catalogId`, last has `type=="deleteSurface"`.
    - `KpiCard.wire()["metrics"][0]["trend"]` is string or absent, never a dict.
    - `TimeSeriesChart.wire()` has no `series` key.
    - Catalog-sync: `RENDERERS` keys in `a2ui.js` cover every `PROFILE_TYPES` component.
