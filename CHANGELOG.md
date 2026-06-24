# Changelog

All notable changes to `agent-sdk`. SemVer applies to the stable core
(DESIGN.md §4.0); provisional surfaces (`agent_sdk.testing`, console
internals, `contrib/`) may change in minors with notice here.

## [0.5.35] — 2026-06-24

### ✅ Features
- GH-93: `pip install "agent-sdk[openai]"` now installs the `openai` package via a declared optional extra; `build_app()` probes eagerly for `openai` when `OPENAI_MODEL` or `AZURE_OPENAI_ENDPOINT` is set and raises `ImportError` with a clear `agent-sdk[openai]` install hint if absent; `converse()` in `openai_client.py` now re-raises `ModuleNotFoundError` before the bare `except Exception` so missing-package errors are never swallowed as generic `AgentError`. (`pyproject.toml`, `agent_sdk/app.py`, `agent_sdk/agent/openai_client.py`)

### 🧪 Test / CI
- GH-93: `tests/test_gh93_openai_missing_package.py` — 2 cases: startup import probe raises `ImportError` with install hint when openai absent; `converse()` propagates `ModuleNotFoundError` unmodified
- GH-92: replace `MagicMock` / `AsyncMock` with real in-memory fakes in `test_scheduler.py` (`types.SimpleNamespace`), `test_a2ui_group_d.py` (`_StubContentModel` concrete subclass), `test_azure_commitment_store.py` (`_FakeTableClient` dict-backed ETag-aware fake); zero `unittest.mock` usage remaining in those files

## [0.5.34] — 2026-06-22

### ✅ Features
- GH-91: `_validate_emits` (SC-F1) now accepts `AsyncIterator[T]` and `AsyncGenerator[T, None]` return annotations on async-generator tools with `emits=T`; wrong yield type raises `ValueError` with a clear message at boot. (`agent_sdk/app.py`)

### 🔧 Fixes
- GH-90: harness A2A multi-turn driver now continues via `contextId` (not `taskId`) when the prior turn's task was completed; `taskId` reuse is correctly gated to `input-required` / `auth-required` continuations only. Eliminates false `transport-divergence` failures on multi-turn `/acceptance` runs. (`harness/workflows/acceptance-api.js`, `harness/skills/acceptance/SKILL.md`)

### 🧪 Test / CI
- `tests/test_gh91_generator_emits_validation.py` — 4 cases: `AsyncIterator[T]` passes, `AsyncGenerator[T, None]` passes, wrong type raises, no annotation passes

## [0.5.31] — 2026-06-21

### ✅ Features
- GH-88: async-generator tool contract — `@tools.tool` now accepts `AsyncGenerator` functions; tools may `yield ToolProgressEvent(...)` for interim progress and `return` their terminal artifact. Backward-compatible: existing coroutine tools unchanged. (`agent_sdk/agent/registry.py`, `loop.py`, `events.py`)
- GH-87: first-class long-running / deferred-task delivery — a tool can return `DeferredResult(handle)` to register a background job; the A2A task stays `WORKING` and streams `TaskStatusUpdateEvent{state:"working"}` until the handle resolves, then delivers the artifact and transitions to `COMPLETED`; timeout → `FAILED`. New `agent_sdk/agent/deferred.py`. (`agent_sdk/agent/loop.py`, `runner.py`, `registry.py`, `routes/a2a.py`)
- GH-87: `@tool(long_running=True, tool_timeout_override=N)` decorator kwargs — per-tool timeout override independent of global `TIER_TIMEOUTS`.

### 🔧 Fixes
- GH-89: `harness/workflows/acceptance-api.js` — `require('crypto').randomUUID()` replaced with caller-provided `args.runId` (minted in the skill where `require` is available); `/acceptance` gate is now functional on all agents.
- GH-88: `ToolProgressEvent` wired to AG-UI `CUSTOM{name:"TOOL_PROGRESS"}` and A2A `TaskStatusUpdateEvent{state:"working",final:false}` so long-running tools emit visible progress on both transports.

### 🧪 Test / CI
- `tests/test_gh88_tool_interim_emit.py` — async-generator tool interim-emit coverage
- `tests/test_gh87_deferred_task.py` — deferred-task resolve, timeout, and working-state coverage

## [0.5.28] — 2026-06-21

### ⚠️ Breaking changes
- acd28c9 feat(w024/GH-86): `build_app()` now raises `ValueError` at boot in production (`DEV_MODE=false`) when `AGENT_NAME` is unset or set to the reserved placeholder `"agent"`. Previously such agents booted with the degraded `"agent"` identity. **Migration:** production agents must set `AGENT_NAME` to a non-placeholder value or `build_app()` now fails; set `DEV_MODE=true` to retain the prior warn-only behavior. Note: `"agent"` (case-insensitive) is permanently reserved as the unset sentinel — choose any other name.

### 🔧 Fixes
- 6aa8431 fix(w024/GH-86): card `description` now falls back to `display_name` sentinel when blank, never emits `""` (A2A §3.1 compliance, LRN-101)
- 9c8e8d4 fix(azure-dev): warn at boot when `AZURE_STORAGE_ACCOUNT_NAME` set without connection string in DEV_MODE

### 📖 Docs
- 6798bbb docs(harness): add no-mock rule for SDK tests in `tests/`

## [0.5.24] — 2026-06-20

### 🟡 Protocol surface changes
- eb303e5 feat(w023): TaskStatus.error extension declared with `https://` URI in agent card (GH-78)
- eb303e5 feat(w023): credential-forwarding extension URI corrected to `https://` scheme (GH-79)
- 2f5786b feat(w022): AG-UI transport made fail-closed — A2UI_UPDATE suppressed unless client sends `forwardedProps.a2uiClientCapabilities` (GH-74)
- 2f5786b feat(w022): MCP absent-header behaviour: Streamable HTTP 400s on absent `Mcp-Protocol-Version`; legacy SSE exempted per spec §10 SHOULD (GH-77)
- 2f5786b feat(w022): `POST /v1/tasks/{id}:subscribe` route confirmed correct per A2A v0.3.0 §2 binding table (GH-75, LRN-099)
- 2f5786b feat(w022): `urn:agui:run:v1` extension URI corrected to `https://agent-sdk.dev/extensions/ag-ui-run/v1` (GH-85, LRN-097)
- 6f5af70 fix(w022-redteam3): agent card now uses `registry.tier1()` — Tier-2 (A2A-only) tools no longer appear in card `skills` section (LRN-094)
- bbfe353 fix(w022-redteam): `ag_ui_run` Content-Type 415 guard added; reject present non-JSON body before SSE stream opens (LRN-093 parity)

### ✅ Features
- eb303e5 feat(w023): `agent_sdk.contrib.Scheduler` — `@cron(interval_seconds)` decorator + `sched.lifespan` context manager for background jobs; `agent_sdk.scheduler` stub raises `ImportError` with migration guide (GH-81)
- eb303e5 feat(w023): `/acceptance` skill wired to named workflow via `scriptPath` form (GH-83 workaround, LRN-096)
- 2f5786b feat(w022): `A2uiCapabilities.for_custom_emit()` — per-transport A2UI capability resolver; `ag_ui.py` uses it to gate `A2UI_UPDATE` emission
- 2f5786b feat(w022): `urn:agui:run:v1` → `https://` extension added to `capabilities.extensions` (GH-73)
- 2f5786b feat(w022): `A2UI_UPDATE` valueSchema `messages.items.type='object'` added (GH-76)
- 2f5786b feat(w022): `TaskStore.list_tasks_for_identity` returns `tuple[list[Task], str|None, int]`; third element is total match count for correct `totalSize` in `GET /v1/tasks` (GH-75)

### 🔧 Fixes
- eb303e5 feat(w023): wave-cycle archive gate extended to cover `tests/`, `workspace/learning/`, `workspace/scenarios/results/`, `workspace/prd/` paths via `offendingHarnessPaths` (GH-84)
- f08214c fix(GH-83): acceptance skill `scriptPath` resolution hardened
- f5249d8 fix(GH-84): archive null guard + commit gate hardened
- 2f5786b feat(w022): `_create_task_record`/`_resume_or_error` archive `model_copy` of inbound `Message` — eliminates `contextId` mutation side-effect (LRN-048)
- bbfe353 fix(w022-redteam): reference binding tables, `docs/protocols.md`, `DESIGN.md` corrected to `POST /v1/tasks/{id}:subscribe` (was `:resubscribe`)
- bbfe353 fix(w022-redteam): `agent_sdk/routes/mcp.py` module docstring corrected to document Streamable vs legacy SSE absent-header divergence

### 🧪 Test / CI
- 993e2c5 fix(w023-redteam4): LRN frontmatter consistency guard test added; 8 id mismatches corrected
- 6f5af70 fix(w022-redteam3): `test_card_mcp_surface_parity.py` — live card vs MCP `tools/list` parity test
- 2f5786b feat(w022): tests for GH-73/74/75/76/77 (ag-ui caps, card extensions, MCP version gate, route, schema)

### — Other
- 986894a docs(w023): LRN-096/097/098 codified — named-workflow args drop, extension URI scheme, scheduler pattern
- 25bb71a chore(w022): plan.md updated; w020b + w022 archived

## [0.5.19] — 2026-06-19

### ✅ Features

- **loop: `max_output_tokens` configurable via `LoopPolicies` (GH-73)** —
  `LoopPolicies` gains `max_output_tokens: int = 8192` (`DEFAULT_MAX_OUTPUT_TOKENS`).
  Every `model.converse()` call now forwards `max_tokens=policies.max_output_tokens`,
  preventing silent model-side truncation on long completions. Default 8 192 matches
  Bedrock Converse defaults; callers can override at `Agent` construction.

### 🔧 Fixes

- **harness/acceptance-api.js: A2A transport four-bug fix (GH-71)** —
  1. URL corrected to `POST /v1/message:stream` (colon path, not `/v1/message/stream`).
  2. JSON-RPC envelope removed — the HTTP+JSON binding takes a flat `MessageSendParams`
     body, not a `{jsonrpc,method,id,params}` wrapper.
  3. `messageId` added to every outgoing message (A2A v0.3.0 §4.1 MUST).
  4. SSE event parsing switched to `ev["kind"]` (`"task"` / `"status-update"` /
     `"artifact-update"`) — the A2A HTTP+JSON binding emits kind-discriminated objects,
     not JSON-RPC method frames. `taskId` now harvested from the first `kind == "task"`
     frame (authoritative) before the `status-update` fallback.

- **sdk/agent: Bedrock credentials from credential store (GH-72)** —
  `BedrockModelClient.__init__` accepts four kwargs: `bearer_token`,
  `aws_access_key_id`, `aws_secret_access_key`, and `aws_session_token`.
  `Agent._build_model_client()` resolves all four from `NS_BEDROCK` in the
  encrypted credential store and forwards them; none are read from `os.environ`
  (SI-6). `aws_session_token` is forwarded alongside the access/secret pair only
  when present — it is required for STS / temporary credentials; long-lived IAM
  keys omit it. Absence of all four falls through to the boto3 default chain
  (env vars / instance-profile IAM). Thread-safe double-checked locking added to
  `_boto_client()`. (Targeted 0.5.18; shipped under 0.5.19.)

- **sdk/build: `-> None` return annotation no longer skips emits mismatch check (RT-002)** —
  `inspect.get_annotations` collapses an explicit `-> None` and a missing annotation
  to the same Python `None`. `app.py` now checks `fn.__annotations__` directly:
  the emits/return-type validation is skipped only when `"return"` is absent from
  `__annotations__`; an explicit `-> None` with a non-`None` `emits=` now raises
  `ValueError` as intended.

- **sdk/a2a: unknown-route 404 now emits -32603 not -32001 (RT-003)** —
  `_A2A_CODE` previously mapped `404 → -32001` (TaskNotFound), mislabelling every
  unrouted `/v1/` hit. The `404` entry is removed; the `.get(status, -32603)` fallback
  applies instead. `-32001` is still raised explicitly by task routes when a task is
  absent. `test_a2a_error_envelope.py::test_unknown_v1_route_404_a2a_envelope` tightened
  to assert exactly `-32603`.

### 🧪 Test / CI

- `tests/test_gh71_acceptance_api_stream.py` — four AC tests covering the corrected
  A2A streaming path: colon URL, flat body, `messageId` presence, `kind`-based SSE
  event parsing.
- `tests/test_bedrock_credential_store.py` — credential-store injection tests for
  `BedrockModelClient` (`bearer_token`, IAM static keys, default-chain fallback).
- `tests/test_emits_return_type.py` — case (h): explicit `-> None` with `emits=` raises
  `ValueError` (was silently skipped).
- `tests/test_a2a_error_envelope.py` — `test_unknown_v1_route_404_a2a_envelope` now
  asserts `error.code == -32603` exactly.

---

## [0.5.17] — 2026-06-19

### ✅ Features

- **harness/skills: standardise on `uv sync --frozen` + `uv.lock` across upgrade, setup, new-agent (GH-70)** —
  `harness/skills/upgrade/SKILL.md` now runs `uv lock` after every SHA bump and uses
  `uv sync --frozen --extra dev` for the reinstall; `harness/skills/setup/SKILL.md`
  generates `uv.lock` in Phase 2 and uses `uv sync --frozen` for the first install;
  `harness/skills/new-agent/SKILL.md` adds a `uv lock` generation step before the
  first install. All three skills now commit `uv.lock` alongside `pyproject.toml`.
  `template/Dockerfile` updated in `wailuen/a2a-agent-template` — uses
  `uv sync --frozen` with uv from `ghcr.io/astral-sh/uv:latest`.

### 🔧 Fixes

- **harness: two wave-cycle.js copies reconciled into byte-identical superset** —
  `.claude/workflows/wave-cycle.js` was a stale fork missing every fail-closed null-gate
  hardening that `harness/workflows/wave-cycle.js` carried. The copies are now unified;
  `tests/test_workflow_sync.py` asserts byte-identity to prevent future drift.

### 🧪 Test / CI

- **tests: `test_learning_index.py` guards LRN file ↔ index consistency** —
  Any LRN file written to `workspace/learning/` without a corresponding index row in
  `README.md` is now caught by CI (the redteam learning-check loop would otherwise
  miss it).
- 1600572 chore: track uv.lock — resolves RT-004 ambiguous lockfile

## [0.5.16] — 2026-06-18

### 🟠 Security

- **harness: ADR credential gitignore globs were entirely absent (GH-66)** —
  `harness/.gitignore` did not exist; neither `workspace/adr/ADR-000-*-credentials.md`
  nor `workspace/adr/ADR-001-*-credentials.md` was gitignored anywhere, despite
  `CLAUDE.md` asserting both are protected. Created `harness/.gitignore` with both
  globs so `/provision`-written credential inventory files are never accidentally committed.

### ✅ Features

- **sdk/models: `metadata` escape hatch on all ContentModel profile types (GH-63)** —
  Added `metadata: dict[str, Any] | None = None` to the 13 `ContentModel` subclasses
  that previously lacked it (`KpiCard`, `ComparisonTable`, `BarChart`, `EntityList`,
  `MarketBriefing`, `WaterfallChart`, `MultiCategoryChart`, `FundPerformance`,
  `EmailList`, `CalendarEvents`, `UserProfile`, `UserList`, `DocumentList`), matching
  the existing pattern on `TimeSeriesChart` and `CategoryValue`. Domain code can now
  pass disclosure annotations (e.g. `coverage_note`) via `metadata={"coverage_note":
  "Partial: 5 of 20 funds"}` without silent field loss. `extra='ignore'` preserved
  for backward compatibility.

### 🔧 Fixes

- **harness/skill: `/provision` now probes Storage Table Data Contributor RBAC before writing `.env` (GH-60)** —
  Phase 1b runs `az storage table list --auth-mode login` after collecting the account
  name. A 403 halts with the exact `az role assignment create` fix command; success
  prints "RBAC confirmed". Degrades gracefully when `az` is unauthenticated.

- **sdk/build: `AzureTableCredentialStore` error message now mentions `pyproject.toml` (GH-62)** —
  `_INSTALL_HINT` in `azure_utils.py` updated to include the `pyproject.toml`
  dependency form alongside the bare `pip install` form.

### 🧪 Test / CI

- `tests/test_content_types.py` — metadata round-trip tests for `GH-63`.

### — Other

- **harness/workflow: `acceptance-api.js` now uses `require('crypto').randomUUID()` (GH-58)** —
  Replaces `globalThis.crypto.randomUUID()` (Node 19+ only) with the Node 15.6+
  compatible form. Fixes `TypeError` on Node 18 LTS CI hosts.

- **harness/workflow: `sdk-wave.js` redteam prompts now include Dimension 5 (GH-65)** —
  Both unit and phase redteam prompts explicitly require checking for stubs, TODOs,
  and unmet ACs — matching `wave-cycle.js`'s "Run all 8 dimensions" instruction.

---

## [0.5.15] — 2026-06-18

### 🔧 Fixes

- **a2ui/ag-ui: domain catalog types now always emitted when tier ≠ "none" (GH-56)** —
  `A2uiCapabilities.allows()` previously gated domain `ContentModel` types on catalog
  membership (`model_cls.catalog_id in self.catalogs`), silently suppressing `A2UI_UPDATE`
  for consumers that omit `forwardedProps.a2uiClientCapabilities.catalogs`. This inverted
  the AG-UI spec contract (consumers silently ignore unknown CUSTOM events; servers emit
  freely). Fixed by removing the catalog-membership gate: domain types are now emitted
  whenever `tier != "none"`. Tier gating within the standard catalog (core vs extended)
  is unaffected. The `catalogs` list remains available for informational purposes.

### 🧪 Test / CI

- New tests in `tests/test_a2ui_group_d.py` and `tests/test_protocol_fixes_w6.py`
  verifying domain catalog emission with standard-only capabilities, and tier=="none"
  suppression regression guard.

---

## [0.5.14] — 2026-06-17

### 🟡 Protocol surface changes

- **a2a: terminal taskId now returns -32004 instead of creating a new task (GH-51)** —
  Removed `_continue_from_terminal()` which violated A2A v0.3.0 §6 item 14. A
  `message/send` or `message/stream` targeting a terminal `taskId` now returns
  `-32004 UnsupportedOperation` (send) or `-32001 TaskNotFound` (stream), never
  a silent new task. Spec-correct multi-turn continuation uses `contextId` only
  (no `taskId`): `_create_task_record()` calls `TaskStore.context_messages()` to
  carry prior conversation history into the new task.

- **a2a: `TaskStore.context_messages()` — contextId continuation API** —
  New method on `TaskStore` ABC (default `[]`) and `InMemoryTaskStore`
  implementation. Scans terminal tasks by `contextId` + `identity`, returns the
  most recent task's `messages` list for model-context prepopulation. Identity
  isolation enforced: different users cannot inherit each other's history on the
  same `contextId`.

### 🔧 Fixes

- **mcp: `ToolEntry.input_schema()` now always emits `required: []` + `additionalProperties: false` (GH-47)** —
  No-model branch returns a fully closed schema; Pydantic branch post-processes
  with `schema.setdefault("additionalProperties", False)` and
  `schema.setdefault("required", [])` so existing `required` arrays are preserved
  but empty schemas are closed. Fixes MCP `tools/list` responses that previously
  omitted these fields.

### 🧪 Test / CI

- `tests/test_w017_gh51_multiturn.py` — new test module covering contextId
  continuation (inherits prior history), stream continuation, fresh context (no
  prior history), terminal-taskId rejection (-32004), stream-terminal rejection
  (-32001), interrupt resume, and per-identity isolation.
- `tests/test_w017_gh47_input_schema.py` — new test module covering no-model
  closed schema, all-optional model schema, required-fields preservation, and
  MCP `tools/list` integration.

---

## [0.5.13] — 2026-06-17

### 🟡 Protocol surface changes

- **a2a: JSON parse errors return -32700, not -32602 (GH-45)** —
  `_parse_send()` now calls the new `a2a_parse_error()` helper
  (`common/wire_errors.py`) for unparseable request bodies, matching JSON-RPC
  2.0 §5 (Parse Error). -32602 (Invalid Params) remains reserved for valid JSON
  that fails `MessageSendParams` validation.

- **a2a: A2UI DataParts gated behind X-A2A-Extensions opt-in (GH-50)** —
  `_capabilities()` now reads the `X-A2A-Extensions` request header and only
  enables A2UI DataPart emission when it advertises the A2UI extension URI.
  Absent the header, capabilities resolve to `tier='none'` so no A2UI MIME
  DataPart is emitted — the client must opt in.

- **mcp: openWorldHint=false for tier-1 / read-only tools (GH-52)** —
  `ToolSet.tool()` now emits `annotations.openWorldHint = False` for tools with
  `tier=1` or `read_only=True`, overriding the MCP 2025-06-18 default of `true`
  so pure read-only query tools are no longer misclassified as world-altering.

### 🔧 Fixes

- **loop: tool ValidationError surfaces field/type so the model can self-correct (GH-48)** —
  A targeted `except ValidationError` branch now builds a tool-result error from
  `loc` + a type-derived phrase via `_safe_validation_message`, instead of
  collapsing into the generic `"tool '{name}' failed"`. SI-2: `msg` and `input`
  are never echoed (both can embed the raw rejected value). The error `loc` is
  walked against the tool's `input_model` so only schema-declared field names
  and list indices are echoed — user-supplied dict keys and `extra_forbidden`
  field names are redacted to `<key>`/`<extra>`, closing the residual loc-borne
  input-leak gap.

### 🔨 Harness

- **acceptance-api: per-invocation thread isolation + failureClass + deterministic follow-ups (GH-53, GH-55)** —
  `acceptance-api.js` now suffixes `THREAD_ID` and all `/tmp/acc-{s.id}-*`
  filenames with a per-invocation UUID, eliminating cross-contamination between
  concurrent runs of the same scenario; `SCENARIO_RESULT_SCHEMA.failureClass`
  gains the `harness-contamination` value; and `buildScenarioPrompt` now honours
  a scenario's `followUpTurns` array, injecting pinned follow-up queries verbatim
  on both A2A and AG-UI paths before falling back to auto-generation.

### 📖 Documentation

- **learning: resolve LRN-028 ID collision + reindex README (GH-54)** —
  The duplicate `LRN-028` is renumbered to a free ID, a new LRN codifies the
  acceptance-api `THREAD_ID` contamination risk with a Check clause that greps
  `harness/workflows/acceptance-api.js`, and `workspace/learning/README.md` is
  reindexed to cover the full LRN-018+ range.

## [0.5.12] — 2026-06-17

### 🟡 Protocol surface changes

- **mcp: gate serverInfo.title behind negotiated version 2025-11-25 (GH-43)** —
  `serverInfo.title` is absent when clients negotiate `2025-06-18` or `2025-03-26`;
  it is only included when the negotiated MCP protocol version is `2025-11-25` or later.
  MCP `SUPPORTED_PROTOCOL_VERSIONS` tuple locked to newest-first order via assert.

### ✅ Features

- **harness: tier-based parallel wave execution (ce34027)** —
  `wave-cycle.js` now resolves a `groupDeps` map from the wave file and executes
  todo groups whose dependencies are all complete concurrently within each tier,
  rather than strictly sequentially. Groups with no inter-group deps run in
  the same tier.

- **harness: pre-archive commit-intent guard (GH-40)** —
  Archive phase in `harness/workflows/wave-cycle.js` now runs a `git status --short`
  check before moving the wave file to `completed/`, cross-referencing dirty paths
  against the wave's `Creates:` entries. If any Creates file is uncommitted the
  archive is blocked (fail-closed). `ARCHIVE_INTENT_SCHEMA` is the structured gate.

### 🔧 Fixes

- **fix(content): DocumentList.to_plain_text() renders type and modification date (GH-42)** —
  `DocumentItem.type` and `last_modified` / `modified` date are now included in
  `to_plain_text()` output, matching the full wire contract for `DocumentList`.

### 📖 Documentation

- **docs: document lifespan_extras scheduling entry point (GH-41)** —
  `Agent.__init__` docstring now fully describes the `lifespan_extras` parameter
  with a minimal `asyncio.create_task` example for periodic background tasks.
  DESIGN.md §10.4 (new) identifies `lifespan_extras` as the single scheduling
  entry point and cross-references `commitments_lifespan` and `webhooks_renewal_lifespan`
  as canonical patterns. No new public API surface added.

- **docs: round-3 conformance audit deferred findings recorded in REVIEWS.md** —
  All 10 findings from the v0.5.12 `/agent-stack-check` gate (1 High deferred,
  5 Medium, 4 Low) are acknowledged with rationale. No Critical or blocking items.

## [0.5.9] — 2026-06-16

### ✅ Features

- **f53fd07 harness: adapt template skills into .claude + /debug threshold raised to round 4+** —
  Copied 16 skills and `wave-cycle.js` from `template/.claude/` into the SDK's `.claude/`
  project directory (SDK-adapted variants: `agent_sdk/` paths, SI invariants, sdk-test recovery).
  `/debug` escalation threshold raised from round 3 to round 4+ across `wave-cycle.js`,
  `wave/SKILL.md`, `implement/SKILL.md`, and `debug/SKILL.md` in harness, template, and `.claude/`.

- **14cef76 harness: full sync with template — advisor agents, conformance skills, reference docs** —
  Added 4 advisor agent specs (`a2a-advisor`, `a2ui-advisor`, `ag-ui-advisor`, `mcp-advisor`),
  5 conformance check skills (`a2a-check`, `a2ui-check`, `ag-ui-check`, `mcp-check`,
  `agent-stack-check`), 2 authoring skills (`add-artifact`, `sdk-issue-scan`), 3 protocol
  reference docs, and `.harness-manifest.json` to `harness/`. Template received `new-agent`
  skill and `.claude-plugin`; drifted files (`analyst.md`, `planner.md`, `agent-verify`,
  `upgrade`, `acceptance`) synced from harness as source of truth.

- **b491085 acceptance skill: dual-path A2A + AG-UI testing** —
  `/acceptance` now drives every scenario on both transports concurrently. A2A path uses
  `POST /v1/message/stream` (JSON-RPC SSE, `TaskArtifactUpdateEvent`/`TaskStatusUpdateEvent`);
  AG-UI path uses `POST /run` SSE. Both must score ≥ 7 for `passed=true`. New
  `transport-divergence` failure class. Added `--transport a2a|agui|both` flag.

- **575fa5c acceptance-api workflow: dual-path A2A + AG-UI** —
  Rewrote `acceptance-api.js` from AG-UI-only to dual-path. Schema changed from
  `minScore/turns` to `a2aMinScore/aguiMinScore/a2aTurns/aguiTurns`. A2A leg drives
  `POST /v1/message/stream` with `httpx` streaming and persists `taskId` across turns.
  AG-UI leg uses `ChatDriver.agui_turn()`. Both run per-scenario; summary log shows
  A2A min + AG-UI min + diverged count. `args.transports` wires the `--transport` flag through.

## [0.5.6] — 2026-06-16

### 🟡 Protocol surface changes

- **a2a: GET /v1/tasks — implement tasks/list (GH-32, A2A-D3)** —
  Replaced -32004 stub with real implementation using `store.list_tasks_for_identity`.
  Response matches A2A v0.3.0 `ListTasksResponse` shape:
  `{tasks, totalSize, pageSize, nextPageToken}`. Cursor-based pagination
  with identity isolation (tasks are never visible to other identities).

- **a2a: transport type narrowed to Literal (A2A-D1)** —
  `AgentCard.preferred_transport` and `AgentInterface.transport` now use
  `Literal["JSONRPC","GRPC","HTTP+JSON"]` instead of unconstrained `str`.
  Prevents invalid transport values from passing Pydantic validation.

- **a2a: route name confirmed spec-correct (GH-32 / A2A v0.3.0 §11.3.2)** —
  `POST /v1/tasks/{task_id}:subscribe` retained. `:resubscribe` was never
  implemented. Spec fetch from `a2aproject/A2A` confirmed `:subscribe` is the
  correct HTTP+JSON binding name.

- **mcp: per-surface PRM routing (GH-33)** —
  A2A (`/v1/`) and AG-UI (`/ag-ui/`) surfaces now emit the bare PRM
  (`/.well-known/oauth-protected-resource`) in their `WWW-Authenticate` challenge.
  MCP (`/mcp`) continues to use the path-suffixed form (`…/mcp`). Bare PRM
  endpoint added at `GET /.well-known/oauth-protected-resource`.

- **mcp: AS metadata resource_indicators_supported (GH-35)** —
  `GET /.well-known/oauth-authorization-server` now includes
  `"resource_indicators_supported": true` (RFC 8707 §5).

- **ag-ui: skill tags flow to AgentSkill (GH-34)** —
  `@tool(tags=[...])` values propagate to `AgentSkill.tags` on the agent card.
  Tier label (`tier-N`) moved to `x-sdk.tier` — never appears in `tags`.

- **ag-ui: TaskStatus.error field for failed tasks (GH-38)** —
  Failed tasks now populate `status.error: {code, message}` in the A2A wire.
  `WireError` is set in all failure branches: `DoneEvent(ok=False)`,
  `except AgentError`, and `except Exception`.

- **a2ui: updateComponents upsert-by-id semantics** —
  `a2ui.js` renderer now maintains a `_componentMap` (JS `Map` keyed by
  `component.id`) per surface. `updateComponents` upserts each component
  by id rather than replacing the full list. Fixes stale-component accumulation.

- **a2ui: duplicate createSurface guard** —
  A second `createSurface` for an already-open surface now logs a protocol-error
  warning and skips processing instead of silently overwriting the surface state.

- **a2ui: updateDataModel null-vs-absent semantics** —
  `MISSING` sentinel distinguishes absent `value` (delete the pointer) from
  explicit `null` (set to null). `apply_data_model_update()` on the server
  and the JS `pointerSet` in `a2ui.js` both apply delete-vs-null semantics.

### 🟠 Security

- **config: HTTPS enforcement for public deployment** —
  `_deployment_invariants()` in `config.py` raises `ValueError` at boot if
  `PUBLIC_URL` is non-local and does not start with `https://`. Loopback
  hosts (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`) are exempt.

### ✅ Features

- **a2ui: SurfaceRegistry duplicate-open tracking** —
  `SurfaceRegistry` class in `translator.py` tracks open surfaceIds and
  emits a `warnings.warn` on duplicate `open()` calls.

- **a2ui: catalog compact schemas + few-shot examples** —
  `catalog.py` injects `_COMPACT_SCHEMAS` and `_FEW_SHOT_EXAMPLES` into the
  system prompt section for `KpiCard`, `TimeSeriesChart`, `ComparisonTable`,
  and `FundPerformance` — giving the LLM concise wire contracts and worked examples.

- **mcp: tool name length check at decoration time** —
  `ToolSet.tool()` now raises `ValueError` immediately if the tool name exceeds
  64 characters (was only checked at `build_app()` time).

- **ag-ui: interrupt expiresAt forwarded to wire** —
  `InterruptEvent.expires_at` field added; populated from `record.interrupt_deadline`
  after `store.mark_interrupted()`; forwarded as `expiresAt` (milliseconds) in the
  AG-UI INTERRUPT event.

- **ag-ui: parentMessageId always present** —
  `TOOL_CALL_START` events always emit `parentMessageId` (as `null` if no prior
  message) — removes the optional-omission ambiguity.

### 🔧 Fixes

- **a2ui: message type guard regression fixed** —
  `a2ui.js` validation guard removed `|| !msg.type || typeof msg.type !== "string"`.
  A2UI messages have no `type` field; the check was always truthy and silently
  skipped every received message. Corrected guard: `version` field only.

- **ag-ui: assistant history content as multimodal array** —
  `chat.js` line ~481: `content: buf.text()` changed to
  `content: [{type:"text", text: buf.text()}]` — matches the multimodal array
  shape used for user turns and required by AG-UI spec.

- **ag-ui: resume status "approved" → "resolved"** —
  Three test files updated from `status: "approved"` to `status: "resolved"`
  with `payload: {decision: "approved"}`. `"resolved"` is the canonical AG-UI
  interrupt-resolution status literal.

- **ag-ui: expires_at falsy guard** —
  `ag_ui.py`: `if event.expires_at:` changed to `if event.expires_at is not None:`
  to avoid suppressing a valid `0.0` deadline.

- **a2ui: paintSurface fallback on missing root** —
  `a2ui.js`: removed `|| entry.components[0]` fallback when no `id:"root"` component
  exists. Now renders a visible `.a2ui-fallback` error node instead of silently
  promoting an arbitrary component.

- **a2ui: MIME dispatch heuristic removed** —
  `chat.js`: removed `|| Array.isArray(part.data)` from the A2UI artifact dispatch
  condition. Dispatch is now by MIME type string only.

- **ag-ui: _fold_history safe text extraction** —
  `ag_ui.py`: `p.get("text", "")` instead of `p["text"]` in `_fold_history`
  prevents `KeyError` on history parts without a `text` key.

### 🧪 Test / CI

- `tests/test_w014_fixes.py` — 7 new tests: subscribe route, resubscribe gone,
  tool tags flow, tags default empty, card skill tags, AS metadata, failed task error
- `tests/test_a2ui_wire.py` — 11 new tests: SurfaceRegistry duplicate warning,
  `apply_data_model_update` null/absent/scope (M2/M3), system prompt schema
- `tests/test_a2a.py` — `test_tasks_list` and `test_tasks_list_isolation` added;
  `test_error_table` updated for `GET /v1/tasks` 200 + `ListTasksResponse` shape
- `tests/test_ag_ui.py`, `tests/test_ag_ui_resume.py` — resume status `"resolved"` + payload
- `tests/test_http_protocol.py` — per-surface PRM routing assertions (C3-H2, C3-H5)
- `docs/protocols.md` — `:subscribe` is spec-correct per A2A v0.3.0 §11.3.2
- `REVIEWS.md` — Round 2 conformance audit log; all Critical/High fixed; 7 deferrals acknowledged

## [0.5.5] — 2026-06-15

### 🟡 Protocol surface changes

- **a2a: correct error code on terminal-task message/send (A2A-F1)** —
  `_resume_or_error` now returns `-32004` (UnsupportedOperation, HTTP 501) when
  `message/send` targets a completed/failed/canceled task. Previously used
  `-32002` (TaskNotCancelable, HTTP 409) which per A2A §2 maps exclusively to
  `tasks/cancel`. Tests updated: `test_a2a.py` GH-16 assertion and
  `test_protocol_fixes_w9_group_a.py` now assert `(501, -32004)`.

### ✅ Features

- **a2ui: system prompt Profile v1 wire-contract injection (A2UI-F1)** —
  `agent_sdk/a2ui/catalog.py` exports `get_system_prompt_section()` returning a
  compact `## A2UI Output Format` block listing every registered FROZEN component
  with its required/optional field types. `app.py` appends this section to the
  system prompt when content types are registered, giving LLMs prompt-level
  guidance on PascalCase component names and field shapes.

### 🔧 Fixes

- **ag-ui: history message content uses canonical multimodal array (AG-UI-F-M-01)** —
  User messages pushed to `aguiMessages` history in `chat.js` now use
  `content: [{type:"text", text}]` (AG-UI multimodal form) instead of
  `content: text` (flat string). `_fold_history` server-side already handled
  both; canonical form eliminates divergence and future-proofs multimodal payloads.

### 🧪 Test / CI

- `tests/test_a2ui_wire.py` — 2 new tests: `get_system_prompt_section()` always
  returns a str; returns non-empty string containing "A2UI" + "KpiCard" when types
  are registered
- `tests/test_a2a_error_envelope.py` — terminal-task `message/send` asserts -32004

## [0.5.4] — 2026-06-15

### 🟡 Protocol surface changes

- **a2a: comprehensive /v1/ HTTP error envelope (GH-25 / A2A-C1/C2/H1)** —
  `_a2a_auth_envelope` now wraps ALL `StarletteHTTPException` on `/v1/` paths
  (not just 401/403). Code map: 401/403→-32000, 404→-32001, 405→-32004,
  415→-32005, others→-32603. Added `RequestValidationError` handler returning
  400 + -32602 with field **locations only** — never echoes submitted values
  (SI-2). `tasks_get` guards against `task_id` containing `:` (returns -32004
  instead of -32001 for route-collision hits).

- **mcp: remove malformed `scope=""` from WWW-Authenticate challenge (GH-27 / MCP-C1)** —
  `_prm_challenge(prm_url)` helper extracted in `middleware.py`; returns
  RFC 6750 §3-conformant `Bearer resource_metadata="{prm_url}"` with no
  empty-scope param. All five challenge sites (middleware, 2× oauth, admin)
  now use the shared helper. Flip-flopping root cause fixed: SC-C3 test
  invariant corrected to assert ABSENCE of `scope=`.

- **ag-ui: TOOL_CALL_ARGS + TOOL_CALL_END consumer handling (GH-31 / AG-UI-C1/C2)** —
  `chat.js` now accumulates `TOOL_CALL_ARGS.delta` fragments per `toolCallId`
  in a `Map` and parses the full JSON only at `TOOL_CALL_END`, with a try/catch
  fallback for partial/malformed JSON.

- **a2ui: MetricItem.trend wire type corrected to string (A2UI-H3)** —
  `@field_serializer("trend")` on `MetricItem` collapses any `KpiTrend` instance
  to its `direction` string before serialization. Profile v1 specifies `trend`
  as `"up"/"down"/"flat"` string only; the object form is now Python-internal only.

- **a2ui: TimeSeriesChart series fields excluded from wire (A2UI-H4)** —
  `TimeSeriesDataPoint.series` and `TimeSeriesChart.series` marked
  `Field(exclude=True)`; both are Python-internal only. Wire output now matches
  the Profile v1 contract: `data:[{date,value,label?}]` only.

### 🟠 Security

- **mcp: Origin validation on /mcp endpoints (MCP-H2)** —
  `mcp_post` and `mcp_get` now validate the `Origin` header against
  `app.state.cors_origins` (MCP spec §10/§12 MUST for DNS-rebinding defense).
  Requests without an `Origin` header (non-browser tools) pass through unchanged.
  `app.state.cors_origins` set at app construction in `app.py`.

- **a2a: 422 validation errors never echo user input (SI-2)** —
  New `_a2a_validation_envelope` handler for `RequestValidationError` on `/v1/`
  returns field **locations** only (never values) in the -32602 message.

### 🔧 Fixes

- **ag-ui: AGENT_ARTIFACT wire payload documented as camelCase (AG-UI-H1 / C2)** —
  `docs/protocols.md` corrected: `AGENT_ARTIFACT.value` fields are `dataType`,
  `toolName`, `data` (camelCase wire) — not snake_case as previously documented.
  `DESIGN.md` updated to match.

- **a2ui: JSON fallback for unknown structured components (GH-28 / A2UI-H1)** —
  `a2ui.js` `paintSurface` now renders unknown components with a non-null object
  value as formatted JSON in a `<pre class="a2ui-json">` block instead of
  discarding structured data via the text-only fallback.

### 🧪 Test / CI

- `tests/test_a2a_error_envelope.py` (new, 7 tests) — 405/422/404 envelope,
  -32602 no-value-echo, task_id colon guard, MCP Origin validation
- `tests/test_http_protocol.py` (new, 7 tests) — WWW-Authenticate exact format
  (no scope=), path-suffixed PRM URL, MCP SSE GET 401, cross-surface consistency
- `tests/test_oauth_flow.py` (new, 7 tests) — token endpoint grant types, DCR
  redirect URI validation, scope omission from token response
- `tests/test_a2ui_wire.py` (new, 13 tests) — KpiTrend string-only wire,
  TimeSeriesChart no-series wire, translate() output structure
- `tests/test_mcp_conformance_w9.py` SC-C3 — flipped to assert `scope=` ABSENT
  (fixing the root cause of repeated GH-27 flip-flopping)
- `tests/test_card_console.py` — routing parity tightened to assert
  `case "TOOL_CALL_ARGS"` and `case "TOOL_CALL_END"` appear in switch body

### — Other

- `ec10fd0` docs: LRN-015/016/017 — MCP coercion failure, SSRF single-predicate, wave gate architecture
- `ab84eb9` chore: v0.5.3 — harness /upgrade pytest path + /agent-verify --no-stack-check clarification

## [0.5.2] — 2026-06-15

### 🔧 Fixes

- **mcp: structuredContent coercion failure now returns isError:True (GH-23)** —
  `_handle_tools_call()` previously swallowed `model_validate` exceptions with
  `except: pass`, returning `isError: False` with no `structuredContent` — a spec
  MUST violation (MCP §4). Now returns `isError: True` with the exception class name;
  attacker-influenced field values are no longer echoed into model context.

### 🔧 Security

- **mcp: SSRF defense — `safe_get()` utility + shared IP-block predicate (GH-24)** —
  Added `agent_sdk/common/http.py` exporting `safe_get(url)` and `_is_non_public_ip()`.
  `safe_get` resolves hostname via async DNS, blocks RFC 1918 / loopback / link-local
  (169.254.x.x IMDS) / reserved / multicast targets, and disables redirect-following.
  The duplicate IP-block logic in `SourceAdapter._on_request` and
  `validate_credential_url` is refactored to call the shared predicate.
  `harness/CLAUDE.md` SI-1 updated to document `safe_get` as the approved escape hatch
  for user-URL fetching outside a `SourceAdapter`.

### 🧪 Test / CI

- `tests/test_w011_mcp_ssrf.py` — 19 new tests: coercion-failure `isError:True`,
  coercion-success `structuredContent` present, `_is_non_public_ip` parametric
  (13 addresses), `safe_get` loopback/IMDS/RFC1918 blocked, public URL passes,
  `follow_redirects=False` enforced.

## [0.5.1] — 2026-06-15

### 🧪 Test / CI

- **wave-cycle.js — pytest gate architecture (GH-19)** — Added `GATE_SCHEMA`
  `{exitCode, passCount, failCount, failures}` and schema-gated gate agents at
  unit-redteam and phase-redteam checkpoints. Gate RED → targeted test-fix
  agent dispatched; `testsRed` flag propagated to return object.

- **wave-cycle.js — post-proto-fix gate (GH-20)** — Added schema-gated gate
  agent between `proto:fix` and `recheck` dispatch so a protocol fix that
  breaks tests is caught before the audit loop continues.

- **wave-cycle.js — implement prompts scoped (GH-21)** — Implement agents now
  run only scoped tests (`pytest -q tests/test_<specific>.py`) during
  implementation; the centralized gate catches suite-wide regressions.
  Full-suite runs during implementation were driving unnecessary memory pressure.

- **wave-cycle.js — pre-archive gate (GH-22)** — Schema-gated gate agent runs
  at the top of the Archive phase. Suite RED blocks archive and re-run is
  required, preventing red-suite commits from reaching the learning store.

## [0.5.0] — 2026-06-15

### 🟡 Protocol surface changes

- **A2A — bare-Message sync-reply path** — `message/send` now supports an optional
  `sync_reply` hook on `Agent`. When registered, the hook is called before task creation;
  returning a non-`None` string skips the task and returns a bare `Message` directly
  (A2A v0.3.0 §2 quick-response pattern). Closes GH-SC-A1.

- **A2A — Content-Type guard → -32005 / HTTP 415** — `_parse_send()` now inspects
  `Content-Type` before attempting `json.loads`. A non-`application/json` body returns
  `-32005 ContentTypeNotSupported` at HTTP 415 instead of the previous `-32602 /
  HTTP 400`. Closes GH-15.

- **A2A — terminal-task re-message returns -32002 / HTTP 409** — `_resume_or_error()`
  now distinguishes "task not found" (`-32001` / 404) from "task is terminal"
  (`-32002 TaskNotCancelable` / 409). Closes GH-16.

- **AG-UI — TOOL_CALL_ARGS injected on resume** — the synthetic interrupt-resume
  tool-call sequence now emits `TOOL_CALL_START → TOOL_CALL_ARGS(delta="{}") →
  TOOL_CALL_END` satisfying the ≥1 ARGS requirement for strict consumers. Closes GH-14.

- **AG-UI — `_fold_history` ContentPart extraction** — `content` arrays in
  `messages[].content` are now extracted as `"".join(p["text"] for p in parts)` instead
  of `str(content)`. Fixes garbled input for CopilotKit-style frontends. Closes GH-17.

- **AG-UI — SSE heartbeat** — `sub.get()` is now wrapped in
  `asyncio.wait_for(timeout=15.0)`; a `TimeoutError` emits an SSE comment keepalive
  (`": ping"`) and resumes waiting. Keeps long idle runs alive across proxies.

- **MCP — `tools/list` cursor pagination** — `_handle_tools_list` now returns
  `nextCursor` (base64-encoded int offset) and accepts `cursor` in the request.
  PAGE_SIZE = 64. Agents with ≥65 Tier-1 tools now paginate correctly per MCP §3.

- **MCP — `structuredContent` for non-BaseModel artifacts** — when `emits=` is
  declared but the artifact is not already a `BaseModel`, the route attempts
  `entry.decl.emits.model_validate(artifact)` before the `structuredContent` gate.
  Dicts from tool returns that match the `emits` schema now produce `structuredContent`.

- **MCP — tool name ≤64 chars enforced at registration** — `registry.py` raises
  `ValueError` if a tool name exceeds 64 characters, catching MCP spec violations
  at boot rather than at `tools/list` time.

- **A2UI — pre-wire assertion** — `_validate_a2ui_wire()` asserts the message list
  is non-empty and every message carries a `version` key before delivery. Bad tool
  returns now surface as agent errors rather than silent partial updates.

- **A2UI — `a2ui_allowed_components` setting** — `BaseAgentSettings` gains
  `a2ui_allowed_components: list[str] | None`. When set, `build_app()` validates
  that all registered content types are in the allow-list.

- **A2A — scalar artifact DataPart** — `build_artifact()` for plain scalar results
  (non-ContentModel, non-mapping) now emits both a `TextPart` and a
  `DataPart(kind="data", data={"value": payload}, metadata={"mimeType": "application/json"})`.

- **A2A — `/v1/card` requires identity** — `extended_card()` now carries
  `Depends(require_identity)`, enforcing authentication before exposing extended
  card fields.

### ✅ Features

- **`ChatDriver.resume()`** — new method to continue an interrupted task by
  `taskId` + `contextId`, sending back the user's reply after an `input-required`
  interrupt. Implements D7.8 of the A2A consumer spec.

- **`ChatDriver` credentials forwarding** — `ChatDriver.__init__` now accepts a
  `credentials: dict[str, str]` kwarg; entries are merged into every request header,
  enabling per-call credential injection for the A2UI extension and other custom
  headers.

- **`ChatDriver` agent.json fallback** — card discovery now falls back from
  `/.well-known/agent-card.json` to `/.well-known/agent.json` on 404, matching the
  server's legacy alias route.

- **`ChatDriver` `additionalInterfaces` transport selection** — when
  `preferredTransport` is unsupported, `a2a_turn()` walks `additionalInterfaces` to
  find a supported transport instead of failing immediately.

- **`A2AError` class constants** — `A2AError` now exposes named class-level
  constants for all 7 A2A error codes (`TASK_NOT_FOUND`, `TASK_NOT_CANCELABLE`,
  `PUSH_NOT_SUPPORTED`, `UNSUPPORTED_OPERATION`, `CONTENT_TYPE_NOT_SUPPORTED`,
  `INVALID_AGENT_RESPONSE`, `NOT_AUTHORIZED`).

- **`/provision` skill** — interactive credential-store interview for a new agent:
  bootstraps admin API key, seeds model backend keys, and writes
  `workspace/adr/ADR-001-<env>-credentials.md`. Targets Azure Table Storage
  as the primary store.

- **Credential ADR discipline** — a `PostToolUse` hook in `.claude/settings.json`
  fires after every admin credential write and prompts updating `ADR-001`.
  `/provision` Phase 3 auto-writes the inventory file.

- **`harness/CLAUDE.md` template** — agent-facing harness conventions file seeded
  into downstream agent `.claude/CLAUDE.md` at `/new-agent` time.

### 🔧 Fixes

- **Azure Table Storage enforced as primary store** — `build_app()` now emits a
  `WARNING` at boot when the credential store falls back to SQLite outside
  `DEV_MODE`. The admin console boot-check route surfaces this warning.

- **`Agent.close()` hardened** — `close()` guards every sub-close call against
  `AttributeError` and `Exception`, preventing partial-init teardown from masking
  the original exception.

- **MCP `WWW-Authenticate` `scope=""` removed** — the Bearer challenge at
  `middleware.py:65` no longer appends `, scope=""` when no scopes are enforced,
  per RFC 6750 §3.

- **GH-18: `pytest -q tests/` → `pytest -q` in wave-cycle.js** — all 5 agent
  prompt templates in `harness/workflows/wave-cycle.js` that passed an explicit
  `tests/` path to pytest now use bare `pytest -q`, respecting `addopts` ignores
  from `pyproject.toml`. Closes GH-18.

### 🧪 Test / CI

- **Zero-tolerance mypy + warnings gate** — `mypy` and `filterwarnings = ["error"]`
  are both hard gates in `/sdk-test`; any new type error or deprecation warning
  blocks release.

- **`/sdk-test` Leg 3 — static conformance at release** — protocol conformance is
  now gated once at SDK release (via `/agent-stack-check` on the SDK source) rather
  than per downstream agent upgrade. `/upgrade` runs `--no-stack-check`.

- **`/sdk-release` is the only commit+push path** — wave completion stages changes;
  `/sdk-release` is the only flow that commits, tags, and pushes, ensuring the full
  3-leg test gate always runs before any code reaches `origin/main`.

- **5 new test modules** — `test_protocol_fixes_w9_group_a.py`,
  `test_ag_ui_group_b.py`, `test_mcp_conformance_w9.py`,
  `test_a2ui_group_d.py`, `test_emits_return_type.py` — covering the w009 protocol
  fixes. 491 tests total.

---

## [0.4.4] — 2026-06-14

### Fixed

- **OData parameterization in `AzureTableCommitmentStore`** — all OData filter strings
  in `list()`, `claim_due()`, and `reap_stale_firing()` now use named parameters
  (`@partition_key`, `@status`, `@now`, `@cutoff`) with a `parameters=` dict instead
  of string interpolation. The `now` parameter in `claim_due()` was previously
  injectable via its public signature; `status` in `list()` was injectable but
  only internally sourced today. Manual `replace("'", "''")` escaping removed —
  the `azure-data-tables` SDK handles OData escaping client-side.

- **Test hardening** — `test_claim_due_only_returns_due_pending` and
  `test_list_filters_by_*` updated to assert parameterized form;
  `partition_key` parameter presence asserted in filter tests;
  `test_list_odata_escapes_single_quote_in_identity_binding` renamed to
  `test_list_parameterizes_single_quote_in_identity_binding` with updated docstring.

---

## [0.4.3] — 2026-06-14

### Added

- **Tool signature validation at registration** — `ToolSet` now rejects invalid tool
  signatures at decoration time: required keyword-only params that are not `SourceAdapter`
  subclasses, required positional params that are not pydantic `BaseModel` subclasses,
  and `*args`/`**kwargs` all raise `TypeError` immediately.

- **`validate_namespace()` in credential store** — `source_name` values are now validated
  against `^[a-z_][a-z0-9_]{0,63}$` at both `register_source()` and `resolver_for_source()`
  time. Rejects hyphens, uppercase, and digit-leading names before they can reach OData
  filter strings.

### Fixed

- **API key fast-reject on format mismatch** — `ApiKeyStore.verify()` now uses
  `^ak_([0-9a-f]{16})_[A-Za-z0-9_-]+$` regex; tokens that don't match the format
  return `None` immediately without scanning the credential store. Eliminates the
  timing oracle between "wrong format" and "key not found."

- **OData injection in `AzureTableCredentialStore.list_fields()`** — switched from
  string-interpolated `PartitionKey eq '{namespace}'` to parameterized
  `PartitionKey eq @partition_key` with `parameters={"partition_key": namespace}`.

- **Test mock hardened** — `_query_entities` in `test_azure_credential_store.py` now
  raises `AssertionError` if called without a `parameters` dict, making any future
  regression back to string interpolation loudly visible.

---

## [0.4.2] — 2026-06-14

### Fixed

- **A2A `:subscribe` path** — `POST /v1/tasks/{id}:subscribe` is the spec-correct
  HTTP+JSON binding (A2A spec §11.3.2). Route confirmed as `:subscribe`; a stale
  `:resubscribe` alias was removed so only the spec-correct path is registered.

- **Bootstrap 401 carries `WWW-Authenticate`** — `admin.py` bootstrap-path rejection
  (invalid/expired token) now includes `Bearer resource_metadata="..."` in
  `WWW-Authenticate`, completing the P6-03 (`resource_metadata` on all 401s) fix.

- **AG-UI resume: synthetic `TOOL_CALL_START/END` before orphan `TOOL_CALL_RESULT`**
  — on interrupt-resume runs, `TOOL_CALL_RESULT` was emitted into the new SSE stream
  with no preceding lifecycle events (those occurred in the prior interrupted stream).
  `_RunMapper` now tracks `_seen_starts` and injects synthetic `TOOL_CALL_START` +
  `TOOL_CALL_END` before any `TOOL_CALL_RESULT` whose START was not emitted in the
  current stream.

- **`ChatDriver.agui_turn` handles `RUN_FINISHED` interrupt outcome** — the event loop
  now has a `RUN_FINISHED` branch: when `outcome.type == "interrupt"`, the `"interrupt"`
  emit key fires with the first interrupt object; the loop always breaks on `RUN_FINISHED`
  regardless of outcome type.

- **`build_artifact` docstring** — corrected to describe the post-P6-02 dual-part
  contract (TextPart + DataPart always; no "TextPart only" path for ContentModel).

### Changed

- **`/redteam` skill** (`harness/` and `template/`) — added pre-release scope rule
  (LRN-002): full-scope run mandatory at release gate; wave-scoped run only covers
  changed code and is not sufficient.

- **`workspace/learning/LRN-006`** — Check section rewritten with correct
  `A2uiCapabilities` construction (no non-existent `.a2ui_enabled` attribute).

---

## [0.4.1] — 2026-06-14

### Fixed

- **MCP `Mcp-Protocol-Version` response header on `initialize`** (GH #4) — header now reflects the
  version negotiated in the body (e.g. `2025-06-18`), not the request-header fallback default
  (`2025-03-26`). Root cause: `_negotiated_version()` in `routes/mcp.py` read the *request* header
  (absent on first contact) and the result was locked into `base_headers` before dispatch.
  Fix: after `_handle_initialize` resolves `protocolVersion`, override the response header to match.

- **`x-agui.customEvents` schema** (GH #5) — entries are now `{name, valueSchema}` objects instead
  of a flat `string[]`. AG-UI CUSTOM event conformance requires `valueSchema` on each entry.

- **`ContentModel` artifacts always emit `DataPart`** (GH #6) — `build_artifact()` previously only
  appended a `DataPart` when the A2UI extension was activated by the client. Plain A2A clients now
  receive a raw `DataPart` (model dump) alongside the `TextPart`, satisfying A2A §D3.

- **`WWW-Authenticate` carries `resource_metadata` on all 401 responses** (GH #7) — auth middleware
  previously added `resource_metadata` only for `/mcp` paths; all other protected routes (A2A,
  AG-UI, admin) returned bare `Bearer realm="agent"`, breaking RFC 9728 OAuth discovery for
  non-MCP clients.

- **`Access-Control-Expose-Headers` in CORS preflight 204** (GH #8) — the OPTIONS preflight
  response now includes `Access-Control-Expose-Headers: WWW-Authenticate, Mcp-Session-Id,
  X-A2A-Extensions`, matching the non-preflight path. Previously absent, which silently blocked
  some user-agents from reading the `WWW-Authenticate` header.

### Added

- **`python -m agent_sdk bump-patch`** — increments the patch segment of the SDK version in
  `pyproject.toml` (e.g. `0.4.1 → 0.4.2`). Used by the `.githooks/pre-push` hook and wave
  commit workflow to keep the version monotonically increasing.

- **`.githooks/pre-push`** — git hook that auto-bumps the patch version and commits the change
  before every push to `main`. Activate with `git config core.hooksPath .githooks`.

- **`workspace/learning/` LRN-001–LRN-006** — codified learnings from GH #4–#8: HTTP wire-level
  test coverage, pre-release full-scope redteam requirement, `resource_metadata` uniformity,
  CORS preflight expose-headers, MCP version header/body sync, ContentModel DataPart invariant.

- **`tests/test_protocol_wire.py`** — HTTP wire-level tests for all five protocol surfaces
  (CORS, auth challenge format, MCP version negotiation, agent card shape, ContentModel artifact
  parts). Complements `test_protocol_fixes_w6.py` (9 unit-level regression tests).

- **Acceptance skill mandatory `/agent-stack-check` gate** — both `harness/skills/acceptance/SKILL.md`
  and `template/.claude/skills/acceptance/SKILL.md` now mandate a full-scope `/agent-stack-check`
  pass before acceptance can be marked complete, even when the wave did not touch protocol surfaces.

---

## [0.4.0] — 2026-06-14

### Added

- **Azure Table Storage persistence backends** — `AzureTableCredentialStore`,
  `AzureTableCommitmentStore`, `AzureTableSubscriptionStore` replace SQLite for multi-replica
  Azure Container Apps deployments. Auto-detected from `AZURE_STORAGE_CONNECTION_STRING`
  (connection string) or `AZURE_STORAGE_ACCOUNT_NAME` (managed identity). AES-256-GCM
  encryption envelope preserved end-to-end. ETag optimistic concurrency preserves
  at-most-once commitment firing across replicas. Install with `pip install agent-sdk[azure]`.

- **`migrate-store` CLI** — `python -m agent_sdk migrate-store [--data-dir ./data]
  [--dry-run] [--force]` migrates existing SQLite credential, commitment, and subscription
  data to Azure Table Storage.

- **`NS_MODEL` namespace + model-backend credential store** — LLM API keys
  (OpenAI, Azure OpenAI, Anthropic) are now stored in the encrypted credential
  store under the reserved `__model__` namespace, never in `.env`. The admin
  console gains a "Model Backend" section (`GET/PUT /admin/api/credentials/__model__/*`)
  with fields for `openai_api_key`, `azure_openai_api_key`, and `anthropic_api_key`.
  `NS_MODEL` exported from `agent_sdk`.

- **OpenAI / Azure OpenAI as built-in model backends** — set `OPENAI_MODEL`
  (or `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT`) in `.env` (non-secret
  operational vars) and seed the API key once via `/admin → Model Backend`. No
  `model_client=` plumbing in `main.py` required; `Agent.build_app()` resolves
  the key from the credential store automatically.

### Changed

- **`BaseAgentSettings`** — gains three new optional fields for Azure Storage auto-detection:
  `AZURE_STORAGE_CONNECTION_STRING` (`SecretStr | None`), `AZURE_STORAGE_ACCOUNT_NAME`
  (`str | None`), `AZURE_STORAGE_TABLE_PREFIX` (`str`, default `"agent"`). Also gains five
  non-secret fields for OpenAI/Azure backends: `OPENAI_MODEL`, `OPENAI_BASE_URL`,
  `AZURE_OPENAI_ENDPOINT`, `AZURE_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`. Removed
  guidance to put API keys in `.env` via `SecretStr` subclass fields — that is now an
  SI-6 violation.
- **`Agent._build_model_client()`** — accepts `credential_store` and resolves OpenAI
  key from `__model__/openai_api_key` (or `azure_openai_api_key`) automatically.
  Bedrock path unchanged.

---

## [0.3.0] — 2026-06-13

### Changed

- **Credential store clarity** — `SourceAdapter.credential()` docstring now
  explains the full lifecycle (admin console → encrypted store → decrypt on
  call). `BaseAgentSettings` comments clarify that `MASTER_KEY` encrypts the
  store (not an upstream API key) and that Bedrock uses IAM (no key in `.env`).
  `.env.example` gains a prominent box listing what belongs and what does not.
  `CLAUDE.md` credential model table adds a "How to access it" column plus
  four labeled anti-pattern examples. SI-4 reference adds a step-by-step
  store lifecycle and common anti-patterns; SI-6 reference lists what does
  belong in `.env` to contrast with upstream keys.

---

## [0.2.0] — 2026-06-13

### Added

- **`ArtifactLoader`** — prompts live in `src/artifacts/*.md` as Jinja2
  templates (StrictUndefined, frontmatter-aware, compiled once at init).
  `Agent` gains `artifacts_dir=` and `artifact_vars=`; `persona=` remains
  supported for backward compat. `ArtifactLoader` exported from
  `agent_sdk`. Template and AlphaGeo example migrated.
  Harness gains `/add-artifact` opt-in migration skill.

- **`/acceptance` skill** — autonomous acceptance gate, the final step in
  the agent development lifecycle (after `/provision` + `/agent-verify`).
  Generates 30+ seed scenario files across 7 dimensions (happy path per
  tool, multi-turn depth, edge cases, A2UI content type coverage, skill
  activation, interrupt/resume, error/degraded upstream), then drives live
  multi-turn AG-UI conversations against the provisioned agent and
  judge-scores every turn 1–10 for content coherency. Self-healing fix
  loop (max 5 rounds) classifies each failure (`code-bug`,
  `content-type-gap`, `persona-gap`, `upstream-issue`, `bad-scenario`),
  dispatches targeted fix agents, restarts the server, and re-tests only
  the failing scenarios — autonomously, without human intervention.
  Does not exit until all scenarios score ≥ 7 or the round budget is
  exhausted. Persona-gap escalations are non-blocking.
  `--ux` path runs the same scenarios sequentially in a single Playwright
  browser session against the admin test console, adding a rendering
  fidelity score (1–10) that exercises the full intended purpose of every
  A2UI Standard Profile component type emitted (click, sort, filter, form
  submit, hover tooltip, deleteSurface lifecycle, console error check).
  Both scores must be ≥ 7 per turn for a UX pass. OBO agents require a
  one-time manual browser login; everything after is autonomous.
  Results written to `workspace/scenarios/results/run-NNN.json` with
  per-scenario score history across runs.

- **`acceptance-api.js` workflow** — parallel fan-out runner invoked by
  `/acceptance`. Each scenario agent drives a 3–5 turn conversation via
  `ChatDriver` over `POST /ag-ui/run` (SSE), persisting message state
  across turns in `/tmp/`, scoring each reply, generating contextual
  follow-ups from the actual agent response, and classifying failures.
  Returns `SCENARIO_RESULT_SCHEMA`-validated structured objects.

- **`/provision --env [dev|prod]`** — new environment flag controls which
  ADR credentials file is written. After minting the first admin API key,
  `/provision` now writes `workspace/adr/ADR-000-<env>-credentials.md`
  (gitignored) so skills like `/acceptance` can authenticate autonomously
  on future runs without re-bootstrapping. On 409 (already bootstrapped),
  checks for an existing ADR-000 before halting. Auto-adds the credentials
  glob to `.gitignore` if absent.

- **`A2AError`** exported from `agent_sdk.testing` — typed exception
  carrying `code` and `message`; raised by `ChatDriver` on A2A error
  responses and interrupt states. Now part of `testing.__all__`.

- **Chat console markdown rendering** — agent replies in the test console
  are rendered as Markdown (bold, italic, inline/fenced code, headings,
  lists, blockquotes). `streamingBubble` re-renders incrementally so
  formatting resolves live while the model is typing, not only at end of
  stream. No external deps; all model output via DOM text nodes (XSS-safe,
  strict CSP compliant).

- **Chat console responsive full-height layout** — transcript and SSE
  trace panels fill the full viewport height with composer pinned at the
  bottom. Responsive breakpoints: ≤900 px single-column stacked panels,
  ≤600 px trace panel hidden.

### Fixed

- **A2A / AG-UI / A2UI / MCP full-stack conformance** — 17 findings from
  `/agent-stack-check` + 8 iterative `/redteam` cycles resolved to zero
  Critical/High across all four protocol layers and six seams:
  - Body size caps (1 MB) on `message/send` and `ag-ui/run` (MCP-consistent).
  - DNS-rebinding guard in `SourceAdapter._on_request`; reads `dev_mode`
    Pydantic attribute (was incorrectly `DEV_MODE` env-var name).
  - SI-7 build-time check: `SourceAdapter.__init__` requires non-empty
    `allowed_hosts` or `_no_http = True` opt-out for non-HTTP adapters.
  - `CommitmentsSource._no_http = True` to pass the SI-7 check.
  - Bootstrap token written to `stderr` (was `stdout` — leaked to captured
    output).
  - Log handler changed to `stderr` to prevent log lines in captured output.
  - SI-2: unknown tool name in loop sanitized before log interpolation
    (truncate to 64 chars, replace control chars).
  - AG-UI `AGENT_ARTIFACT` wire uses camelCase `{dataType, toolName, data}`
    (was snake_case; AG-UI camelCase invariant).
  - AG-UI `A2UI_UPDATE` envelope wraps message array: `{messages: [...]}`.
  - Agent card removes `urn:agui:run:v1` from `capabilities.extensions[]`;
    AG-UI is advertised via `x-agui.endpoint` only (wrong slot per A2UI F2).
  - `forwarding.bind()` called in `ag_ui_run` before creating the worker
    task so credentials are bound in the correct context.
  - `serverInfo` in MCP `initialize` response includes `title` field
    (MCP 2025-06-18).
  - `register_content_type` enforces global component-name uniqueness.
  - Console `chat.js` AGENT_ARTIFACT consumer reads camelCase keys
    (`dataType`, `toolName`).
  - `a2uiClientCapabilities` in console includes `version`, `catalogs`,
    `tier` on both A2A and AG-UI paths.

- **`ChatDriver` A2A consumer conformance** (D7 hard-MUST floor):
  - Card discovery: fetches and caches `/.well-known/agent-card.json`
    before first request; selects transport from `preferredTransport`.
  - Message/Task discrimination: checks `result.get("kind") == "message"`
    before accessing `task["id"]`.
  - `X-A2A-Extensions` header sent on `message:send`; response echo read
    to confirm activation (`_a2ui_active` flag).
  - Interrupt states (`input-required`, `auth-required`) fire `"interrupt"`
    emit and raise `A2AError` instead of polling to timeout.
  - `extract_a2ui` dispatches on `DataPart.metadata.mimeType`
    (`"application/a2ui+json"`) at the part level, not artifact level.
  - `A2UI_MIME` sourced from `A2UI_MIME_TYPE` constant in
    `models/content_types` (removes local duplicate).

---

## [0.1.0] — 2026-06-13

Initial release.

### Added
- `Agent` / `build_app()`: single FastAPI app exposing A2A v0.3.0
  (HTTP+JSON), AG-UI (SSE), A2UI v0.9.1 Standard Profile v1 artifacts,
  MCP (2025-06-18, Streamable HTTP) behind OAuth 2.1, the agent card, and
  the admin console.
- `ToolSet` / `@tool` with tiers (1 = query: A2A+MCP, 2 = composite: A2A
  only), `emits=` content types, console `sample=`, adapter injection via
  keyword-only annotations, `ToolInterrupt` for input-/auth-required
  pauses with typed resume handlers.
- `SourceAdapter` base: allowed-hosts enforcement on every hop, redirect
  pinning, retry-once policy, namespaced credential resolution from the
  AES-256-GCM encrypted store.
- Loop policies: max turns, tiered tool timeouts, wall-clock deadline
  (suspended during interrupts), cumulative token budget across resumes,
  task-local result cache.
- Auth: API keys (single-use bootstrap token on zero-key startup), OAuth
  2.1 AS for `/mcp` (S256 PKCE, refresh rotation with family revocation,
  two-value audience), kind-tagged identities with per-surface assertions,
  rate limiting with trusted-proxy-aware client IPs.
- Standard Profile v1: 14 frozen content types; domain-card extension API
  (`ContentModel` subclass + own `catalog_id` + `register_content_type`).
- `agent_sdk.testing`: `FakeModelClient`, `reply`, `tool_call`,
  `ChatDriver` (multi-turn AG-UI/A2A driver for integration tests and
  `python -m agent_sdk test-chat`).
- Admin console (vanilla JS, strict CSP) at `/admin`: keys, credentials,
  tool try-out, self-check.
- Repo-level `template/` (the ~10-file agent footprint) and `docs/`.
- Claude Code harness plugin (`harness/`) with 18 seeded skills covering
  the full agent development lifecycle: scaffold → implement →
  zero-tolerance redteam → conformance → acceptance → ops.
- AlphaGeo climate-risk agent (`examples/alphageo/`) as the worked
  reference implementation and SDK CI target.
- `contrib/` (EXPERIMENTAL): `action_gate`, `obo`, `commitments`,
  `webhooks` — validated by the m365 reference agent port.
