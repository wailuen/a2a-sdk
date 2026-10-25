# w068 — G4 deferred findings (medium/low)

- Wave: w068
- Scope: unit:G4
- Date: 2026-10-25

Non-blocking — these did not block w068's archive. Address opportunistically or fold into a future wave.

Findings were collected across every redteam round and deduped by file and description. Where two rounds reported the same issue, they are merged below and the round IDs are listed.

---

## D-1 (medium) — tasks/resubscribe echoes A2UI with no per-task decision
- Rounds: R1 RT-002, R2 RT-001
- File: `agent_sdk/routes/a2a.py:1194`
- Quote: `_echo_extensions(request, response, activatable=_STREAM_ONLY_EXTENSION_URIS)`
- Issue: GH-271 added `a2ui_active` to `_echo_extensions` with a fail-open default of True (line 328). This caller does not pass it. A resubscribe to a task built without A2UI (no opt-in, or acceptedOutputModes `["application/json"]`) answers `X-A2A-Extensions: <A2UI URI>`. It also does so on the 404 for an unknown task id. Probed: send echo None, resubscribe 200 echo A2UI, unknown id 404 echo A2UI.
- Fix: Make `a2ui_active` keyword-only with no default (or default False, per the GH-261 fail-closed convention). In tasks_resubscribe, echo after the store lookup with `a2ui_active=record.a2ui_opted_in and accepts_a2ui_mode(record.accepted_output_modes)` (or use `_echo_a2ui_if_present`); echo nothing on the 404. This undoes the RT-B-005 "echo before not-found" ordering, so get a maintainer ruling or file a follow-up GH issue first. Test: send with header + `["application/json"]`, then resubscribe with header must not echo A2UI.
- Codify: When a helper gains a per-request decision parameter, every caller must pass it explicitly. An extension echo must come from the same per-task activation decision on every route; never default to True.
- sdkCandidate: true

## D-2 (medium) — `_a2ui_decision` recomputes instead of using the build's capabilities
- Rounds: R1 RT-003, R2 RT-002
- File: `agent_sdk/routes/a2a.py:453-454`
- Quote: `return record.a2ui_opted_in and accepts_a2ui_mode(modes)`
- Issue: The decision is re-derived from `params.configuration`, not from the A2uiCapabilities the build used (C-006 reuse note: "never a recomputed one"). It ignores `a2uiClientCapabilities`: a client that opts in with tier `none` gets no A2UI built, yet the header claims A2UI is activated. It also reads params modes, while runner `_build_capabilities` (lines 1191, 1487) reads `record.accepted_output_modes`; they match today only because `_create_task_record` copies non-empty modes verbatim.
- Fix: In message_send/message_stream compute `caps = _capabilities(...)` once, pass it to `_start_worker`, and set `a2ui_active=_build_capabilities(caps, record.accepted_output_modes).tier != "none"` (shared helper); delete `_a2ui_decision`. Minimum fix: drop `params` and read `record.accepted_output_modes`. Test: header + metadata `a2uiClientCapabilities {"tier":"none"}` must not echo A2UI.
- Codify: An extension echo must be derived from the exact capability object the build used, never re-derived from request fields.
- sdkCandidate: true

## D-3 (low) — store contract test skips unimported stores; misses live resume case
- Rounds: R1 RT-004, R2 RT-003
- File: `tests/test_gh271_task_store_contract.py:14,27`
- Issue: Stores are found via `TaskStore.__subclasses__()` after importing only `agent_sdk.tasks.memory`. A new bundled store module would be skipped silently, and `test_at_least_one_bundled_store_is_covered` still passes. The test also only checks a fresh, already-completed task, never a live `input-required` task after a resume (the case the `TaskStore.get` docstring names).
- Fix: Import every module under `agent_sdk.tasks` (`pkgutil.walk_packages` + `importlib.import_module`) before collecting; skip abstract classes via `inspect.isabstract`. Add a case: tool interrupts, resume carries new acceptedOutputModes, then `store.get(task_id, owner)` still returns `a2ui_opted_in` and the updated `accepted_output_modes`.
- sdkCandidate: true

## D-4 (low) — duplicate A2UI media-type literal
- Rounds: R1 RT-005, R2 RT-006
- File: `agent_sdk/common/media.py:7`
- Quote: `_A2UI_MEDIA_TYPE = "application/a2ui+json"`
- Issue: Second copy of `A2UI_MIME_TYPE` (`agent_sdk/models/content_types.py:172`, used by `_supported_modes`, `build_artifact`, `_echo_a2ui_if_present`). Nothing pins them equal; drift would split the build/echo gate from the part filter.
- Fix: Add a unit test asserting `media._A2UI_MEDIA_TYPE == A2UI_MIME_TYPE` (importing models from common would invert layering), or move the constant into `common/media.py` and have `content_types` import and re-export it.
- sdkCandidate: true

## D-5 (low) — emitting-app control test does not prove success
- Rounds: R1 RT-007, R2 RT-004
- File: `tests/test_gh257_single_a2ui_gate.py:157`
- Quote: `assert "error" not in r.json(), r.text`
- Issue: A task that ends `failed` (e.g. -32005 from apply_output_modes inside the worker) has no top-level `error`, so the control still passes.
- Fix: In `test_modes_with_a2ui_on_control_same_request_succeeds`, also assert `r.status_code == 200`, `r.json()["status"]["state"] == "completed"`, and that `X-A2A-Extensions` contains `A2UI_EXTENSION_URI`.
- sdkCandidate: true

## D-6 (low) — two ambiguous "Deviation (GH-266)" sentences in docs
- Rounds: R1 RT-006
- File: `tests/test_gh259_a2a_route.py:572`
- Quote: `i = text.rindex("Deviation (GH-266)")`
- Issue: docs/protocols.md now has two different "Deviation (GH-266)" sentences (-32004 status and MCP void-emits). The MCP test uses position-dependent `rindex`; LRN-553's Check names an ambiguous sentence; no test pins the new -32004 deviation sentence (ruling item 3).
- Fix: Locate each paragraph by a unique anchor (e.g. "maps `-32004` to HTTP 501", "declares `emits`"); add a doc test for the -32004 sentence and the issue-266 ruling URL; update LRN-553's Check to name the MCP sentence by its own words.
- sdkCandidate: true

## D-7 (low) — `apply_output_modes` docstring omits mimeType rewrite
- Rounds: R2 RT-005
- File: `agent_sdk/agent/runner.py:433`
- Issue: Since GH-271, when filtering changes the parts, artifact `metadata.mimeType` is rewritten to the shared normalized media type of the kept parts, or removed when they differ. Not documented.
- Fix: Extend the docstring with that behaviour; cite GH-271 item 2.
- sdkCandidate: true

## D-8 (low) — DESIGN.md -32004 row incomplete
- Rounds: R2 RT-007
- File: `DESIGN.md:292`
- Quote: `| -32004 | UnsupportedOperation | terminal-task re-message (`message/send`, `message/stream`), any unimplemented method |`
- Issue: Omits the "task is not awaiting input" trigger on `message:send`/`message:stream` and the GH-266 HTTP 400 deviation (GH-271 ruling item 4). docs/protocols.md was updated; this table was not.
- Fix: Extend the row: "terminal-task re-message or message to a task not awaiting input (`message:send`, `message:stream`) → HTTP 400 (GH-266 deviation; A2A v0.3.0 says 501); any unimplemented method → 501". DESIGN.md is outside G4's Modifies list; route via the owning group or a follow-up.
- sdkCandidate: true
