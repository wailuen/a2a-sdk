# Changelog

All notable changes to `agent-sdk`. SemVer applies to the stable core
(DESIGN.md §4.0); provisional surfaces (`agent_sdk.testing`, console
internals, `contrib/`) may change in minors with notice here.

## [0.5.44] — 2026-07-24

### 🔴 Breaking changes
- **`DataPart.data` narrows from `dict[str, Any] | list[Any]` to `dict[str, Any]`**
  (`agent_sdk/models/a2a.py`) — part of the GH-128 fix for the non-conformant bare-array A2UI
  wire shape, detailed in full under "Protocol surface changes" below. Both directions change:
  outbound, every A2A `DataPart` this SDK emits for A2UI now wraps the message array as
  `{"messages": [...]}` instead of delivering it bare; inbound, a `DataPart` whose `data` is a
  bare array now fails Pydantic validation (`-32602`, Invalid Params) instead of being accepted.
  **Migration:** any A2A client reading A2UI delivery must change from `part.data` to
  `part.data.messages`. RT-005 (redteam, low, versioning discipline): flagged that shipping a
  breaking wire-shape change under a same-minor patch bump (0.5.43 → 0.5.44, not 0.6.0) could
  surprise a consumer pinning `~=0.5.43`. Resolved by keeping the version at 0.5.44 rather
  than bumping to 0.6.0 — consistent with this project's established convention of surfacing
  breaking changes via an explicit `🔴 Breaking changes` section with a Migration callout rather
  than reserving them for a minor/major bump (precedent: 0.5.40's `TaskStore.interrupt_ttl_remaining`
  breaking change, also shipped under a same-minor patch bump, see below). This section is that
  callout, given its own top-level heading — matching 0.5.40's placement, and promoted out from
  inside "Protocol surface changes" where the fuller writeup still lives — precisely so a reader
  scanning only `Breaking changes` headers across releases does not miss it. Redteam follow-up
  (low, versioning discipline — a second pass on RT-005): citing 0.5.40 as *precedent* still left
  the top-of-file SemVer promise ("SemVer applies to the stable core (DESIGN.md §4.0)") and this
  entry's own practice in tension for any reader who checks §4.0 without reading changelog
  precedent — a consumer pinning `~=0.5.43` has no reason to expect a stable-core wire type to
  narrow without a major bump just because a *different* prior release also did it. Resolved for
  good, not just for this release: DESIGN.md §4.0 now states a standing, explicit **wire-shape
  conformance exemption** — a stable-core wire-shape break driven by external protocol conformance
  (not a voluntary redesign) may ship under a patch/minor bump provided it carries a dedicated
  `🔴 Breaking changes` heading + Migration callout, exactly as this entry does. §4.0 is the rule
  now; this entry and 0.5.40's are its precedent, not its justification — future breaking wire-shape
  conformance fixes cite §4.0 directly instead of re-litigating this argument per release. The §4.0
  exemption is a signed-off, owned decision (not merely this CHANGELOG note): **REVIEWS.md Round 7**
  records the rejected alternative (a major bump for every stable-core wire break) and the accepted
  risk to consumers pinning `~=0.5.x`.

### 🟡 Protocol surface changes
- `split_a2ui_delivery()` (new, `agent_sdk/a2ui/translator.py`): discovered during the GH-126
  redteam pass, tracked separately as it is unrelated to GH-126's scope. `translate()` computes
  a per-artifact A2UI sequence — `createSurface` → `updateComponents` → `updateDataModel` →
  `deleteSurface` — as one logical `list[dict]`, but A2UI v0.9.1's client contract folds ONE
  delivered array atomically and paints once after the fold. Delivering all four messages in a
  single array (the prior behavior) meant a strictly spec-conformant Path-A renderer — built from
  the public spec alone, with no knowledge of this SDK's internals — would unmount the surface via
  `deleteSurface` during the fold, before it was ever painted: **nothing would render, for every
  A2UI artifact this SDK emits**, on any consumer that didn't happen to special-case this SDK's
  bundling. `split_a2ui_delivery()` splits that sequence into an `open` array
  (createSurface/updateComponents/updateDataModel) and a `close` array (deleteSurface), and both
  delivery callers now send them as two independently-folded wire units, open before close:
  `agent/runner.py::build_artifact` emits two A2A DataParts on the artifact instead of one;
  `routes/ag_ui.py`'s `ArtifactEvent` branch emits two `A2UI_UPDATE` CUSTOM events instead of one.
  On the A2A side each array is now delivered as `DataPart(data={"messages": [...]})`. **This is
  a breaking wire-shape change, not just a count change** (see the dedicated `🔴 Breaking changes`
  section above): every released version through v0.5.42
  (back to the initial commit — verified via `git show v0.5.42:agent_sdk/agent/runner.py`) emitted
  `DataPart(data=a2ui_messages, ...)` with `data` as a bare `list`, which was already non-conformant
  — the A2A base spec requires `DataPart.data` to be a JSON object (`a2a.json`/`types.ts`, pinned
  v0.3.0 tag) — but shipped that way across every tagged release to date. 0.5.44 fixes the shape by
  wrapping the message array under a `"messages"` key, matching the AG-UI CUSTOM event's
  `value.messages` convention exactly (same key, same shape). **Migration for A2A consumers:** any
  client parsing `DataPart.data` as an array for A2UI must change to reading `part.data.messages`
  (was `part.data`) — this will silently break on upgrade otherwise. `agent_sdk/models/a2a.py`'s
  `DataPart.data` is now typed `dict[str, Any]` (was `dict[str, Any] | list[Any]`) so the old
  bare-array shape fails at construction time, closing GH-128. The bare-array shape was caught by
  `/sdk-test` Leg 3's static conformance gate (a2a-advisor) before the v0.5.44 tag and fixed under
  GH-128. This is also a wire-*count* change
  for every A2UI emission (previously one DataPart/event per artifact, now up to two) — flagged
  here as a protocol surface change, not a plain fix, since any consumer that assumed exactly one
  DataPart/event per A2UI artifact must now expect two. The agent card's A2UI extension hint
  (`deleteSurfaceSemantics`, GH-113) is updated from `"post-paint"` to `"split-delivery"` to match
  — non-normative in both cases, but the value itself changed.
  Covered by `tests/test_a2ui_wire.py` (`test_split_a2ui_delivery_isolates_delete_surface`,
  `test_split_a2ui_delivery_empty_input`) plus updated assertions in
  `tests/test_gh113_delete_surface_semantics.py`, `tests/test_a2ui_group_d.py`,
  `tests/test_protocol_fixes_w6.py`, `tests/test_protocol_wire.py`, `tests/test_a2a.py`. See
  DESIGN.md §5.4/§7.1 for the full wire contract. Filed and closed as fixed: GH-127, GH-128.
  (`agent_sdk/a2ui/translator.py`, `agent_sdk/agent/runner.py`, `agent_sdk/routes/ag_ui.py`,
  `agent_sdk/a2ui/catalog.py`, `agent_sdk/console/static/a2ui.js`, `agent_sdk/console/static/chat.js`,
  `agent_sdk/models/a2a.py`, `agent_sdk/testing/chat.py`, `DESIGN.md`)
- RT-003 (redteam, low, `agent_sdk/models/a2a.py`): the `DataPart.data` narrowing above
  (`dict[str, Any]`, was `dict[str, Any] | list[Any]`) is symmetric — it also tightens INBOUND
  parsing, not just the outbound A2UI wire shape migration documented above. A `Message.parts`
  `DataPart` whose `data` is a bare array — the exact shape A2UI v0.9.1's own A2A binding mandates
  for an inbound `action` DataPart (see LRN-134) — now fails Pydantic validation at parse time and
  is rejected as `-32602` (Invalid Params) instead of being accepted. No functional regression
  today: the SDK has no inbound A2UI-action `DataPart` consumer (`Message.parts` `DataPart.data` is
  never read anywhere in `agent_sdk`), so nothing that previously worked stopped working. Recorded
  because it forecloses a future spec-conformant inbound A2UI action `DataPart` without first
  adding a bare-array-tolerant parse — if inbound A2UI actions are ever supported, they must be
  parsed through such a path (e.g. a dedicated inbound type/validator that accepts a bare array
  before Pydantic sees it), not through this tightened `DataPart` model. Pinned by
  `test_inbound_data_part_bare_array_rejected_as_invalid_params` (`tests/test_protocol_wire.py`),
  which documents the current end-to-end rejection via `POST /v1/message:send`.

### 🔧 Fixes
- GH-126 / RT-001: `apply_data_model_update()` (`agent_sdk/a2ui/translator.py`)
  now matches A2UI v0.9.1's `updateDataModel` semantics on both value- and
  path-handling.
  - Omitting `value` (the `MISSING` sentinel) deletes the key at `pointer`
    (`target.pop(leaf, None)`, a no-op if already absent) instead of leaving
    the target unchanged. `apply_data_model_update()` has no production
    callers today — `translate()`, the SDK's only emit path, always sets an
    explicit `value` — so this closes a latent server/renderer divergence.
  - A2UI v0.9.1 overrides RFC 6901 for `updateDataModel.path`: "omit `path`
    or use `/` to replace the whole data model." `""` and `"/"` are now both
    handled, identically, as a genuine whole-model replace —
    `model.clear(); model.update(value)` — evaluated before the
    root-relative check, so neither spelling falls through to ordinary
    pointer traversal. Because this is an in-place mutator (it cannot
    reassign the caller's `model` reference), *value* must be a `dict` for
    a whole-model replace; any other type raises `ValueError`. `MISSING` is
    a no-op on both spellings. An earlier revision of this fix reasoned from
    the console renderer's `pointerSet` (`agent_sdk/console/static/a2ui.js`)
    alone, whose `pointerTokens("/")` returned a literal one-segment token
    list (addressing the ordinary child key `model[""]`) rather than folding
    to the whole-model-replace empty-token-list case — that premise was
    itself non-conformant to the spec, not a valid reference. Both
    `pointerTokens` and this helper now implement the spec's `"/"` override
    directly against the A2UI spec text, and agree with each other as a
    consequence of that, not as the justification for it.
  - Parent-key navigation for ordinary (non-whole-model) pointers is a
    single traversal shared by set and delete, scaffolding missing
    intermediate dicts unconditionally and then branching on `MISSING`
    (pop) vs. set — mirroring `pointerSet`'s shape, so e.g. deleting
    `/a/b/c` on `{}` converges with the renderer's `{a: {b: {}}}` on both
    sides. Three documented, latent VALUE/TRAVERSAL divergences remain (not
    live bugs — `translate()` never emits a numeric-token, array-shaped,
    scalar-shadowed, or whole-model-replace pointer): RT-002a — a numeric path
    token (e.g. the `0` in `/metrics/0`) is treated as a literal string dict key
    here, not a list index; RT-002b — a pre-existing scalar (non-dict, non-list)
    intermediate node is preserved by this helper (set raises, delete
    no-ops) where `pointerSet` destructively overwrites it with `{}`/`[]`;
    RT-002c — a whole-model replace (`""`/`"/"`) with a non-`dict` value
    raises `ValueError` here (the helper is an in-place mutator and cannot
    write a non-object `dataModel`) where `pointerSet`'s empty-tokens branch
    (`value === undefined ? doc : value`) returns the scalar verbatim
    (`pointerSet({}, "/", "scalar")` → `"scalar"`). Each of the three — RT-002a
    (`..._on_numeric_token`), RT-002b (`..._on_scalar_intermediate_delete`), and
    RT-002c (`..._on_whole_model_replace_non_dict`) — is pinned by its own live
    node cross-check that recomputes the `pointerSet` reference at test time, so
    none can drift silently against a hand-copied literal. A FOURTH divergence —
    the deliberate `..`-token parent-escape guard (RT-JSON-POINTER-001, next
    bullet) — is a security divergence rather than a value/traversal one; the
    `apply_data_model_update()` docstring enumerates all four together so the
    tally cannot drift.
  - RT-JSON-POINTER-001: the parent-escape guard rejects ONLY a decoded
    token EQUAL to `..` (e.g. `/foo/../bar`, `/..`). This check is complete:
    it runs after `~1`/`~0` decoding and `..` has no tilde form, so nothing
    can hide a parent-escape segment from it. A prior revision additionally
    tested each decoded token for the `/..` / `../` SUBSTRINGS; those clauses
    were false-positives only — a `/` inside a decoded token can arise solely
    from `~1` (a literal key character, the split on `/` having already
    happened), so they fired exclusively on legitimate `~1`-formed literal
    keys and never on a genuine escape. Concretely `/foo~1../bar` decodes to
    the literal key `foo/..` then `bar`; the renderer's `pointerSet` accepts
    it and writes `{"foo/..": {"bar": ...}}`, and this helper now converges
    (sets the same literal key) instead of wrongly rejecting it. Rejecting a
    genuine `..` token remains a deliberate stricter-than-renderer guard (the
    renderer treats `..` as a literal key), pinned as a live-cross-checked
    divergence.
  - RT-EMPTY-SEGMENT-001: removed the over-broad `//`-prefix guard. An empty
    path segment is not a component-root escape — per RFC 6901 it addresses
    the empty-string key `model[""]`, an ordinary key within the component
    root, never the envelope or a parent. The old guard rejected only a `//`
    PREFIX while the helper already accepted every equivalent spelling that
    reaches the same empty-string key (`/a//b` → `model["a"][""]["b"]`, `/a/`
    → `model["a"][""]`), so it blocked one spelling of a legitimate operation
    and was no boundary. `//`-prefixed pointers now converge with the
    renderer's `pointerSet` (`pointerSet({}, "//bar", "X")` →
    `{"": {"bar": "X"}}`), cross-checked live. The genuine parent-escape guard
    (a decoded `..` token) is unaffected.
  - RT-002 (a later, separate redteam finding on the fix above — distinct
    from the RT-002a/RT-002b/RT-002c divergence labels earlier in this
    entry): the intersection of BOTH spec rules — path omitted/`"/"` (whole
    data model) AND `value` omitted (`MISSING`, delete-at-path) — is
    deliberately defined as a no-op. The spec states two independent rules:
    "omit `path` or use `/` to replace the whole data model" and "omit
    `value` to delete the key at path." Composed, those two rules are
    genuinely ambiguous, not spec-decided: read one way, an
    `updateDataModel` with both omitted addresses the whole model, where
    there is no single key at path for the delete rule to target — the
    delete has no referent, so the operation no-ops (this SDK's reading);
    read the other way, a spec-literal peer could treat omit-path +
    omit-value as "clear the whole model." The no-op is therefore an
    SDK-defined resolution of that ambiguity, not a spec certainty — both
    this helper and the console renderer's `pointerSet` empty-tokens branch
    (`value === undefined ? doc : value`) agree on the no-op reading, which
    is a consequence of choosing it consistently across the SDK, not proof
    the spec mandates it. This is NOT "clear the model" under the SDK's
    reading: the spec-supported way to unambiguously clear the model
    remains an explicit whole-model replace with an empty object
    (`value={}`), honored as `model.clear(); model.update({})`, so a
    caller who wants a clear is never stranded by the no-op reading. Pinned
    by
    `test_apply_data_model_update_whole_model_missing_is_noop_per_spec_no_key_at_path`,
    which documents the SDK's chosen reading of the ambiguous composition
    (not a spec oracle), alongside the existing `..._missing_value_is_noop`
    renderer-convergence tests. Cross-implementation interop risk only: a
    spec-clarification request for this composition is worth filing
    upstream with the A2UI spec maintainers so a genuinely conformant
    third-party peer has an authoritative answer rather than two SDK
    surfaces agreeing by internal convention.

  Covered by `test_apply_data_model_update_empty_pointer_replaces_whole_model`,
  `test_apply_data_model_update_slash_pointer_replaces_whole_model`,
  `test_apply_data_model_update_empty_and_slash_pointer_are_symmetric`, their
  `_missing_value_is_noop`/`_rejects_non_dict_value` counterparts, the
  convergence-table tests
  (`test_apply_data_model_update_converges_with_pointer_set_reference` and its
  live-node counterpart,
  `test_apply_data_model_update_converges_with_live_pointer_set_reference`),
  and the RT-002a/RT-002b/RT-002c divergence pins. See the docstring of
  `apply_data_model_update()` for the full contract.
  (`agent_sdk/a2ui/translator.py`, `agent_sdk/console/static/a2ui.js`)

### ⚠️ Behavior changes
- RT-004: the `MISSING` sentinel's effect on `apply_data_model_update()`
  changed from a documented no-op to delete-at-path (`target.pop(leaf, None)`).
  Both `apply_data_model_update` and `MISSING` are importable submodule
  utilities on `agent_sdk.a2ui.translator` — NOT part of the package public
  API: neither is in any `__all__`, and `agent_sdk.a2ui.__init__` re-exports
  only `A2uiCapabilities`, `get_system_prompt_section`, and `translate`. They
  are therefore provisional per the SemVer note at the top of this file, so a
  behavior change ships in a patch. Still flagged explicitly because the
  symbols ARE importable: any external code that reached into the submodule and
  imported `MISSING` relying on the previously-documented no-op now silently
  deletes the key at `pointer` instead (the old behavior was a latent bug, and
  there are no in-repo callers). The whole-model-replace forms (`""`/`"/"`)
  with `MISSING` remain a no-op (see the value-semantics contract in the
  `apply_data_model_update` docstring).

## [0.5.43] — 2026-07-20

### 📖 Docs
- GH-124: `for_custom_emit()`'s (`agent_sdk/a2ui/translator.py`) deliberate
  Extended-tier bypass on the AG-UI CUSTOM-event path — a client that
  declares `tier="core"` still receives in-catalog Extended Standard-Profile
  types (e.g. `WaterfallChart`), unlike `allows()` on the A2A DataPart path,
  which does enforce Extended-tier gating — was re-flagged as a HIGH
  conformance bug by a fresh `/agent-stack-check` run. On review this is the
  intentional, already-tested LRN-049 decision, not a defect:
  `tests/test_rt001_ag_ui_custom_extended_gate.py` already pins
  `WaterfallChart` emitting under `tier="core"`, and AG-UI's silent-ignore of
  unknown CUSTOM events is the safety net A2A DataPart lacks, so withholding
  data here has no protective value and only breaks graceful degradation.
  GH-124 closed as not-a-bug. Strengthened the `for_custom_emit()` docstring
  with this rationale so it isn't re-flagged. No behavior change.
  (`agent_sdk/a2ui/translator.py`)

## [0.5.42] — 2026-07-20

### 🟠 Security
- GH-122: consent-page `Content-Security-Policy: form-action` now covers the **entire** redirect chain (consent-page GET, 401 re-render, error redirect, success redirect) via a shared `_redirect_security_headers()` helper, closing a gap where Chromium/Electron enforce `form-action` against the form-owning document's CSP across the whole chain (crbug.com/932518) rather than a later 30x hop's CSP alone. The advertised origin is now rebuilt from sanitized components (`_validated_origin()`) instead of interpolating the raw `netloc`/`.hostname`, closing a CSP-header-injection vector (RFC 3986 `reg-name` permits `;`/space characters that `urlparse().hostname` doesn't reject). IPv6-literal `redirect_uri`s are now rejected outright (fail-closed) rather than best-effort sanitized. (`agent_sdk/routes/oauth.py`)

### 🔧 Fixes
- GH-118: `sdk-wave.js`/`wave-cycle.js` (and harness/template mirrors)'s `archiveIntent` import-resolution gate now handles sub-package imports and both absolute/relative import forms via a four-way disambiguation ladder, kept in sync across runner copies by `test_workflow_sync.py`. (`.claude/workflows/sdk-wave.js`, `.claude/workflows/wave-cycle.js`)

### 🧪 Test / CI
- Codifies LRN-126 through LRN-132 from wave w035's redteam rounds (`workspace/learning/`).

## [0.5.41] — 2026-07-15

### ✅ Features
- GH-113: `a2ui_extension()` (`agent_sdk/a2ui/catalog.py`) now advertises a new extension param `deleteSurfaceSemantics: "post-paint"` alongside `supportedCatalogIds`/`acceptsInlineCatalogs` — carries the show-then-close `deleteSurface` convention (DESIGN.md §5.4/§7.1), previously inferable only from the admin console's `a2ui.js` renderer source, on the card itself. `deleteSurfaceSemantics` is a **non-normative, SDK-specific hint** — it is not a field A2UI v0.9.1 or Standard Profile v1 defines, and a consumer implementing its own renderer (Path B or third-party) must already know this SDK's convention to interpret the key/value; it is not a spec-defined discovery mechanism, just a wire hint that spares reverse-engineering the renderer source. Additive, non-breaking. (`agent_sdk/a2ui/catalog.py`, `DESIGN.md`)

### 🔧 Fixes
- GH-119: `agent_sdk/app.py`'s CORS allow-list now unions the deployment's own resolved base-URL origin (`{scheme}://{netloc}` of `settings.resolved_base_url`) alongside the existing `CORS_ORIGINS` entries and `https://claude.ai`, so the bundled console's same-origin requests aren't 403'd by `guard_origin()` on a non-claude.ai deployment that never explicitly listed itself in `CORS_ORIGINS`. **Operator-visible:** the effective allow-list is now wider than `CORS_ORIGINS` alone. RT-001: only the ORIGIN component is unioned, never the full URL — browser `Origin` headers are always path-less (RFC 6454), so a path-prefixed `PUBLIC_URL` (e.g. a reverse-proxy deployment at `https://gw.example.com/agents/x`) contributes only `https://gw.example.com`, or the entry could never equal a real `Origin`. (`agent_sdk/app.py`)
- GH-120 / GH-121: a `long_running` tool may return a `DeferredResult` whose handle resolves to ANOTHER `DeferredResult` (nested deferral). `ToolEntry.invoke_any` (`agent_sdk/agent/registry.py`) now follows that chain up to `_MAX_DEFERRED_RESOLUTIONS` (2 handles total) instead of returning the nested object verbatim — previously the un-awaited nested handle's `repr` was baked into the MCP `tools/call` wire text under a false `isError: false`. Nesting beyond the bound closes/cancels the handle and raises `AgentError`, which every caller (`routes/mcp.py`, `routes/admin.py`, the commitments executor) now maps to its `isError`/`ok:false` path — `routes/admin.py`'s `try_tool` did NOT handle `DeferredResult` at all before this wave (see the `invoke_any` signature-change entry below); only `routes/mcp.py` and the commitments executor were previously correct. (`agent_sdk/agent/registry.py`)
- RT-001 (redteam, C-012): the nested-resolution loop was extracted to a new module-level `resolve_deferred_result(result, *, tool_name, handle_timeout)` (registered as **C-012**) so `runner._run_deferred_background` — the A2A/AG-UI background awaiter for a `DeferredEvent` — shares the IDENTICAL nesting-depth bound and rejection point as `invoke_any` instead of maintaining its own divergent branch. A `long_running` tool's nesting-depth contract can no longer drift by transport. The shared guarantee is scoped to DEPTH, not the timeout budget (see C-012 in `workspace/components/README.md`). (`agent_sdk/agent/registry.py`, `agent_sdk/agent/runner.py`)
- RT-001 (redteam, `agent_sdk/agent/registry.py`, **public signature change**, C-010): `ToolEntry.invoke_any(arguments, adapters)` gained two new keyword-only params, `timeout: float | None = None` and `policies: LoopPolicies | None = None`. When `timeout` is given it bounds the initial invoke/drain AND the DeferredResult-resolution handle(s) it awaits under ONE shared deadline — the handle gets only the budget remaining after the initial call, never a fresh `timeout` seconds on top (RT-003). When omitted (the commitments executor's call shape — unchanged), the initial call stays unbounded and only a returned `DeferredResult` is bounded, via `resolve_tool_timeout` against `policies` (or a default `LoopPolicies()`). Existing positional callers (`invoke_any(arguments, adapters)`) are source-compatible — both new params default to the prior unbounded/no-policy behavior. `routes/mcp.py`'s `_handle_tools_call` and `routes/admin.py`'s `try_tool` now both dispatch through `invoke_any(..., timeout=timeout)` instead of each re-implementing the `is_generator`/`DeferredResult` branch inline. Registered as **C-010** in `workspace/components/README.md`. (`agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/admin.py`)
- RT-001 (redteam, SI-2, `agent_sdk/routes/admin.py`): `POST /admin/api/tools/{name}/try` built its `ValidationError` response from raw Pydantic `e['msg']` under a `# never echo input values` comment that was false — `errors(include_input=False)` strips only the `input` key, NOT `msg`, so a tool's own `@field_validator` that interpolates the rejected value into its error message (e.g. `raise ValueError(f"invalid token {v!r}")`) reflected that value verbatim into the admin response. A tool argument can itself be a credential/token, making this an SI-2 leak on the admin surface. Routed through `safe_validation_message()` (`agent_sdk/agent/loop.py`), the same helper `routes/mcp.py` already used — keeps only `loc` + `type`. **Wire-visible:** the try-tool endpoint's validation-error shape changed from `{"error": {"category": "validation", "errors": [{"loc", "msg", "type"}, ...]}}` to `{"error": {"category": "validation", "message": <str>}}`. (`agent_sdk/routes/admin.py`)
- RT-001 (redteam, `agent_sdk/agent/loop.py`): an async-generator (`is_generator`) tool whose TERMINAL yield is a `DeferredResult` was not detected as deferred — only the coroutine branch ran the `isinstance(result, DeferredResult)` handoff. The raw `DeferredResult` leaked onto `ToolResultEvent`/AG-UI `TOOL_CALL_RESULT` and was `str()`-folded into the model conversation, and the handle was never awaited (`ResourceWarning: coroutine never awaited`; the long-running job never ran). The generator branch now runs the same handoff, so a generator tool's terminal `DeferredResult` behaves identically to a coroutine's across the MCP and A2A/AG-UI surfaces. (`agent_sdk/agent/loop.py`)
- RT-001 (redteam, `agent_sdk/agent/runner.py`): `_run_deferred_background`'s SUCCESS path built and serialized the terminal artifact (`build_artifact()` / `TaskArtifactUpdateEvent.wire()`) OUTSIDE any try/except, unlike the synchronous `run_task_worker`'s equivalent (guarded) `ArtifactEvent` branch. A raise here (e.g. `_validate_a2ui_wire` rejecting a malformed domain card) escaped the fire-and-forget `asyncio.Task` nobody awaits, stranding the A2A task in WORKING forever with every SSE subscriber queue left un-sentinel-closed until the TTL sweep. The build/serialize step is now wrapped: a `ValueError` maps to the existing `-32006` ("invalid agent response") code — mirroring `run_task_worker`'s mapping — anything else to `-32603` ("internal error"), both routed through the new `_fail()` helper (FAILED + synthetic `ToolResultEvent(ok=False)` + closed streams; SI-2: only a fixed string is echoed, never exception/handle text). (`agent_sdk/agent/runner.py`)
- RT-002 (redteam, wire behavior — AG-UI): on deferred-task **FAILURE** (timeout / cancellation / tool error / terminal-artifact build failure), `runner._run_deferred_background`'s `_fail()` now publishes a synthetic `ToolResultEvent(ok=False)` → AG-UI `TOOL_CALL_RESULT`, closing the tool-call lifecycle that the pre-`DeferredEvent` `TOOL_CALL_START` opened. Previously the failure path emitted no matching result, so strict AG-UI clients observed a `TOOL_CALL_START` with no `TOOL_CALL_RESULT`. `frame=None`, so A2A SSE consumers skip it; only the AG-UI RunMapper consumes it. (`agent_sdk/agent/runner.py`)
- RT-002 (redteam, `agent_sdk/agent/runner.py`): a FAILED task must never retain an artifact that was never delivered on any stream. The wave's initial reorder serialized the `TaskArtifactUpdateEvent` frame before mutating `task.artifacts`, closing the `.wire()`-raises sub-case — but the append still preceded `publish()`, so a `publish()` failure (a persistent `TaskStore` whose durable write fails) flipped the task to FAILED (sync path) / propagated out of the background task (deferred path) with a never-delivered artifact still attached. The append now runs only AFTER `publish()` has delivered the frame, at BOTH call sites (`run_task_worker`'s `ArtifactEvent` branch and `_run_deferred_background`'s success path). (`agent_sdk/agent/runner.py`)
- GH-110: `agent_sdk/routes/mcp.py`'s defense-in-depth Origin allow-list check (RT-004, shipped pre-0.5.x) was enforced on every MCP browser-reachable streaming surface but was missing from `agent_sdk/routes/ag_ui.py`'s `POST /ag-ui/run` and all 6 `agent_sdk/routes/a2a.py` handlers (`message_send`, `message_stream`, `tasks_list`, `tasks_get`, `tasks_cancel`, `tasks_resubscribe`) — an inconsistent partial hardening of RT-004's own stated intent ("every browser-reachable streaming surface"). `mcp.py`'s 5 duplicate inline checks are now extracted into a shared `guard_origin(request)` predicate (new `agent_sdk/common/origin.py`, C-009); `a2a.py`/`ag_ui.py` are newly guarded by 7 net-new call sites, not deduplicated from an existing copy. Behavior is unchanged for MCP; `a2a.py`/`ag_ui.py` now reject a present-but-disallowed `Origin` header with 403 (static `"origin not allowed"` detail — the untrusted header value is never interpolated into the response or a log line, SI-2) while an absent or allow-listed Origin still passes through unaffected. (`agent_sdk/common/origin.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/mcp.py`)
- RT-003 (folded into the GH-110 fix): `InterruptEvent.expires_at` (`agent_sdk/agent/events.py`) renamed to `expires_in` — the field has always held seconds-remaining-until-expiry (a relative duration computed by `TaskStore.interrupt_ttl_remaining`), never an absolute time, and the old name was a holdover from the 0.5.40 AGUI-1 fix that superseded its own wording without updating it. Also updated where it's set (`agent_sdk/agent/runner.py`) and read (`agent_sdk/routes/ag_ui.py`). Internal-only — `InterruptEvent` is not exported from any `__init__`, constructed only in `agent_sdk/agent/loop.py`, so this is not a public API break. The wire field (`Interrupt.expiresAt`, ISO-8601 string) is unaffected. (`agent_sdk/agent/events.py`, `agent_sdk/agent/runner.py`, `agent_sdk/routes/ag_ui.py`)
- RT-001 (redteam finding on this wave, reverted): a prior revision of the GH-110 fix also switched `agent_sdk/routes/a2a.py`'s `_now_iso()` and `agent_sdk/agent/runner.py`'s `_now()` from `datetime.now(timezone.utc).isoformat()` (microsecond precision, explicit `+00:00` offset) to the shared `iso_utc()` helper (fixed-width, no microseconds, literal `Z` offset) — a stable-core A2A wire format change (`TaskStatus.timestamp`, DESIGN.md §4.0) bundled untracked into an Origin-hardening todo, with no CHANGELOG entry and no conformance test pinning the new format. Reverted out of this wave; `_now_iso()`/`_now()` are unchanged (still `datetime.now(timezone.utc).isoformat()`). A future consolidation onto `iso_utc()` must land under its own tracked todo, its own CHANGELOG entry, and a passing conformance test. (`agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py`, `agent_sdk/common/iso8601.py`)
- GH-111: `mcp_get` and `mcp_delete` (`agent_sdk/routes/mcp.py`) never called the existing `_negotiated_version()` helper that `mcp_post` already uses, so a present-but-unrecognized `MCP-Protocol-Version` header value was silently accepted on those two verbs instead of the 400 `mcp_post` already returns for the same invalid-value case. Both now return `400 {"error": "unsupported MCP-Protocol-Version"}` (with a `MCP-Protocol-Version` response header naming the server's preferred version) when the header is present but unrecognized; an absent header is unaffected on both verbs (locked GH-77/w022 ruling — not re-litigated). `mcp_get`'s return type widened to `StreamingResponse | JSONResponse`. (`agent_sdk/routes/mcp.py`)
- GH-112: `ChatDriver.a2a_turn` (`agent_sdk/testing/chat.py`, a provisional surface — see header) walked the agent card's `additionalInterfaces` for a `JSONRPC`/`HTTP+JSON` fallback transport whenever `preferredTransport` was unsupported, but never acted on the result — every request unconditionally POSTed to `/v1/message:send` regardless of the computed value, so the walk executed but its outcome was discarded; the old regression test only passed because the unconditional POST would have succeeded either way, not because the fallback logic did anything. DESIGN.md's v1 non-goals already scope A2A client support to HTTP+JSON only, so the dead code is deleted rather than wired up: `a2a_turn` now raises `ValueError` for any `preferredTransport` other than `"HTTP+JSON"`, with no `additionalInterfaces` fallback. `agent_sdk/__main__.py`'s `test-chat --url`/`--a2a` help text now states the HTTP+JSON-only limitation. (`agent_sdk/testing/chat.py`, `agent_sdk/__main__.py`)
- F1 (post-release protocol re-audit, independently raised by `a2a-advisor` and `a2ui-advisor`): `store.close_streams()` calls inside the FAILURE-HANDLING paths themselves — `_run_deferred_background`'s `_fail()`, `run_task_worker`'s `except AgentError`/`except Exception` handlers, and `tasks_cancel`'s terminal publish — were not guarded by `try`/`finally`. A `publish()` failure INSIDE one of those already-failing paths (as opposed to a `publish()` failure that merely triggers entry into the path, which the existing RT-002 tests cover) could itself skip stream teardown, stranding SSE subscribers un-sentinel-closed until the TTL sweep. All four sites now wrap their terminal `publish()` call(s) in `try`/`finally: store.close_streams(...)`, mirroring the guard already present on the deferred-success path. Theoretical risk only — `InMemoryTaskStore`'s `publish()`/`close_streams()` never raise; this hardens custom/persistent `TaskStore` implementations under double-failure conditions. (`agent_sdk/agent/runner.py`, `agent_sdk/routes/a2a.py`)
- AG-UI advisor (post-release protocol re-audit, Low): `agent_sdk/routes/admin.py`'s `overview` and `selfcheck_info` diagnostics endpoints displayed the raw configured `settings.cors_origins` instead of the GH-119-resolved allow-list `guard_origin()`/`CorsMiddleware` actually enforce (which also includes the deployment's own resolved-base-URL origin). Cosmetic — the enforcement layer already read the correct resolved value — but the admin diagnostics could show a narrower list than what was actually allowed. Both endpoints now report `sorted(request.app.state.cors_origins)`. (`agent_sdk/routes/admin.py`)

### 🧪 Test / CI
- `tests/test_rt002_failed_task_no_stranded_artifact.py` — `.wire()`-raises and `publish()`-raises sub-cases for both the sync `ArtifactEvent` path and the deferred-background path; asserts a FAILED/erroring task retains no undelivered artifact
- `tests/test_rt002_deferred_failed_tool_result.py`, `tests/test_rt002_close_streams_finally_on_publish_failure.py`, `tests/test_rt002b_deferred_terminal_frame_no_duplicate.py`, `tests/test_rt002c_sync_worker_terminal_frame_no_flip.py` — synthetic failure `TOOL_CALL_RESULT`, `close_streams()` in `finally`, and no-duplicate/no-flip terminal-frame guarantees
- `tests/test_gh120_invoke_any_nested_deferred_result.py`, `tests/test_gh121_nested_deferred.py`, `tests/test_rt001_deferred_nesting_parity.py`, `tests/test_rt001_invoke_any_shared_timeout.py`, `tests/test_rt001_gen_tool_terminal_deferred_result.py` — nested-`DeferredResult` depth bound, cross-surface parity, shared-deadline budget, and the async-generator terminal-`DeferredResult` handoff
- `tests/test_rt002_invoke_any_deferred_result.py` — `invoke_any()` resolves a `DeferredResult` from a `long_running=True` COROUTINE tool (not just the generator form) end-to-end through the real `CommitmentExecutor`
- `tests/test_rt001_deferred_task_handle_cancel.py` — max-depth cleanup calls `.cancel()` (not just `.close()`) so an abandoned `asyncio.Future`/`Task`-backed handle, not only a coroutine one, is actually cancelled rather than left running unobserved
- `tests/test_admin_try_tool_deferred_result.py` — `try_tool`'s `DeferredResult` resolution (resolved value returned, never a raw repr) and prompt timeout handling
- `tests/test_admin_try_tool_validation_leak.py` — pins the SI-2 fix: a custom `@field_validator`'s rejected input value never appears in the `try_tool` response, which still names the offending field
- `tests/test_rt001_deferred_artifact_build_failure.py` — a deferred tool whose resolved value makes `build_artifact()` raise deterministically reaches FAILED with streams closed, mirroring `test_gh87_deferred_task.py`
- `tests/test_common_origin_guard.py` (new) — unit coverage for `guard_origin()` in isolation: absent Origin passes, allow-listed Origin passes, disallowed Origin raises `HTTPException(403, "origin not allowed")`
- `tests/test_gh110_origin_allowlist.py` (new) — 403 for a disallowed Origin and pass-through for absent/allowed Origin, across `POST /ag-ui/run` and all 6 `a2a.py` handlers
- `tests/test_http_protocol.py` — 4 new cases: `mcp_get`/`mcp_delete` with a bogus `MCP-Protocol-Version` → 400; regression cases confirming the no-header path on both verbs is unaffected
- `tests/test_chat_driver.py` — `test_sc_e3_additional_interfaces_fallback`/`test_sc_e3_no_fallback_raises` rewritten to assert `ValueError` for any non-`"HTTP+JSON"` `preferredTransport`, including when `additionalInterfaces` lists a supported transport
- `tests/test_gh113_delete_surface_semantics.py` (new), `tests/test_card_console.py` — `a2ui_extension()`/agent-card assertions that `params.deleteSurfaceSemantics == "post-paint"`
- `tests/test_rt001_a2a_timestamp_wire_format.py` (new) — pins `TaskStatus.timestamp` (via `message:send` and `tasks:cancel`) to the microsecond-precision, `+00:00`-offset form, guarding against the reverted `iso_utc()` switch silently reappearing
- `tests/test_f1_close_streams_double_failure.py` (new) — real store subclasses whose `publish()` raises on EVERY call (not just once, unlike the existing RT-002 stores) drive the F1 double-failure scenario across all three fix sites: `run_task_worker`'s generic exception handler, `_run_deferred_background`'s `_fail()` under `CancelledError`, and `tasks_cancel`'s terminal publish — asserting `close_streams()` still runs in every case

### — Other
- GH-114: added `workspace/learning/LRN-115-agui-capabilities-fail-closed-tier-none-default.md`, documenting GH-74's deliberate fail-closed `tier="none"` default in `agent_sdk/routes/ag_ui.py`'s `_capabilities()` as intentional — not a bug to "align" with `A2uiCapabilities.from_metadata(None)`'s fail-open default. Pure documentation debt; no code or test change.

## [0.5.40] — 2026-07-11

### 🔴 Breaking changes
- `TaskStore` (`agent_sdk/tasks/store.py`) gained a new concrete method `interrupt_ttl_remaining(task_id) -> float | None`, defaulting to `None` (unknown) so every pre-existing external `TaskStore` subclass keeps instantiating without modification. Subclasses that predate this hook now silently stop emitting `Interrupt.expiresAt` on AG-UI interrupt outcomes (previously they emitted a wrong, monotonic-clock-derived absolute value on that field — see the AGUI-1 entry below). Override `interrupt_ttl_remaining` to compute seconds-remaining from your store's own tracked deadline and clock to restore the field. `InMemoryTaskStore` (`agent_sdk/tasks/memory.py`) already overrides it.

### 🔧 Fixes
- GH-104: `agent_sdk/app.py`'s `_A2A_CODE` HTTP-status→JSON-RPC-error-code table had no `404` entry, so an unmatched `/v1/*` route fell through to the generic `-32603` (Internal Error) default instead of the spec-correct `-32601` (Method not found) — the same code MCP's own method-dispatch-miss fallback already uses (`agent_sdk/routes/mcp.py`). This reverses a deliberate w021/RT-003 ruling that left 404 unmapped without considering `-32601`. (`agent_sdk/app.py`)
- GH-105: `MarketBriefing`, the SDK's one "prose exception" `ContentModel`, leaked a bare-string `Tool.outputSchema`/`structuredContent` on the MCP surface (`{"type": "string"}` / a raw markdown string) — MCP 2025-06-18 requires both to always be JSON objects. Now wrapped as `{"markdown": <string>}` on the MCP surface (and the agent card's `x-sdk.outputSchema`, which shares the same registry method). The AG-UI/A2A `DataPart` wire contract (`agent_sdk/a2ui/translator.py`) is unchanged and still emits the bare markdown string — that ratification (RTGA-001/RTGA-005) only ever covered AG-UI/A2A, not MCP. (`agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/agent_card.py`)
- AGUI-1: `agent_sdk/routes/ag_ui.py` emitted `Interrupt.expiresAt` as an int epoch-ms, but the upstream `ag-ui-protocol` SDK types the field `Optional[str]` (confirmed against the installed `ag-ui-protocol==0.1.19` package) — a spec-strict consumer's reference Pydantic model would fail validation. The value also originated from a `time.monotonic()`-based deadline, so a naive int→str cast would have produced a near-1970 date. Fixed by threading a clock-agnostic *relative* TTL through the stack: `TaskStore.interrupt_ttl_remaining()` (see Breaking changes above) → `agent_sdk/agent/runner.py` sets `event.expires_at` to the relative seconds-remaining → `ag_ui.py` rebases it against wall-clock `time.time()` and serializes via the new `agent_sdk/common/iso8601.py` helper as ISO-8601 UTC. See `workspace/learning/LRN-111`, `LRN-112`. (`agent_sdk/routes/ag_ui.py`, `agent_sdk/common/iso8601.py`, `agent_sdk/agent/events.py`, `agent_sdk/agent/runner.py`, `agent_sdk/tasks/memory.py`, `agent_sdk/tasks/store.py`)
- AGUI-2: the admin console's `chat.js` folded a completed assistant turn back into `state.aguiMessages` using the multimodal list-of-parts content shape that's only valid for `UserMessage` — `AssistantMessage.content` is `Optional[str]` per the upstream spec. Every later `RunAgentInput` in the session replayed the malformed assistant message; invisible against this SDK's own server (which tolerates either shape) but would 422 on turn two against a spec-strict third-party AG-UI server. Fixed to `content: buf.text()` (plain string). (`agent_sdk/console/static/chat.js`)
- AGUI-3: `chat.js`'s AG-UI resume path sent `resume: [{ interruptId, status: "resolved", payload: text }]` — a bare-string `payload`. `agent_sdk/contrib/action_gate/gate.py::parse_decision()` only reads a decision out of a dict payload (`payload = raw_payload if isinstance(raw_payload, dict) else None`); a bare string was silently discarded and every action_gate-gated tool confirmation driven from the console's AG-UI tab landed on `Outcome.UNCLEAR` regardless of the user's actual approve/reject intent. Fixed to `payload: { decision: text }`. Found by this release's own static conformance re-audit, not the originating wave. (`agent_sdk/console/static/chat.js`)

### 🧪 Test / CI
- `tests/test_a2a_error_envelope.py::test_unknown_v1_route_404_a2a_envelope` — asserts `-32601` (was `-32603`)
- `tests/test_mcp_conformance_w9.py` — `MarketBriefing` outputSchema/structuredContent object-wrapper shape on MCP; agent-card `x-sdk.outputSchema` mirrors it (RT-004); AG-UI/A2A bare-string wire contract confirmed unchanged
- `tests/test_iso8601.py` (new), `tests/test_task_memory_store.py` (new) — the ISO-8601 helper and `interrupt_ttl_remaining` hook
- `tests/test_ag_ui.py`, `tests/test_ag_ui_group_b.py`, `tests/test_gh97_ag_ui_thread_run_id_synthesis.py` — updated for the relative-TTL `expires_at` contract
- `tests/test_card_console.py::test_agui_assistant_turn_fold_uses_plain_string_content` (new) — pins AGUI-2
- `tests/test_card_console.py::test_agui_resume_payload_matches_action_gate_contract` (new) — pins AGUI-3

### — Other
- This release's `/sdk-test` Leg 3 re-audit (full 4-advisor `/agent-stack-check`) also surfaced several Medium/Low findings unrelated to GH-104/GH-105/AGUI-1–3 — deliberately deferred, not fixed here, per `workspace/sdk-candidates.md` Candidates 4–8: an AG-UI/A2A Origin allow-list defense-in-depth gap (Medium), a missing `MCP-Protocol-Version` check on the MCP GET/DELETE verbs (Medium), a dead transport-selection code path in the `ChatDriver` test utility (Medium), a third-party-interop trap in A2UI's atomic per-artifact message bundling (Medium), and an undocumented-as-LRN capability-default divergence from GH-74 (Low). None affect this SDK's own server/console surfaces.

## [0.5.39] — 2026-07-11

### 🔧 Fixes
- `TimeSeriesDataPoint.value` (`agent_sdk/models/content_types.py`) is required-but-nullable on the frozen `time_series` Standard Profile v1 contract — a data-gap point must still carry `"value": null`, never omit the key. `_Wire.wire()`'s blanket `model_dump(..., exclude_none=True)` was silently dropping the key whenever `value` was `None`, which (a) violated MCP's declared `outputSchema` for any tool emitting a `TimeSeriesChart` via `structuredContent`, and (b) broke the same frozen contract on A2UI's wire delivery over both A2A DataPart and AG-UI CUSTOM (`A2UI_UPDATE`). Fixed via a `model_serializer(mode="wrap")` on `TimeSeriesDataPoint` that re-inserts `value: null` when the field is `None`, without disturbing the Python-level `is None` semantics `TimeSeriesChart.to_plain_text()` relies on. Surfaced independently by both the MCP and A2UI static conformance audits (`LRN-110`). (`agent_sdk/models/content_types.py`)
- `agent_sdk/routes/agent_card.py`: removed a dead `_is_placeholder` local left orphaned by the w024/GH-86 description-fallback refactor — `settings.is_placeholder_name` itself is unchanged and still used elsewhere.

### 🧪 Test / CI
- `tests/test_a2ui_wire.py::test_time_series_wire_data_keys_conform_to_profile` — updated to assert `value: null` survives the wire for a data-gap point (previously asserted the dropped-key bug as spec-conformant) and that a genuinely absent optional field (`label`) is still correctly excluded.

### — Other
- Static conformance audit (`/agent-stack-check . --static-only`, run as `/sdk-test` Leg 3 ahead of this release) also flagged `agent_sdk/a2ui/translator.py`'s `A2uiCapabilities.for_custom_emit()` as a possible Core/Extended tier-gating gap on the AG-UI CUSTOM path. Investigated and confirmed this is the deliberate, already-shipped behavior from `test_rt001_ag_ui_custom_extended_gate.py` (v0.5.20, `LRN-049`): AG-UI CUSTOM events are gated only on `tier=='none'`, not on Core/Extended, because AG-UI consumers silently ignore unknown CUSTOM types and stricter gating only breaks discovery. No code change; left as-is.

## [0.5.37] — 2026-07-10

### 🔧 Fixes
- GH-95: `MarketBriefing`'s section types (`BriefingKpiItem.value`/`.delta`, `ChartSection.data`, `TableSection.data`) previously accepted non-finite floats with no validation, silently splitting the dual-part artifact contract — `model_dump_json()` serializes `inf`/`nan` as JSON `null` while `to_markdown()`/`to_plain_text()` render them literally as `"inf"`/`"nan"`, so a client's structured and text views of the same card would disagree. Fixed via per-field validators scoped to exactly the four fields GH-95's AC named, using a shared `_assert_finite()` helper that recurses through dict/list/tuple nesting and any embedded pydantic `BaseModel` values. (RT-001: an earlier revision broadened this onto a `_Wire`-wide `model_validator` covering every `ContentModel` field SDK-wide and shipped it as a patch despite self-declaring a breaking change — reverted to the AC's original scope, so this is a non-breaking patch fix.) (`agent_sdk/models/content_types.py`)
- GH-96: `agent_sdk/routes/ag_ui.py`'s `stream()` now catches any non-`StreamTerminated` exception raised inside its event loop (e.g. from `mapper.map()` or a store call) and yields a `RUN_ERROR` terminal frame with the static message `"internal error"` before the `finally` unsubscribe runs — previously such an exception propagated past the post-loop `terminal_sent` safety net and the SSE connection died with no terminal frame at all, violating the AG-UI "exactly one terminal event" invariant. The error message is intentionally static (never `str(exc)`) per SI-2: the exception can carry tool/user payload. (`agent_sdk/routes/ag_ui.py`)
- GH-97: `_validate()` no longer rejects the client's raw `body` for missing/malformed `threadId`/`runId` — those fields are already synthesized into local variables and used for `RUN_STARTED` before `_validate` runs, so the old check unconditionally emitted `RUN_ERROR: "threadId is required"` immediately after a valid `RUN_STARTED`. `_validate` now only checks `messages` shape and content. (`agent_sdk/routes/ag_ui.py`)
- GH-98: `TOOL_PROGRESS` (added in GH-88/w025) is now declared in `agent_card.py`'s `CUSTOM_EVENTS`/`_CUSTOM_EVENT_SCHEMAS` (`{message: string, toolName: string}`) and handled by the admin console's `chat.js` `handleCustom()` — previously the event was genuinely emitted on the wire but absent from both the agent card and the console's reference renderer, which fell through to "unrecognized CUSTOM event". (`agent_sdk/routes/agent_card.py`, `agent_sdk/console/static/chat.js`, `DESIGN.md`)
- GH-99: the `load_skill` unknown-skill-name error path (`agent_sdk/agent/loop.py`) now truncates to 64 chars and strips control characters from the caller/model-supplied skill name before embedding it in `ToolResultEvent.error`, matching the sanitization the adjacent unknown-tool branch already applied — previously the raw name reached `ToolResultEvent.error` (and from there the AG-UI `TOOL_CALL_RESULT` SSE frame) unsanitized (SI-2). (`agent_sdk/agent/loop.py`)
- GH-100: `Agent(exclude_from_catalog=[...])` lets always-on/guardrail skills be inlined into `persona`/`artifacts_dir` (unconditionally in the system prompt) while being omitted from the advertised skills catalog text folded into that same system prompt — the skill remains fully loadable via `load_skill`/`app.state.skills.load()`, it is just not listed. Validated at `build_app()` boot (unknown names raise `ValueError`); no post-build mutation hook. (`agent_sdk/app.py`, `agent_sdk/agent/skills.py`, `DESIGN.md`)
- GH-101: `ToolSet.tool()` now logs a `WARNING` at registration time when a tool function's `__name__` ends in `_tool` and no explicit `name=` override was supplied — the `_tool` suffix is registered verbatim (never stripped), which was a recurring cause of a skill/persona being authored against a tool name that doesn't exist. Never raises, never renames. (`agent_sdk/agent/registry.py`, `docs/tools.md`)

### 🧪 Test / CI
- `tests/test_content_types.py` — GH-95 cases (`BriefingKpiItem`/`ChartSection`/`TableSection` reject non-finite, finite payloads round-trip); RT-001 cases proving fields outside the AC's four (`MetricItem`, `BarItem`, `WaterfallSegment`, `ComparisonTable` rows, `FundPerformance.irr`, free-form `metadata`) intentionally still accept non-finite floats; RT-003 cases proving `_assert_finite` catches a non-finite float nested inside a foreign (non-`_Wire`) `BaseModel` embedded in `ChartSection.data`/`TableSection.data`
- `tests/test_gh96_ag_ui_terminal_event_coverage.py` — forces a non-`StreamTerminated` exception mid-stream, asserts exactly one `RUN_ERROR` frame terminates the SSE stream
- `tests/test_gh97_ag_ui_thread_run_id_synthesis.py` — omitted/empty-string/non-string `threadId`/`runId` synthesize correctly and never trigger a post-`RUN_STARTED` `RUN_ERROR`
- `tests/test_card_console.py` — strengthened to derive the emitted-event-name set from `ag_ui.py`'s event types and assert it equals `CUSTOM_EVENTS` (card-vs-emitted parity, not just card-vs-console)
- `tests/test_agent_skills.py` — `TestUnknownSkillSI2SurfaceCoverage`: a crafted control-char/oversized skill name never appears verbatim in the AG-UI `TOOL_CALL_RESULT` payload or the A2A `ToolResultEvent.error`
- `tests/test_skills_catalog.py` — `exclude_from_catalog` omits entries from `catalog_text()` while `load()` still resolves them; unknown name raises at `build_app()`
- `tests/test_gh101_tool_suffix_name_warning.py` — `_tool`-suffixed name with no `name=` warns (via `caplog`); explicit `name=` override suppresses it; non-suffixed name never warns

## [0.5.36] — 2026-06-24

### 🔧 Fixes
- GH-94: `openai.RateLimitError` now raises `AgentError(ErrorCategory.RATE_LIMITED, "model rate limit exceeded; retry later")` instead of being swallowed by the bare `except Exception` as a generic `"model invocation failed"` — callers can now distinguish transient rate-limit failures from fatal errors; `Retry-After` header is extracted into `detail={"retry_after": n}` when present. (`agent_sdk/agent/openai_client.py`)

### 🧪 Test / CI
- `tests/test_gh94_rate_limit_error.py` — 4 cases: `RateLimitError` → `RATE_LIMITED` category, message distinct from fatal, fatal errors still `UPSTREAM`, `Retry-After` header extraction

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
