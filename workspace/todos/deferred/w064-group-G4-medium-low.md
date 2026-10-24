# w064 — G4 deferred medium/low findings

- Wave: w064
- Scope: unit:G4
- Date: 2026-10-24

Non-blocking — these did not block w064's archive. Address opportunistically or fold into a future wave.

Findings are deduped by file+description. Where two redteam rounds reported the same defect, both IDs are listed (round-local IDs collide across rounds).

## Medium

### F1 (RT-001) — `agent_sdk/a2ui/translator.py:98` [SDK]
Quote: `(c for c in candidates if isinstance(c, list) and (keep_declared_catalogs or c)),`
On A2A an empty `catalogs: []` now counts as the declared list and hides a filled GH-213 alias. `gated(True, {'catalogs': [], 'v0.9': {'supportedCatalogIds': [CATALOG_ID, 'urn:d']}}, keep_declared_catalogs=True).catalogs == []`, while the old path gives `[CATALOG_ID, 'urn:d']`. Such a client loses BOTH Standard and domain cards (domain = GH-213 regression the ruling never covered). No test pins this case.
Fix: either (a) skip an empty list when a later alias holds a non-empty list, or (b) keep the strict first-list rule and record it: test for `{'catalogs': [], 'v0.9': {...}}`, update docs/protocols.md:179, CHANGELOG behaviour-change line noting domain cards too.

### F2 (RT-003 / RT-002) — `docs/protocols.md:179` [SDK]
Quote: "A2A clients must list a domain catalog in `a2uiClientCapabilities.catalogs` ... accepted too when `catalogs` is absent or unusable ... (GH-213)."
The client-facing doc never states GH-240: over A2A, a declared catalog list without `urn:a2ui-profile:standard:v1` gets only the TextPart fallback for Standard cards. `grep GH-240 docs/` finds nothing. "absent or unusable" is now wrong for A2A: `{"catalogs": [], "v0.9": {"supportedCatalogIds": [CATALOG_ID]}}` no longer falls through (allows()=False over A2A, True over AG-UI).
Fix: add a GH-240 paragraph (cite ruling https://github.com/wailuen/a2a-sdk/issues/240#issuecomment-6379597173): over A2A, the first present list among `catalogs` / `v0.9.supportedCatalogIds` / `supportedCatalogIds` (empty included) is used as sent and must contain the Standard Profile URN for Standard cards; no such key = unchanged; AG-UI not gated. Change "absent or unusable" to "absent or not a list (A2A), or absent/empty (AG-UI)".

### F3 (RT-004) — `DESIGN.md:368` [SDK]
Quote: "- **Domain gating:** ... when `catalogs` is absent or not a non-empty list ..."
GH-240 also changed domain-card gating over A2A: `catalogs: []` plus `v0.9.supportedCatalogIds: [DOMAIN]` no longer sends the domain card. §5.4 still says empty `catalogs` falls through; CHANGELOG only describes the Standard change. Unannounced change to GH-213 behaviour.
Fix: update the bullet (A2A/keep_declared_catalogs keeps an empty list; AG-UI keeps old fall-through); mention domain effect in the GH-240 CHANGELOG bullet; add a test pinning `{"catalogs": [], "v0.9": {"supportedCatalogIds": [DOMAIN]}}` over A2A.

### F4 (RT-003, round 2) — `CHANGELOG.md:21`
Quote: "- GH-240: over A2A a Standard Profile card is sent only when the client's advertised catalogs ... contain `urn:a2ui-profile:standard:v1` ..."
Stable-core wire behaviour change not marked as one (unlike GH-241 in the same block). Clients that declared `catalogs: []`, a domain-only list, or a populated alias without the URN now get only text. Repeats the `keep_declared_catalogs` sentence from the `### Added` entry (line 18), and line 18 says "set only by from_metadata" though any caller can pass it to the public dataclass.
Fix: mark **behaviour change**; list affected client shapes; add migration line (add the URN to `catalogs`); drop the repeated sentence; reword "set only by" as "set by the SDK only through".

### F5 (RT-005 / RT-004) — `tests/test_gh214_no_delete_surface.py:79` [SDK]
Quote: `"""The console keeps every surface mounted: a2ui.js only unmounts on a`
GH-242 AC asks for a correct docstring; still wrong. a2ui.js never unmounts on deleteSurface: post-paint loop (a2ui.js:209-216, "close the registry entry; DOM persists") closes the registry entry and the node stays (DESIGN.md §6/§7.1 agree). GH-242 also asked for a node-harness render test; the test still only greps source for `msg.deleteSurface` / `deleteSurface`.
Fix: docstring: "The console keeps every surface mounted. a2ui.js still accepts a deleteSurface from another producer and closes the registry entry after painting, while the painted DOM stays. The SDK itself never sends one." Replace greps with a node test like tests/test_gh239_console_caps.py: render createSurface+updateComponents+updateDataModel, then deleteSurface; assert node stays attached and a later updateComponents is dropped.

### F6 (RT-006 / RT-005) — `tests/test_a2ui_wire.py:1493` [SDK]
Quote: `"""DESIGN.md §5.4: a replayed createSurface for a held surface is a no-op,`
DESIGN.md §5.4/§6/§7.1 state as fact that a replayed createSurface for a held surface is a no-op. No A2UI v0.9.1 citation; the SDK's own renderer calls it a protocol error (a2ui.js:141 `console.warn("[a2ui] protocol error: duplicate createSurface for open surface", surfaceId)`). Docs cite only tasks/get, though GH-240 named tasks/resubscribe (routes/a2a.py) too.
Fix: cite the A2UI v0.9.1 clause, or reword: "replay reuses the same surfaceId; the SDK console ignores a duplicate createSurface for an open surface (with a warning) and still applies updates; third-party renderers may treat it as an error". Name tasks/get and tasks/resubscribe. Align a2ui.js warning text.

### F7 (RT-006, round 2) — `tests/test_a2ui_wire.py:1527`
Quote: `assert sids(first) and sids(first) == sids(second)`
The replay test only shows the task store returns the same stored artifact on two reads (wait_for_state already GETs /v1/tasks/{id}). It never feeds messages into a renderer and does not cover tasks/resubscribe, so it cannot support the "no-op" claim.
Fix: run both artifacts' message arrays through a2ui.js under node (as in tests/test_gh239_console_caps.py, skip without node); assert one surface, one painted node, no error notes. Add a tasks/resubscribe case checking the same surfaceId.

## Low

### F8 (RT-007, both rounds) — `agent_sdk/a2ui/translator.py:33` [SDK]
Quote: `profile types need ``tier="core+extended"``; domain cards are emitted freely`
Module docstring gating paragraph is stale: says domain cards go out whenever tier is active and only tier=none suppresses them (GH-56). False since GH-180 (domain needs declared catalog), and GH-240 gates Standard cards on A2A too. Also, the C-006 entry in workspace/components/README.md:82 states the GH-240 keyword rule twice.
Fix: rewrite to describe allows(): domain cards need catalog_id in `catalogs` unless `any_catalog` (AG-UI CUSTOM via for_custom_emit(), gated only by tier=none); on A2A (`negotiate_standard`) Standard cards need CATALOG_ID when a catalogs list is present; Extended types need tier core+extended. Merge the two C-006 GH-240 sentences.

### F9 (RT-008) — `tests/test_gh240_field_summary_alias.py:15` [SDK]
Quote: `pb_id: str = Field(serialization_alias="pbId")`
AC asks for an aliased domain card, but `_Aliased` keeps the default Standard `catalog_id` and only covers `serialization_alias`, not `alias`. No module docstring citing GH-240; file missing from the todo's Creates list (scope drift, LRN-322).
Fix: give `_Aliased` its own `catalog_id` (e.g. `urn:gh240:test:v1`), add a `Field(alias=...)` field and assert its alias shows, add GH-240 docstring with ruling URL, add file to G4 Creates.

### F10 (RT-009) — `tests/test_gh240_a2a_catalog_negotiation.py:78` [SDK]
Quote: `def test_ag_ui_custom_unchanged() -> None:`
Builds capabilities directly with `A2uiCapabilities.gated(True, ...)`, never through `routes/ag_ui.py::_capabilities(body)`, so a wrong `keep_declared_catalogs=True` on the AG-UI route would pass. Missing: mixed A2A case (`catalogs: [DOMAIN]` lets domain through, blocks Standard) and an Extended Standard type under negotiation.
Fix: resolve via `agent_sdk.routes.ag_ui._capabilities({"forwardedProps": {"a2uiClientCapabilities": {"catalogs": [OTHER]}}})`, assert `negotiate_standard is False` and A2UI_UPDATE emitted; add the mixed and Extended cases on A2A.
