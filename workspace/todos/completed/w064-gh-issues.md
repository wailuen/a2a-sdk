# w064 — GitHub issues 235–242

Sourced from open issues on wailuen/a2a-sdk filed 2026-10-24 from the w062/w063 deferred lists and the v0.20.0/v0.20.1 release-gate audits (each re-checked at v0.20.1). GH-186 is deferred by ruling. GH-224 is design-only.
Groups G1–G6 are independent and run in parallel; items inside one group share files and run in order.
Target: 0.21.0 — the A2A catalog check (GH-240) changes which clients get cards.

Each issue body lists file:line, the probe, and the fix; implement exactly those items. GH-242 (weak tests) is split: each test item is done by the group that owns the code under test, named below. Do NOT edit `template/` except the peer copy named in GH-242 (G6) (LRN-085/LRN-071: it lands via commit+push to wailuen/a2a-agent-template inside this wave; the commit stages only that path). Shared files edited by parallel groups (`CHANGELOG.md`, `DESIGN.md` (G3, G4), `docs/protocols.md` (G1, G4), `docs/content-types.md` (G5), `docs/testing.md` (G2), `workspace/components/README.md`): each item edits only its own row/section with in-place Edit, never a whole-file rewrite. Each item adds its own entry to `CHANGELOG.md` `[Unreleased]`, naming every changed `agent_sdk/` file by repo path (LRN-491).

---

## G1 — protocol ingress + MCP surface

- [x] `GH-235` deeply nested JSON body returns HTTP 500; extra AG-UI resume entries ignored ‖ group:G1
  - Creates: (modifies `agent_sdk/common/json_strict.py`, `agent_sdk/routes/ag_ui.py`, `workspace/components/README.md` (C-040 row only), `CHANGELOG.md`; new `tests/test_gh235_nested_json_and_resume.py`)
  - Reads: `agent_sdk/routes/mcp.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/oauth.py`
  - Severity: medium
  - Root cause: `loads_strict` lets `RecursionError` escape and no caller catches it; `_resume` uses only `resume[0]`.
  - AC: `loads_strict` (C-040) turns `RecursionError` into its fixed-message `json.JSONDecodeError` (no input echo). The fix lives only in C-040; no route adds its own `RecursionError` catch. Body `"[" * 50000 + "]" * 50000`: MCP `POST /mcp` (~1004) → JSON-RPC -32700; MCP `/messages` SSE path (~1398) → JSON-RPC -32700; A2A `POST /v1/message:send` → its parse error (not 500); AG-UI `POST /ag-ui/run` → its existing parse-error response (not 500). OAuth Dynamic Client Registration `POST /oauth/register` (`routes/oauth.py` ~352, catches only `UnicodeDecodeError`/`ValueError`, so today a nested body escapes as 500) caps the body at `_MAX_BODY_BYTES` = 16 KiB (~72), so the 100 KB body above is rejected by the size check before parsing; it gets its own nested body under 16 KiB (depth 2000, `"[" * 2000 + "]" * 2000`, past the default recursion limit of 1000) → HTTP 400 `invalid_client_metadata` "request body must be valid JSON", not 500. One test per surface (five), failing test written RED before the code, GREEN after.
  - AC: an AG-UI resume with more than one entry → `RUN_ERROR` with fixed text `invalid resume entry`, code `validation`. Test. `status` values stay unchecked (dual-mode ruling, docs/protocols.md:104-110).
  - AC (SI-2): the `RecursionError` mapping never uses `str(exc)` or any slice of the body; the `invalid resume entry` RUN_ERROR carries no resume entry content. Tests send a hostile marker string in the nested body and in the extra resume entry, and assert it is absent from every surface's error payload (MCP both sites, A2A, AG-UI, OAuth `/oauth/register`).
  - AC: the C-040 row in `workspace/components/README.md` says ingress also maps `RecursionError` to the fixed-message `JSONDecodeError`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/235
  - Reuses: C-040  # loads_strict is C-040 (agent_sdk/common/json_strict.py). Fix RecursionError -> fixed-message json.JSONDecodeError only inside C-040. Do not add per-route RecursionError catches. Both MCP parse sites (agent_sdk/routes/mcp.py ~1004 POST /mcp and ~1398 the /messages SSE path), A2A (~448), AG-UI (~509) and OAuth /oauth/register (agent_sdk/routes/oauth.py ~352, catches ValueError, of which JSONDecodeError is a subclass) already catch JSONDecodeError and inherit the fix. Add the second MCP site and the OAuth site to the per-surface tests. Update the C-040 row to say ingress also maps RecursionError.
  - SI: SI-2  # Touches protocol ingress error text (loads_strict in C-040, AG-UI _resume RUN_ERROR in agent_sdk/routes/ag_ui.py). The RecursionError mapping never uses str(exc) or any slice of the body, and the 'invalid resume entry' RUN_ERROR carries no resume entry content. Tests assert the hostile body text is absent from every surface's error.

- [x] `GH-236` load_skill, pagination and strict-mode conformance gaps ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/mcp.py`, `agent_sdk/common/schema.py`, `agent_sdk/app.py`, `docs/protocols.md`, `docs/deployment.md`, `workspace/components/README.md` (C-068 and C-070 rows only), `tests/test_gh205_mcp_skills.py`, `tests/test_gh206_strict_schema_mode.py`, `tests/test_gh207_mcp_description.py`, `tests/test_rt001_strict_required_nullable_output.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/agent/registry.py`, `agent_sdk/agent/loop.py`
  - Severity: low
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/236#issuecomment-6379597364 (wider unions follow https://github.com/wailuen/a2a-sdk/issues/206#issuecomment-6377771749)
  - AC: load_skill annotations `{"readOnlyHint": true, "openWorldHint": false}` and `title: "Load skill"`.
  - AC: tools/call load_skill is served only when `_mcp_skills(app)` is non-empty (else the normal unknown-tool error); extra keys, a missing `name` or a non-str `name` get the registry's argument-error shape (GH-196), built with the registry's `_unknown_argument_error` (`agent_sdk/agent/registry.py` ~350) and rendered through C-050 `safe_validation_message`; no hand-built error string in `routes/mcp.py`. No value echo: argument VALUES never appear; key NAMES appear only as C-050 sanitises them (GH-196, `loop.py` ~1163).
  - AC: the load_skill catalog is cut at whole entries within 2048 chars and ends with `…and N more` when entries were left out. Test with 40 skills.
  - AC: an undecodable or negative cursor on tools/list and prompts/list → JSON-RPC -32602 with fixed text. The check lands in the shared C-070 cursor path (`_decode_cursor` + offset, `routes/mcp.py` ~557/614/655), replacing the `max(0, _decode_cursor(cursor))` clamp, so both lists reject the same way. Tests for both lists.
  - AC: strict mode drops the `null` member from anyOf unions of 3+ members at property positions, with the same required/keep-null rules as the two-member case. This extends C-068 `flatten_schema` (`agent_sdk/common/schema.py`) at property positions only; C-066 top-level emits unions stay intact (test). Test `Optional[Union[int, str]]` for input and output.
  - AC: the `mcp_skills` and reserved-name boot checks run before `_build_credential_store()`. Test that a failed boot leaves no open store.
  - AC: `routes/mcp.py` module and `_handle_tools_list` docstrings describe prompts/list, prompts/get, load_skill and strict mode.
  - AC (from GH-242): `tests/test_gh205_mcp_skills.py:131,208` assert the JSON-RPC code; `tests/test_gh207_mcp_description.py` drives one loop turn with FakeModelClient and asserts the model sees the docstring; `tests/test_rt001_strict_required_nullable_output.py` fails on any validation error and asserts zero skipped models.
  - AC (SI-2): cursor errors never echo the cursor value; argument errors echo only C-050-sanitised key names, never values; boot-check failures raised before `_build_credential_store()` carry fixed text with no store path or key material. Tests assert a hostile cursor string, a hostile argument value and the store path are absent from the error text.
  - AC: in `workspace/components/README.md`, the C-070 row no longer documents the `max(0, _decode_cursor(cursor))` clamp (states -32602 on undecodable/negative cursor), and the C-068 row's "keeps multi-member anyOf" says null is dropped from 3+ member unions at property positions in strict mode. Both rows edited in place.
  - GH: https://github.com/wailuen/a2a-sdk/issues/236
  - Reuses: C-070  # The negative/undecodable cursor -> -32602 AC must land in the shared C-070 cursor path (_decode_cursor + offset at agent_sdk/routes/mcp.py ~557/614/655), so tools/list and prompts/list reject the same way. The C-070 row still documents the `max(0, _decode_cursor(cursor))` clamp that this AC removes. Update that row in place.
  - Reuses: C-068  # Dropping null from 3+ member anyOf unions in strict mode extends C-068 flatten_schema (agent_sdk/common/schema.py). It must apply only at property positions, so C-066 top-level emits unions stay intact. The C-068 row says 'keeps multi-member anyOf'. Update it in place.
  - Reuses: C-050  # Bad load_skill arguments (extra keys, missing or non-str name) must be built with the registry's _unknown_argument_error (agent_sdk/agent/registry.py ~350) and rendered through C-050 safe_validation_message. Do not hand-build a parallel error string in routes/mcp.py. Under GH-196, C-050 echoes identifier-like key NAMES (loop.py ~1163). The 'No input echo' AC therefore means values only.
  - SI: SI-2  # Adds new client-facing error paths in agent_sdk/routes/mcp.py (load_skill argument errors, -32602 cursor errors) and reorders credential-store construction in agent_sdk/app.py (credential code). Cursor errors never echo the cursor value. Argument errors echo only C-050-sanitised key names, never values. Boot-check failures raised before _build_credential_store() carry fixed text with no store path or key material.

## G2 — test clients and MCP gate

- [x] `GH-237` MCP gate miscounts load_skill; test clients drop A2A kind and mis-handle AG-UI history ‖ group:G2
  - Creates: (modifies `agent_sdk/testing/mcp.py`, `agent_sdk/testing/turns.py`, `agent_sdk/testing/chat.py`, `docs/testing.md`, `workspace/components/README.md` (C-055, C-056 and C-072 rows only), `CHANGELOG.md`; new `tests/test_gh237_testing_clients.py`)
  - Reads: `tests/test_gh234_agui_chat_driver.py`, `tests/test_chat_driver.py`, `tests/test_gh210_testing_turns.py`, `harness/skills/acceptance/SKILL.md`
  - Severity: medium
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/237#issuecomment-6379597584
  - AC: `_check_list` (C-056 McpTestClient, `agent_sdk/testing/mcp.py`) leaves the built-in `load_skill` out of the count compared with `--expected-count`; the exclusion lives inside C-056. `run_gate` test on an app with `mcp_skills="tool"`.
  - AC: the A2A message built in `testing/turns.py` carries `"kind": "message"`. Test.
  - AC (run-outcome signal): `ChatDriver._run_agui` (`agent_sdk/testing/chat.py` ~215-303) returns `tuple[bool, str]` = `(finished, reply)`, where `finished` is True only when a RUN_FINISHED frame was read (any `outcome`, including `interrupt`) and `reply` is the joined assistant text (may be `""`). Today it returns `""` both on failure and on a RUN_FINISHED with no assistant text (A2UI-only turn, interrupt outcome, or a turn whose only text is a `developer` message after the role filter below), so callers cannot tell success from failure; every append decision below keys on `finished`, never on `reply` truthiness. `_run_agui` is private with exactly two callers (`agui_turn`, `agui_resume`); both are updated. The public return type of `agui_turn` / `agui_resume` stays `str` (the reply, `""` when not finished), so `agent_sdk/__main__.py:230` and existing tests are untouched.
  - AC (agui_turn history contract): `ChatDriver.agui_turn` (C-072 owner, ~152-172) posts a body built from a copy, `self._agui_body(thread_id, [*messages, {"role": "user", "content": query}])`, and does not touch `messages` before the run (today ~168 appends the user message first and never removes it). After the run, by outcome:
    - RUN_FINISHED with non-empty reply → append `{"role": "user", "content": query}` then `{"role": "assistant", "content": reply}`.
    - RUN_FINISHED with empty reply (A2UI-only, interrupt outcome, developer-only text) → append `{"role": "user", "content": query}` only; never an empty assistant entry. This keeps the query in history so the next turn and `agui_resume` after an interrupt post it.
    - RUN_ERROR, stream closed with no terminal event, or an exception from the POST/stream (`httpx.HTTPStatusError`, `httpx.TransportError`, cancel) → `messages` unchanged (the exception still propagates).
    The `agui_turn` docstring (~161-166) states this three-row contract.
  - AC (agui_resume history contract): `agui_resume` (~174-202) appends `{"role": "assistant", "content": reply}` only when `finished` and `reply` is non-empty; it never appends a user message or an empty assistant entry; on RUN_ERROR / no terminal event / exception `messages` is unchanged.
  - AC (tests, `tests/test_gh237_testing_clients.py`, failing test written RED before the code, GREEN after): direct `ChatDriver.agui_turn` cases with a captured posted body: (a) text + RUN_FINISHED → `messages[-2:]` is user query then assistant reply; (b) A2UI-only turn (CUSTOM `AGENT_ARTIFACT` + `A2UI_UPDATE` frames, no text, RUN_FINISHED) → `messages[-1] == {"role": "user", "content": query}` and no assistant entry with empty content; (c) RUN_FINISHED with `outcome.type == "interrupt"` and no text → same as (b), then a following `agui_resume` posts a body whose `messages` contains that user query; (d) RUN_ERROR and (e) no terminal event → `messages` equals its value before the call. In every case the last entry of the posted body's `messages` is `{"role": "user", "content": query}`. Through `turns.py` (`_agui_attempt`): (f) text success and (g) the A2UI-only turn of (b) (classified success by C-055 `_Attempt.classify` because `content_types` is non-empty) → `messages` ends with the user query, and for (f) the assistant reply after it; (h) RUN_ERROR → `messages` equals the pre-turn snapshot; (i) interrupt-only with no text and no artifact → C-055 classifies `empty-reply` and restores the snapshot (today's retry behaviour, asserted, not changed by this item).
  - AC (layering): the fix lives in `chat.py`; it is not a second rollback mechanism. C-055's snapshot/restore in `turns.py` (`_agui_attempt` / `_restore_if_failed` ~183-213) is unchanged and stays the outer guard for timeouts, transport errors, cancels and turns it classifies as failed.
  - AC (reply role filter, exclusion rule): the filter only ever removes text; it never needs a START to keep text. Record a role for a message id only from an explicit `role` field on its `TEXT_MESSAGE_START` or on its first `TEXT_MESSAGE_CHUNK` (the id a chunk resolves to under today's id inheritance/reset rules). Text is left out of the reply only when the recorded role for its id is a value other than `"assistant"` (`developer`, `system`, `user`, `tool`, or any other string). Every other text counts as assistant and is kept exactly as today, including: a START with no `role` or `role == "assistant"` (AG-UI defaults `role` to `"assistant"`); a chunk-only message whose first CHUNK has no `role` or `role == "assistant"`; a `TEXT_MESSAGE_CONTENT` whose `messageId` never had a START; a CONTENT frame with no `messageId` at all; an id-less CHUNK. Only the reply join changes; the `text` emit still fires for every delta as today. The filter lives in C-072 `agui_terminal_stream_reader` (`ChatDriver._run_agui`) and `turns.py` reuses it, so both apply one reply-join rule. "RUN_FINISHED was read" in the run-outcome AC includes a RUN_FINISHED with no `outcome` field.
  - AC (existing tests stay green unchanged; none of these files is edited by GH-237): `tests/test_chat_driver.py:93,152,179,538` (START with no role; :184 CONTENT `m2` with no START after RUN_FINISHED stays ignored); `tests/test_gh234_agui_chat_driver.py:49-51,60-105,120-135,155-170,222` (bare `_content(...)` frames with no START, e.g. :105 `== "Hello\nWorld"`; :222 id-less CHUNK after a START, `== "a\nb\nc"`) — G3 (GH-238) edits this file in parallel, so GH-237 must not rely on changing it; `tests/test_gh210_testing_turns.py:137-158,198-224` (`_agui_ok` sends CONTENT with no `messageId` and a RUN_FINISHED with no `outcome`; :220 asserts reply `"agui reply"` and saved roles `["user", "assistant"]`). Run all three files before and after the change.
  - AC (role-filter tests, `tests/test_gh237_testing_clients.py`): a `developer` message next to an assistant message, through both `ChatDriver.agui_turn` and `turns.py` (`_agui_attempt` / `run_turn`), keeps only the assistant text; a START with no `role` keeps its text; a chunk-only message with no role keeps its text; a CONTENT-only message (no START, with a `messageId`) keeps its text; a CONTENT frame with no `messageId` keeps its text; a `developer` START followed by CONTENT for a different id with no START keeps only the second message's text.
  - AC: the `agui_resume` docstring states the RUN_FINISHED-only return contract and its append rule (assistant only, only on RUN_FINISHED with non-empty text).
  - AC: in `workspace/components/README.md`, the C-056 row says the built-in `load_skill` is not counted against `--expected-count`, and the C-072 row says it owns the assistant-role reply filter, the `(finished, reply)` run-outcome signal, and append-on-finish (`agui_turn` appends the user message on any RUN_FINISHED and the assistant message only when the reply is non-empty; nothing on RUN_ERROR / no terminal event). The C-055 row is left as is apart from noting its rollback is the outer guard for timeouts/transport errors/cancels (it already covers RUN_ERROR / no-terminal-event runs). Rows edited in place.
  - GH: https://github.com/wailuen/a2a-sdk/issues/237
  - Reuses: C-056  # _check_list belongs to C-056 McpTestClient (agent_sdk/testing/mcp.py). Exclude load_skill inside that component. Update the C-056 row to say the built-in load_skill is not counted against --expected-count.
  - Reuses: C-055  # C-055 (agent_sdk/testing/turns.py _agui_attempt/_restore_if_failed ~183-213) snapshots and restores `messages` around ChatDriver.agui_turn for turns.py callers only. It stays as the outer guard for timeouts, transport errors and cancels; it already covers RUN_ERROR / no-terminal-event runs. Do not move the append-on-success fix here.
  - Reuses: C-072  # C-072 (agent_sdk/testing/chat.py::ChatDriver) owns the assistant-role text filter (exclusion rule: text is left out only when an explicit non-assistant role was recorded for its message id from its TEXT_MESSAGE_START or first TEXT_MESSAGE_CHUNK; text with no recorded role, including CONTENT with no START or no messageId, counts as assistant; in _run_agui), the (finished, reply) run-outcome signal from _run_agui, and append-on-finish in agui_turn (~168; user on any RUN_FINISHED, assistant only on non-empty reply). Reuse it so turns.py and chat.py apply one reply-join rule, and fix the premature user append here so direct ChatDriver callers are covered. Update the C-072 row.

## G3 — console (chat.js, a2ui.js)

- [x] `GH-238` AG-UI chat client history and interrupt lows ‖ group:G3
  - Creates: (modifies `agent_sdk/console/static/chat.js`, `tests/test_gh234_agui_chat_driver.py`, `CHANGELOG.md`)
  - Reads: `tests/test_card_console.py` (RT-004 node cross-check pattern)
  - Severity: medium
  - AC: a failed resume POST restores the interrupt only if `state.threadId` is unchanged and `pendingInterrupt` is still null; the shown Resume form is tracked and removed before any re-render, so at most one form exists.
  - AC: START/CONTENT/END and chunk-only messages are folded into `state.aguiMessages` only after RUN_FINISHED, in arrival order of their first frame; an id-less chunk with no earlier chunk id gets a `uuid()` id.
  - AC (from GH-242): the GH-234 console checks run in node (skip when node is absent), following the `tests/test_card_console.py` RT-004 pattern, instead of source greps; the `:133` http_error case asserts `httpx.HTTPStatusError`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/238

- [x] `GH-239` A2UI renderer caps, registry growth and stale docs ‖ group:G3
  - Creates: (modifies `agent_sdk/console/static/a2ui.js`, `DESIGN.md`, `CHANGELOG.md`; new `tests/test_gh239_console_caps.py`)
  - Reads: `agent_sdk/console/static/chat.js`
  - Severity: low
  - AC: renderBarChart and renderGeneric scalar rows call the existing C-059 `capRows`/`moreNote` helpers (MAX_ROWS); no local cap. Node test with 150 bars.
  - AC: `renderA2ui` prunes registry entries whose `node.isConnected` is false; the comment at the registry names the real fields.
  - AC: DESIGN.md §7.1 (~line 470) describes the generic card for object-bound unknown types and the MAX_ROWS cap.
  - GH: https://github.com/wailuen/a2a-sdk/issues/239
  - Reuses: C-059  # capRows/moreNote/MAX_ROWS are C-059 (agent_sdk/console/static/a2ui.js). renderBarChart and renderGeneric scalar rows must call the existing C-059 helpers, not a local cap.

## G4 — A2UI translator

- [x] `GH-240` Standard Profile sent without negotiation; surface-lifetime docs inaccurate ‖ group:G4
  - Creates: (modifies `agent_sdk/a2ui/translator.py`, `agent_sdk/a2ui/catalog.py`, `agent_sdk/routes/a2a.py` (`_capabilities` ~406-414 only), `agent_sdk/agent/runner.py`, `docs/protocols.md`, `DESIGN.md`, `workspace/components/README.md` (C-006 row only), `tests/test_gh214_no_delete_surface.py`, `tests/test_a2ui_wire.py`, `tests/test_rt001_a2ui_data_encoding_hint.py`, `CHANGELOG.md`; new `tests/test_gh240_a2a_catalog_negotiation.py`)
  - Reads: `agent_sdk/routes/ag_ui.py`, `agent_sdk/models/content_types.py`
  - Severity: medium
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/240#issuecomment-6379597173
  - AC: on the A2A path, a Standard Profile card is emitted only when the client's advertised catalogs contain `CATALOG_ID` (`urn:a2ui-profile:standard:v1`, reused from `agent_sdk/models/content_types.py:166`, no new literal); else the TextPart fallback is sent. A client with no catalogs key keeps today's behaviour. AG-UI CUSTOM is unchanged. Tests for all three cases plus AG-UI.
  - AC: the negotiation goes through C-006. `A2uiCapabilities.from_metadata` / `gated` gain a transport-scoped keyword argument (default keeps today's behaviour, so AG-UI callers are untouched); only `routes/a2a.py::_capabilities` passes it. With it set, an absent catalogs key still resolves to `[CATALOG_ID]`, but a present catalogs list (including an empty list) is kept as sent, so "no key" and "key without the profile URN" are told apart.
  - AC: "advertised catalogs" means the first list found in the GH-213 order: `catalogs`, then `v0.9.supportedCatalogIds`, then `supportedCatalogIds`. The aliases count. "No catalogs key" means none of the three is present as a list. Tests cover the URN sent via each alias.
  - AC: the C-006 row in `workspace/components/README.md` names the transport-scoped argument and the A2A-only "present list kept as sent" rule.
  - AC: `_field_summary` uses `info.serialization_alias or info.alias or name`. Test with an aliased domain card.
  - AC: "fresh surfaceId per turn" becomes "per artifact" in `docs/protocols.md`, `translator.py` and DESIGN.md; docs say a caller-supplied `surface_id` must be unique per artifact. DESIGN.md §5.4 states a replayed createSurface for a held surface is a no-op; add a tasks/get replay test.
  - AC: the `validate_a2ui_delivery` error text in `runner.py` no longer mentions the removed split and keeps the substring `empty open`.
  - AC (from GH-242): `tests/test_gh214_no_delete_surface.py:85-94` uses `Path(__file__)` paths and a correct docstring; `tests/test_a2ui_wire.py:248` cites the GH-214 ruling URL; `tests/test_rt001_a2ui_data_encoding_hint.py:6` no longer calls deleteSurfaceSemantics live.
  - GH: https://github.com/wailuen/a2a-sdk/issues/240
  - Reuses: C-006  # The catalog negotiation must go through C-006 (A2uiCapabilities.gated/from_metadata, agent_sdk/a2ui/translator.py ~76-107). Today from_metadata turns an absent OR empty catalogs list into [CATALOG_ID], so 'no catalogs key keeps today's behaviour' cannot be told apart from 'catalogs present without the profile URN' without changing C-006. C-006 is shared with AG-UI, so the change uses a transport-scoped parameter passed only by agent_sdk/routes/a2a.py::_capabilities, keeping AG-UI CUSTOM unchanged. The GH-213 aliases (v0.9.supportedCatalogIds, supportedCatalogIds) count as advertised catalogs. Reuse CATALOG_ID (agent_sdk/models/content_types.py:166) for the URN, not a new literal.

## G5 — errors and id helpers

- [x] `GH-241` SafeValueError edge cases and id-helper docs ‖ group:G5
  - Creates: (modifies `agent_sdk/agent/loop.py`, `agent_sdk/models/errors.py`, `agent_sdk/__init__.py`, `docs/content-types.md`, `docs/tools.md`, `workspace/learning/LRN-470-pydantic-type-code-echo.md`, `workspace/components/README.md` (C-050 row only), `tests/test_gh230_safe_value_error.py`, `tests/test_gh212_id_safe_text.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/common/redact.py`, `agent_sdk/models/content_types.py`
  - Severity: low
  - AC: the SafeValueError hint is sanitised inside C-050 with the existing C-034 `safe_line_text` first (no new control-char stripper); an empty result falls back to the generic phrase. Parametrized test including `'\x07 '`.
  - AC (SI-2): the parametrized test drives the hint through MCP, A2A and AG-UI and asserts no control or bidi character and no raw input reaches any error payload.
  - AC: `SafeValueError.__init_subclass__` raises TypeError for a non-str or blank class `message`; the runtime fallback stays.
  - AC: LRN-470's Check points at C-050 `_validation_phrase` / `_BUILTIN_ERROR_CODES` (`agent_sdk/agent/loop.py`).
  - AC: the C-050 row in `workspace/components/README.md` names the hint sanitising and the `__init_subclass__` class-message guard.
  - AC: `docs/content-types.md` (~237) no longer contradicts the `is_id` column, states the leftover risk inside an is_id cell, and names `safe_joined_id_text`, which is exported from `agent_sdk`. Rendering is unchanged (GH-212 ruling).
  - AC (from GH-242): `tests/test_gh230_safe_value_error.py:161-190` drops dead imports and builds a real unknown_argument error; `tests/test_gh212_id_safe_text.py` removes the duplicate assert, writes U+2028 as an escape, adds U+2028, `\x85` and `\x9b` to HOSTILE_STANDALONE, and sends the is_id table through MCP.
  - GH: https://github.com/wailuen/a2a-sdk/issues/241
  - Reuses: C-050  # The SafeValueError hint channel and _validation_phrase/_BUILTIN_ERROR_CODES are C-050 (agent_sdk/agent/loop.py). Sanitise the hint inside C-050 and point LRN-470's Check at it. Update the C-050 row to include the __init_subclass__ class-message guard.
  - Reuses: C-034  # Sanitise the hint with the existing C-034 safe_line_text (agent_sdk/common/redact.py). Do not write a new control-char stripper.
  - SI: SI-2  # Changes the SafeValueError hint that reaches the wire in tool error text (agent_sdk/models/errors.py, agent_sdk/agent/loop.py). The parametrized test proves no control or bidi character and no raw input reaches the MCP/A2A/AG-UI error payloads.

## G6 — harness workflow tests

- [x] `GH-242` workflow-script test gaps and acceptance-api.js arg guards ‖ group:G6
  - Creates: (modifies `harness/workflows/acceptance-api.js`, `template/.claude/workflows/acceptance-api.js`, `tests/test_gh131_acceptance_api_args_normalization.py`, `tests/test_gh233_workflow_scripts_parse.py`, `workspace/components/README.md` (C-069 and C-071 rows only), `CHANGELOG.md`)
  - Reads: `harness/workflows/wave-cycle.js`
  - Severity: low
  - AC: `acceptance-api.js` (both copies, identical guard lines placed in the C-069 `normalizedArgs` block) rejects a non-array `transports` and a non-array `onlyIds` with a fixed message (no arg echo, never the `_keyFile` path); `onlyIds` matches whole ids, so `S-1` does not match `S-10`. Node mutation tests.
  - AC: in `workspace/components/README.md`, the C-069 row covers the array-type guards and whole-id `onlyIds` matching; the C-071 row covers utf-8 read, `re.M` export strip, repo-relative path + node stderr, and the required `sdk-wave.js`.
  - AC: the GH-131 no-echo regex also catches `e.message` and `JSON.stringify(normalizedArgs)`; the bare-`args` scan covers helpers above the guard; dead `_after_guard` removed.
  - AC: the GH-233 parse test reads with `encoding="utf-8"`, strips `export` with `re.M`, reports the repo-relative path plus node stderr on failure, and also requires `.claude/workflows/sdk-wave.js` to exist.
  - AC: template copy committed and pushed to wailuen/a2a-agent-template main, staging only `.claude/workflows/acceptance-api.js`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/242
  - Reuses: C-069  # The transports/onlyIds array guards sit next to the GH-131 normalizedArgs block, which is C-069 (harness/workflows/acceptance-api.js + template mirror). Extend C-069 with identical guard lines in both copies. Update the C-069 row to cover the array-type guards and whole-id onlyIds matching.
  - Reuses: C-071  # The GH-233 parse test changes (utf-8 read, re.M export strip, repo-relative path + node stderr, sdk-wave.js must exist) modify C-071 WORKFLOW_SCRIPT_PARSE_CHECK (tests/test_gh233_workflow_scripts_parse.py). Update its registry row.
  - SI: SI-2  # acceptance-api.js args carry the service-key file path (_keyFile, ~253-267). The new guards emit error text. The fixed-message, no-arg-echo rule and the widened no-echo regex (e.message, JSON.stringify(normalizedArgs)) are tracked as an invariant, not only as an AC.

---

Archived by hand 2026-10-24: the sdk-wave run (wf_5269b229-07e) finished with no critical/high left
(protocolBlocked flag set but every advisor reported 0 critical / 0 high), pytest gate 4145 passed,
but it did not move this file. The 3 "still-open" sdk-candidates were re-checked against the code
and are fixed (_MAX_DEPTH=64 in json_strict.py; negotiate_standard documented in CHANGELOG;
HOSTILE_STANDALONE carries U+2028/\x85/\x9b). Mediums: deferred/w064-*-medium-low.md and
deferred/w064-protocol-medium.md.
