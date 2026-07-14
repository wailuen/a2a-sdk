# w032 — GitHub issues 110–114

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: 0.5.41.

---

- [ ] `GH-110` AG-UI + A2A missing Origin allow-list check ‖ group:G
  - Creates: `agent_sdk/common/origin.py` (shared `guard_origin` helper, extracted from `mcp.py`'s 5 inline call sites, C-009), `tests/test_common_origin_guard.py`, `tests/test_gh110_origin_allowlist.py` (modifies `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/mcp.py`)
  - Also modifies (RT-003, folded in): `agent_sdk/agent/events.py`, `agent_sdk/agent/runner.py` — `InterruptEvent.expires_at` renamed to `expires_in` (holds seconds-remaining, not an absolute time; the old name was left over from the 0.5.40 AGUI-1 fix and was misleading). Internal-only field, not exported from any `__init__`, so no public API break. See CHANGELOG 0.5.41.
  - Reads: `agent_sdk/routes/mcp.py:446-448` (reference RT-004 pattern, 5 existing call sites)
  - Severity: medium
  - Root cause: `agent_sdk/routes/mcp.py` enforces a defense-in-depth Origin allow-list check (RT-004) on every browser-reachable streaming surface, but `ag_ui.py`'s `POST /ag-ui/run` and all 6 handlers in `a2a.py` (message_send, message_stream, tasks_list, tasks_get, tasks_cancel, tasks_resubscribe) lack it — an inconsistent partial hardening of RT-004's own stated intent ("every browser-reachable streaming surface").
  - AC: `ag_ui_run` rejects with 403 when `Origin` header is present and not in `request.app.state.cors_origins`, mirroring `mcp.py:446-448` exactly.
  - AC: all 6 `a2a.py` handlers apply the identical check before body parsing.
  - AC: regression tests assert 403 for disallowed Origin and normal pass-through for absent/allowed Origin, for both surfaces.
  - GH: https://github.com/wailuen/a2a-sdk/issues/110
  - SI: SI-5  # Touches transport-security hardening on the A2A + AG-UI browser-reachable data paths (Origin allow-list) with no SI: field on the todo. Implementer must (a) not weaken the existing Depends(require_identity) on ag_ui.py:399 and the 6 a2a.py handlers, and (b) keep the 403 detail a STATIC string exactly as mcp.py uses ('origin not allowed') — never interpolate the untrusted Origin header value into the response or a log line (SI-2 injection). Add an explicit SI: line to the todo.

- [ ] `GH-111` MCP GET/DELETE skip MCP-Protocol-Version validation ‖ group:G
  - Creates: (modifies `agent_sdk/routes/mcp.py`, `tests/test_http_protocol.py`)
  - Reads: `agent_sdk/routes/mcp.py:174-188` (`_negotiated_version()`), `agent_sdk/routes/mcp.py:492-500` (mcp_post's invalid-value branch)
  - Severity: medium
  - Root cause: `mcp_post` validates `MCP-Protocol-Version` via `_negotiated_version()` and returns 400 for an unrecognized value; `mcp_get` (~line 576) and `mcp_delete` (~line 604) never call this helper, so a present-but-unrecognized header value is silently accepted instead of rejected.
  - AC: `mcp_get` returns a 400 JSONResponse when `_negotiated_version(request)` is None (present-but-unrecognized); the absent-header case is unaffected (out of scope per the locked GH-77/w022 ruling — do not re-litigate absent-header behavior).
  - AC: `mcp_delete` gets the identical check.
  - AC: `mcp_get`'s return type annotation is widened (e.g. `StreamingResponse | JSONResponse`); mypy clean.
  - AC: new tests cover GET/DELETE with `MCP-Protocol-Version: bogus-value` → 400, plus a regression test confirming GET/DELETE with no header still succeed unchanged.
  - GH: https://github.com/wailuen/a2a-sdk/issues/111

- [ ] `GH-112` ChatDriver dead transport-selection code ‖ group:G
  - Creates: (modifies `agent_sdk/testing/chat.py`, `agent_sdk/__main__.py`, `tests/test_chat_driver.py`)
  - Reads: `agent_sdk/testing/chat.py:234-250` (dead selection logic), `DESIGN.md:18-23` (v1 non-goals: A2A client features / gRPC / JSON-RPC transports are out of scope)
  - Severity: medium
  - Root cause: `ChatDriver.a2a_turn` computes a transport/URL selection (walking `additionalInterfaces`, checking for `JSONRPC`) but never acts on it — every request unconditionally POSTs to `/v1/message:send` on the pre-bound client. DESIGN.md's v1 non-goals already settle this in favor of HTTP+JSON-only, not "wire in the selection" — the fix is to delete the dead code and narrow scope, not add transport support.
  - AC: the `additionalInterfaces`-walk/JSONRPC fallback logic in `a2a_turn` is deleted, replaced with a guard that raises `ValueError` when `preferredTransport != "HTTP+JSON"`.
  - AC: `ChatDriver` class docstring + `a2a_turn` docstring state explicitly that it is HTTP+JSON-only, citing DESIGN.md's non-goals.
  - AC: `test-chat --url` CLI help text in `__main__.py` notes the HTTP+JSON-only limitation.
  - AC: `tests/test_chat_driver.py`'s `test_sc_e3_additional_interfaces_fallback`/`test_sc_e3_no_fallback_raises` are rewritten to assert `ValueError` is raised for any non-HTTP+JSON `preferredTransport` regardless of `additionalInterfaces` content (the current "falls back and succeeds" assertion is deleted as invalid).
  - GH: https://github.com/wailuen/a2a-sdk/issues/112

- [ ] `GH-113` A2UI deleteSurface interop trap — advertise post-paint semantics (option a, developer-confirmed) ‖ group:G
  - Creates: `tests/test_gh113_delete_surface_semantics.py` (modifies `agent_sdk/a2ui/catalog.py`, `DESIGN.md`, `tests/test_card_console.py`)
  - Reads: `agent_sdk/a2ui/translator.py:118-140` (atomic bundling), `agent_sdk/console/static/a2ui.js` (post-paint deferral convention already implemented by the console)
  - Severity: medium
  - Root cause: `translate()` always bundles `createSurface`+`updateComponents`+`updateDataModel`+`deleteSurface` atomically; the console renderer only works because of a project-local "show-then-close" convention (DESIGN.md §7.1) that isn't wire-discoverable. Developer chose option (a): make the convention discoverable via the extension params rather than changing wire behavior (option b, deferred as a bigger/riskier change).
  - AC: `a2ui_extension()` params (`agent_sdk/a2ui/catalog.py`) include a new `deleteSurfaceSemantics: "post-paint"` field.
  - AC: unit test asserts the agent card's A2UI extension always carries this field.
  - AC: `DESIGN.md` §5.4/§7.1 updated to state the semantics are now wire-discoverable, citing the exact param name/value.
  - GH: https://github.com/wailuen/a2a-sdk/issues/113

- [ ] `GH-114` GH-74 fail-closed default missing LRN doc ‖ group:G
  - Creates: `workspace/learning/LRN-115-agui-capabilities-fail-closed-tier-none-default.md`
  - Reads: `agent_sdk/routes/ag_ui.py:368-372` (`_capabilities()` fail-closed default), `tests/test_gh74_ag_ui_capabilities_fail_open.py`, `workspace/learning/LRN-049-*.md` (format to mirror)
  - Severity: low
  - Root cause: GH-74's deliberate fail-closed `tier="none"` default (when `a2uiClientCapabilities` is absent) has no LRN doc memorializing it as intentional, unlike the sibling LRN-049 decision in the same function family — pure documentation debt, no code/test change needed.
  - AC: new LRN doc mirrors LRN-049's frontmatter (id, title, category, severity, source, date) and section structure (Observation, Root Cause, Prevention, Check).
  - AC: Prevention section explicitly warns against "aligning" the default to spec's `tier="core"`.
  - AC: Check section cites `tests/test_gh74_ag_ui_capabilities_fail_open.py` as executable proof.
  - AC: `grep -ril "GH-74" workspace/learning/` returns the new file.
  - GH: https://github.com/wailuen/a2a-sdk/issues/114
