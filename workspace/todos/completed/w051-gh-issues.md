# w051 — GitHub issue 180

Sourced from open issues on wailuen/a2a-sdk. One item.
Runs on top of v0.14.0 (w050 released as 1f7bd72).
Target: 0.14.1.

---

- [ ] `GH-180` A2A DataPart emits domain-catalog surfaces the client did not declare ‖ group:G1
  - Creates: (modifies `agent_sdk/a2ui/translator.py`, `agent_sdk/console/static/chat.js`, new `tests/test_gh180_a2a_catalog_negotiation.py`, `docs/content-types.md` (if it describes catalog gating), `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/a2a.py` (`gated()` call ~line 393), `agent_sdk/routes/ag_ui.py` (~line 504), `agent_sdk/a2ui/catalog.py` (`a2ui_extension`, advertised catalog IDs), `agent_sdk/routes/agent_card.py`, `tests/test_rt001_ag_ui_custom_extended_gate.py`
  - Severity: high
  - Root cause: `A2uiCapabilities.allows()` (translator.py ~line 108) returns True for any model whose `catalog_id != CATALOG_ID` without checking `self.catalogs`. On A2A there is no silent-ignore safety net, so a client that declared only the Standard Profile still receives `createSurface` for a domain catalog. A2UI v0.9.1 negotiation requires catalogs both sides support.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/180#issuecomment-6192926900
  - AC: `allows()` returns False for a domain model whose `catalog_id` is not in `self.catalogs`; the A2A DataPart then carries only the text + raw-data fallback (same shape as `tier="none"` for that artifact).
  - AC: AG-UI CUSTOM emission is unchanged: `for_custom_emit()` still emits domain types whatever the declared catalogs (LRN-049). Pin with a test; the existing `tests/test_rt001_ag_ui_custom_extended_gate.py` must stay green unmodified.
  - AC: A client that opts in with no `catalogs` key, a non-list, or an empty list gets the Standard Profile only (existing `from_metadata` default kept). A domain model is therefore gated off for it on A2A. Test it.
  - AC: A client that declares the domain catalog ID gets the domain surface on A2A (positive test).
  - AC: Standard Profile in-catalog types keep today's tier behaviour (Extended still needs the extended tier on A2A).
  - AC: The admin console `chat.js` A2A request (and the AG-UI forwardedProps, for consistency) declares every catalog ID the agent card advertises in its A2UI extension params, not only `urn:a2ui-profile:standard:v1`. Read them from the agent card the console already loads, or fetch `/.well-known/agent-card.json` once; fall back to the Standard Profile ID if the card has none. Any card value placed in the request is used as data only (no innerHTML).
  - AC: CHANGELOG `[Unreleased]` notes the behaviour change for A2A clients that relied on receiving undeclared domain catalogs.
  - GH: https://github.com/wailuen/a2a-sdk/issues/180
  - Reuses: C-006  # A2uiCapabilityGate (agent_sdk/a2ui/translator.py: gated()/allows()/for_custom_emit()) is the single capability gate shared by both transports. Put the catalog-membership check inside C-006 allows() only. Do not add a second check in routes/a2a.py or runner.build_artifact. Keep gated()/from_metadata() defaults as they are (LRN-046/LRN-115). Update the C-006 entry in workspace/components/README.md: allows() now gates domain types on declared catalogs, and for_custom_emit() is the AG-UI bypass.
  - SI: SI-5  # No SI: field, but this todo changes the A2A capability-negotiation gate (C-006) that both data paths use, and it adds a new request-building fetch in the admin console. Add an SI line with these rules. (1) Do not touch gated()'s fail-closed tier="none" default for clients that never opt in, or the X-A2A-Extensions / forwardedProps opt-in checks in routes/a2a.py:393 and routes/ag_ui.py:504-505 (LRN-046, LRN-115). (2) In chat.js, treat the card's params.supportedCatalogIds as untrusted data. Accept only an array of strings, cap how many are taken and how long each can be, drop anything else, and fall back to urn:a2ui-profile:standard:v1. Never put these values into innerHTML or into console/log text (SI-2). Fetch the card from the same-origin relative path /.well-known/agent-card.json, which is a public route, so do not attach the admin key to that request.

---

Archived 2026-10-15 by hand. The pre-archive gate failed on one docs test (tests/test_rt007_component_registry_anchors.py: the new C-044 registry entry cited chat.js:370). Fixed by hand by naming the functions instead. Full suite then green.
