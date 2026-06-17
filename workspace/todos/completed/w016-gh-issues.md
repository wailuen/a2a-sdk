# w016 — GitHub issues #45, #48, #50, #52, #53, #54, #55

Sourced from open issues on wailuen/a2a-sdk. Three parallel groups.
Target: v0.5.13.

Groups:
- group:A — acceptance-api.js changes (#53, #55 — same file, must be done together)
- group:B — independent files (#52, #54, #48)
- group:C — A2A route changes (#45, #50 — both touch a2a.py)
No inter-group dependencies — all three groups run concurrently.

---

- [x] `GH-53` + `GH-55` acceptance-api.js: parallel-session bleed + missing failureClass + followUpTurns ignored ‖ group:A
  - Creates: (modifies `harness/workflows/acceptance-api.js`)
  - Reads: `harness/workflows/acceptance-api.js`
  - Severity: high
  - Root cause (GH-53): `acceptance-api.js` sets `THREAD_ID = s.id` (deterministic), causing concurrent runs of the same scenario to share `/tmp/acc-{s.id}-agui-msgs.json` and the AG-UI thread, producing cross-contamination. `SCENARIO_RESULT_SCHEMA.failureClass` enum is missing `harness-contamination`; `additionalProperties: false` rejects the field. Root cause (GH-55): `buildScenarioPrompt` (line 58) never reads `s.followUpTurns`; the field is undocumented and silently dropped; follow-up queries are always auto-generated regardless of scenario file contents.
  - AC (GH-53): `THREAD_ID` includes a UUID suffix so each invocation is isolated; all `/tmp/acc-{s.id}-*` filename literals also scoped with the same per-invocation UUID; `failureClass` enum includes `harness-contamination` with classification rule documented in FINAL SCORING.
  - AC (GH-55): When `s.followUpTurns` is a non-empty array, `buildScenarioPrompt` injects a `DETERMINISTIC FOLLOW-UPS` section listing each pinned query verbatim; both A2A and AG-UI step-4 conditionally use the next pinned entry before auto-generating.
  - GH-53: https://github.com/wailuen/a2a-sdk/issues/53
  - GH-55: https://github.com/wailuen/a2a-sdk/issues/55

- [x] `GH-52` protocol/mcp: openWorldHint=false missing for tier-1 read-only tools ‖ group:B
  - Creates: (modifies `agent_sdk/agent/registry.py`, `tests/test_mcp_conformance_w9.py`)
  - Reads: `agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`
  - Severity: high
  - Root cause: `ToolSet.tool()` decorator in `registry.py:62–67` sets `readOnlyHint=true` and `destructiveHint=false` for `read_only=True` tools but never sets `openWorldHint=false`. MCP spec 2025-06-18 defaults `openWorldHint` to `true` (unbounded world-altering), which misclassifies all pure read-only query tools.
  - AC: `annotations.openWorldHint = False` is emitted in `tools/list` for all tools with `tier=1` or `read_only=True`; test in `test_mcp_conformance_w9.py` asserts `openWorldHint == False` on representative tools.
  - GH: https://github.com/wailuen/a2a-sdk/issues/52

- [x] `GH-54` workspace/learning: LRN-028 ID collision, wrong Check clause, README gap ‖ group:B
  - Creates: (modifies `workspace/learning/`, `workspace/learning/README.md`)
  - Reads: `workspace/learning/LRN-028-*.md`, `workspace/learning/README.md`
  - Severity: high
  - Root cause: Two files share the `LRN-028` ID (`LRN-028-unconditional-seam-audit-dispatch.md` and `LRN-028-redteam-findings-count-mismatch.md`). A third LRN-028 (covering the THREAD_ID / acceptance-api.js risk) was described in the issue but does not exist. `workspace/learning/README.md` stops indexing at LRN-018; LRN-019 through LRN-037+ are absent. The missing Check clause should grep `harness/workflows/acceptance-api.js` for `THREAD_ID = .*-agui` (not `tests/`).
  - AC: One of the duplicate LRN-028 files is renumbered to the next available ID (confirm `LRN-038` is free); a new LRN covering the acceptance-api THREAD_ID risk is created with a Check clause that greps `harness/workflows/acceptance-api.js`; `workspace/learning/README.md` indexes all LRN-018 through LRN-037+ entries.
  - GH: https://github.com/wailuen/a2a-sdk/issues/54

- [x] `GH-48` sdk/loop: tool ValidationError swallowed generically — LLM cannot self-correct ‖ group:B
  - Creates: (modifies `agent_sdk/agent/loop.py`, `tests/`)
  - Reads: `agent_sdk/agent/loop.py`, `agent_sdk/agent/registry.py`, `agent_sdk/models/errors.py`
  - Severity: low
  - Root cause: Bare `except Exception` handlers at `loop.py:272–273` and `301–302` collapse Pydantic `ValidationError` (raised from `ToolEntry.invoke()` on bad input) into the generic `"tool '{name}' failed"` string, discarding field name, error type, and validation rule. The LLM cannot self-correct without knowing which field failed and why.
  - AC: A targeted `except ValidationError` branch before the bare `except Exception` extracts `loc`, `type`, `msg` from `exc.errors()` (explicitly omitting `input` to satisfy SI-2) and formats `"tool '{name}' input invalid: {field} — {type} ({msg})"`. Test asserts the field name appears in the error text and the raw rejected input value does NOT.
  - GH: https://github.com/wailuen/a2a-sdk/issues/48

- [x] `GH-45` protocol/a2a: JSON parse error returns -32602 instead of -32700 ‖ group:C
  - Creates: (modifies `agent_sdk/common/wire_errors.py`, `agent_sdk/routes/a2a.py`, `tests/`)
  - Reads: `agent_sdk/routes/a2a.py`, `agent_sdk/common/wire_errors.py`
  - Severity: low
  - Root cause: `_parse_send()` at `a2a.py:118–119` catches `json.JSONDecodeError` and calls `a2a_invalid_params()` which emits -32602. JSON-RPC 2.0 §5 mandates -32700 (Parse Error) for unparseable JSON; -32602 is for valid JSON with wrong content (already correctly used at lines 121–129 for Pydantic `ValidationError`).
  - AC: `a2a_parse_error()` helper added to `wire_errors.py`; `a2a.py:119` calls it for `json.JSONDecodeError`; test sends malformed JSON to `POST /v1/message:stream` and asserts `error.code == -32700`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/45

- [x] `GH-50` protocol/a2ui: A2UI DataParts emitted without X-A2A-Extensions opt-in ‖ group:C
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/a2ui/translator.py`, `tests/`)
  - Reads: `agent_sdk/routes/a2a.py`, `agent_sdk/a2ui/translator.py`, `agent_sdk/a2ui/catalog.py`
  - Severity: low
  - Root cause: `_capabilities()` at `a2a.py:82–84` reads only `message.metadata.a2uiClientCapabilities`; it never checks the `X-A2A-Extensions` HTTP request header. When the metadata key is absent, `A2uiCapabilities.from_metadata()` returns a default core-tier capability that enables A2UI DataPart emission for all standard types — even if the client never sent the opt-in extension header.
  - AC: `_capabilities()` accepts `Request` and gates A2UI on `X-A2A-Extensions` containing `A2UI_EXTENSION_URI` — if absent, returns `A2uiCapabilities(tier='none', catalogs=[])` so `allows()` is always False; call sites in `message_send` and `message_stream` pass `request`; test confirms no A2UI MIME DataPart on requests without the header; test confirms A2UI DataPart present when header is set.
  - GH: https://github.com/wailuen/a2a-sdk/issues/50
