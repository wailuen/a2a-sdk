wave: w051
group: G1
date: 2026-10-15

Non-blocking — these did not block w051's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.
All findings are SDK-level (sdkCandidate: true). Context: GH-180 (A2A catalog negotiation in
A2uiCapabilities.allows(); AG-UI CUSTOM bypass via for_custom_emit()/any_catalog).

## Findings

### RT-001
- severity: medium
- file: workspace/learning/LRN-049-agui-custom-emit-freely-catalog-gate-wrong.md
- description: The LRN-049 Check clause now fails against the landed code. It says "The allows() method in translator.py must return False only when self.tier == \"none\", and must emit domain types freely ... never suppress based on catalog membership." GH-180 deliberately changed allows() to check catalog membership. AG-UI keeps the old behaviour only through for_custom_emit()/any_catalog. A future redteam that runs this Check will flag the GH-180 fix and push to revert it. (Severity inherited from LRN-049: medium.)
- fix: Reword the LRN-049 Check clause. allows() gates domain types on self.catalogs for the A2A DataPart path (GH-180). for_custom_emit() must set any_catalog=True so the AG-UI CUSTOM path is gated only on tier == "none". Cite issue #180 and its ruling comment.
- codify: When a ruling changes a gate, update every LRN Check clause that pins the old gate in the same todo, or the next redteam reverts the fix.

### RT-002
- severity: medium
- file: agent_sdk/a2ui/translator.py
- description: Raised in three rounds. The module docstring (lines 36-41) still says "domain cards are emitted freely whenever tier is active (consumers silently ignore unknown CUSTOM events per AG-UI spec) — only tier=\"none\" suppresses them (GH-56)". That contradicts the GH-180 allows() logic at lines 114-118 in the same file. This file's own docstrings are what reviewers read before "fixing" the gate.
- fix: Rewrite the "Gating happens here" paragraph. Extended types need tier="core+extended". On the A2A DataPart path, domain cards need their catalog_id in caps.catalogs (GH-180). On the AG-UI CUSTOM path, for_custom_emit() sets any_catalog=True, so only tier="none" suppresses them (LRN-049). tier="none" suppresses everything. Cite GH-180 and LRN-049.

### RT-003
- severity: medium
- file: workspace/components/README.md
- description: Raised in three rounds. The todo's "Reuses: C-006" line requires updating the C-006 A2uiCapabilityGate entry to state that allows() now gates domain types on declared catalogs and that for_custom_emit() is the AG-UI bypass. The file is unchanged (git diff --stat / git status show no change), and the C-006 text at lines 10 and 56-57 still describes only gated()/from_metadata(). The todo is therefore not complete (Dimension 5).
- fix: Extend the C-006 entry. allows() checks model_cls.catalog_id against self.catalogs for non-Standard catalogs unless any_catalog is set (GH-180). for_custom_emit() returns a copy with tier="core+extended" and any_catalog=True; it is the only code that sets any_catalog and the only AG-UI CUSTOM bypass. any_catalog is never parsed from client input. No route or transport may add a second catalog check.

### RT-004
- severity: medium
- file: agent_sdk/console/static/chat.js
- description: Raised in three rounds. loadCatalogIds() (lines 343-362) runs once when the chat pane renders (line 358/362) and is fire-and-forget; sendA2a() and the AG-UI request builder never await it. A message sent before the agent-card fetch resolves declares only urn:a2ui-profile:standard:v1, so on A2A that turn's domain card falls back to text plus raw data with no sign in the console. The baseInput "change" handler (lines 211-213) changes state.base but never reloads state.catalogIds, so pointing the console at another agent sends the previous agent's catalog list and the new agent's domain catalogs are never declared — the exact GH-180 symptom the console change was meant to avoid. render() also re-runs on every tab visit (console.js:81), refetching the card each time.
- fix: Store the load as a module-level promise that runs once per base URL (e.g. state.catalogIdsReady ??= loadCatalogIds()). In the baseInput "change" handler, reset state.catalogIds to the Standard Profile default and start a fresh load. Await the promise at the top of sendA2a() and before the AG-UI body is built.
- codify: A capability list fetched in the background must be awaited before the first request that declares it, or the first turn silently negotiates down.

### RT-005
- severity: medium
- file: agent_sdk/testing/chat.py
- description: Raised in two rounds. ChatDriver is a first-party SDK client. It already fetches and caches the agent card (_discover_card, lines 126-139), but still declares only [standard] + extra_catalogs (lines 92-96). The admin console was changed to declare every supportedCatalogIds entry; ChatDriver was not. Downstream agent tests that use ChatDriver(client).a2a_turn, or `python -m agent_sdk chat --a2a` without --catalog, now silently lose domain A2UI surfaces on A2A and get the raw-data fallback. Neither the CHANGELOG migration note nor the docs mention extra_catalogs or --catalog.
- fix: Choose one. (a) Make ChatDriver merge the card's A2UI extension params.supportedCatalogIds into self._caps["catalogs"] after _discover_card(), validated the same way as chat.js (strings only, capped count and length). Or (b) at minimum, add to the CHANGELOG [Unreleased] migration note: "ChatDriver / `agent_sdk chat --a2a` users must pass extra_catalogs=[...] / --catalog for domain cards", and add the same note to docs/testing.md:141 and docs/content-types.md.
- codify: When a server-side negotiation gate gets stricter, every SDK-owned client (console, ChatDriver, CLI) must be updated to declare the new requirement, not just the one the todo names.

### RT-006
- severity: medium
- file: tests/test_gh180_a2a_catalog_negotiation.py
- description: Raised in three rounds. Every test calls A2uiCapabilities.allows()/translate() in isolation, so the transport-level ACs are untested. (1) AC1 ("the A2A DataPart then carries only the text + raw-data fallback, same shape as tier=\"none\"") is unpinned: no test proves the delivered parts for an undeclared domain catalog have no A2UI_MIME_TYPE DataPart, no data.messages, raw model dump present, and no mimeType in artifact metadata. (2) No positive test sends a domain surface through build_artifact or POST /v1/message(:stream) with X-A2A-Extensions plus metadata.a2uiClientCapabilities.catalogs listing the domain ID. (3) The AG-UI "unchanged — pin with a test" AC is pinned only at unit level; no _RunMapper or /ag-ui/run test shows an A2UI_UPDATE CUSTOM event still goes out for a registered domain type when forwardedProps lists only the standard catalog.
- fix: Add a build_artifact(ArtifactEvent(domain payload), A2uiCapabilities.gated(True, {"catalogs": [CATALOG_ID]})) test asserting a TextPart plus one raw-data DataPart (raw wire() data), no part with metadata.mimeType == "application/json+a2ui", and parts equal to the tier="none" output. Add the declared-catalog counterpart that does carry the A2UI DataPart. Add one route-level test posting to /v1/message:stream with a registered domain card and checking the artifact parts. Add an AG-UI _RunMapper or /ag-ui/run test that A2UI_UPDATE is emitted for the domain type with standard-only catalogs.

### RT-007
- severity: medium
- file: CHANGELOG.md
- description: GH-180 changes stable-core behaviour: the public A2uiCapabilities.allows() and the A2A wire output. A client that used to receive domain surfaces now gets only the text and raw-data fallback. Yet the entry sits under "### Changed" in a wave targeting 0.14.1, a patch release. The changelog's own convention (SemVer on the stable core, DESIGN.md §4.0) uses a "### 🔴 Breaking changes" section for exactly this. The "New tests:" bullet is also filed under Changed.
- fix: Move the GH-180 entry under "### 🔴 Breaking changes" with its migration note, and release as a minor (0.15.0), not 0.14.1. Drop the "New tests" bullet or move it under a Tests/Fixed heading.

### RT-008
- status: CLOSED by GH-213
- severity: medium
- file: agent_sdk/a2ui/translator.py
- description: GH-180 cites A2UI v0.9.1 negotiation, but from_metadata() (lines ~81-88) reads only the SDK profile key `catalogs`. A2UI's own a2uiClientCapabilities names the client's catalog list `supportedCatalogIds`. A third-party client that declares a domain catalog only under `supportedCatalogIds` falls back to [CATALOG_ID], and allows() now gates its domain surfaces off; before GH-180 that client received them. (PLAUSIBLE: the advisor's Standard Profile binding uses `catalogs`.)
- fix: In from_metadata(), when `catalogs` is missing or unusable, accept a non-empty list of strings from raw["supportedCatalogIds"] (same validation). Add a test that a client declaring the domain catalog via supportedCatalogIds gets allows(_Domain) is True.

### RT-009
- severity: low
- file: agent_sdk/console/static/chat.js, tests/test_card_console.py
- description: Raised in two rounds. No test pins the console's new behaviour: reading params.supportedCatalogIds from the same-origin card, the string/length/count filter, the Standard Profile fallback, and declaring state.catalogIds in both the A2A metadata and the AG-UI forwardedProps. If someone reverts to the hard-coded standard-only list, the console's A2A path breaks for domain cards and no test fails.
- fix: Add a static source check in tests/test_card_console.py, like the existing chat.js render-branch checks. Assert the "supportedCatalogIds" read, that both a2uiClientCapabilities literals use `catalogs: state.catalogIds`, and that the card fetch sends no Authorization header.

### RT-010
- severity: low
- file: agent_sdk/console/static/chat.js
- description: The extension lookup at line 349 accepts any URI that merely contains "a2ui.org/a2a-extension/a2ui/" (indexOf). That includes other A2UI versions or a URI that only embeds the substring. The same file sends the exact URI "https://a2ui.org/a2a-extension/a2ui/v0.9.1" in X-A2A-Extensions (line 372), so the console could read catalogs from an extension block it does not actually activate.
- fix: Match with `e.uri === "https://a2ui.org/a2a-extension/a2ui/v0.9.1"`, ideally through one shared const used by both the card lookup and the X-A2A-Extensions header.

### RT-011
- status: CLOSED by GH-213
- severity: low
- file: docs/protocols.md
- description: Raised in two rounds. Line 137 says the card's A2UI extension carries `catalogIds`. The real param is `supportedCatalogIds` (catalog.py:382), which this wave corrected only in docs/content-types.md. The page also does not mention the new A2A catalog-negotiation gate.
- fix: Change the key to `supportedCatalogIds` and add one sentence: A2A clients must list a domain catalog in a2uiClientCapabilities.catalogs to receive its surfaces (GH-180).

### RT-012
- severity: low
- file: DESIGN.md
- description: Raised in two rounds. §5.4 line 365 says "a domain component is emitted only when the client's a2uiClientCapabilities.catalogs includes that domain catalog_id. Tier alone never unlocks domain types." It says nothing about the AG-UI CUSTOM bypass (for_custom_emit / any_catalog), while docs/content-types.md now says "AG-UI CUSTOM events are not gated by catalog". The design doc and the user docs give different rules.
- fix: Limit the §5.4 domain-gating bullet to the A2A DataPart path. Add: "AG-UI A2UI_UPDATE CUSTOM events are gated only on tier=\"none\" (for_custom_emit(), LRN-049)." Cite GH-180.

### RT-013
- severity: low
- file: agent_sdk/app.py
- description: app.state.default_capabilities = A2uiCapabilities() at line 893 is never read anywhere in agent_sdk. This dead state is a fail-open default (tier="core" with the standard catalog). A future caller that picks it up would bypass gated()'s fail-closed tier="none" rule (LRN-046/LRN-115) and the GH-180 catalog negotiation.
- fix: Remove app.state.default_capabilities. If something must stay, make it A2uiCapabilities.gated(False, None) and comment that routes must resolve capabilities per request.

### RT-014
- severity: low
- file: tests/test_protocol_fixes_w6.py
- description: Comments at lines 31-33, 38 and 47 still say domain types are "emitted freely" and the catalog list is "vestigial in allows()". Since GH-180 that is false. The tests pass only because _CAPS_A2UI_ON happens to list the domain catalog.
- fix: Update the comments: _CAPS_A2UI_ON must list the domain catalog because allows() gates domain types on declared catalogs (GH-180).
