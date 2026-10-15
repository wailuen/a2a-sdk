# SDK issue candidates — w051 (2026-10-15)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: Full suite red (2 failed): test_gh56_ac1_domain_type_allowed_when_tier_core_catalog_standard (line 565) and test_gh56_allows_domain_type_core_plus_extended_catalog_omitted (line 597) still assert the old GH-56 rule (domain types emitted regardless of declared catalogs), contradicting the new GH-180 allows() catalog gate in agent_sdk/a2ui/translator.py:114. Fix: rewrite both tests so catalogs=[standard] gives translate(...) is None on the A2A path and not None with capabilities=caps.for_custom_emit() (AG-UI CUSTOM path); cite GH-180 in docstrings; do not loosen allows(). /sdk-release refuses to tag until the suite is green.
- Severity: critical
- Component: protocol/a2ui
- File: tests/test_a2ui_group_d.py
- Rationale: SDK test suite covering the A2UI translator/catalog gate (SDK internal); blocks the SDK release gate, not agent-specific code.

## Candidate 2: loadCatalogIds() (lines 343-358) keeps every string from params.supportedCatalogIds with no count or length cap, and fetches `${state.base}/.well-known/agent-card.json` from the user-editable base URL instead of the same-origin relative path. A card from any origin can push an unbounded catalogs array into every A2A metadata and AG-UI forwardedProps request. Fix: fetch '/.well-known/agent-card.json' (or refetch deliberately on base change), keep string IDs <=~256 chars and at most ~32, always keep urn:a2ui-profile:standard:v1, and fall back to it when nothing valid remains.
- Severity: high
- Component: sdk/console
- File: agent_sdk/console/static/chat.js
- Rationale: SDK-shipped admin test console code; also a security issue (untrusted remote input copied into outbound requests without bounds), applies to every agent built on the SDK.

## Candidate 3: LRN-049's Check clause still says allows() must return False only when tier == 'none' and never suppress by catalog membership. GH-180 made allows() gate domain types on self.catalogs, so the next redteam round (Dimension 7) will flag GH-180 as an LRN-049 violation and push to revert it. Fix: rewrite the Check and Prevention point 3 so the AG-UI emit-freely rule lives only in for_custom_emit() (returns self for tier=='none', else core+extended with any_catalog=True), state that allows() on the A2A path does gate on declared catalogs (GH-180, ruling comment 6192926900), and point to tests/test_gh180_a2a_catalog_negotiation.py::test_custom_emit_ignores_declared_catalogs as the pin. Note: this finding reuses id RT-001, which duplicates the first finding's id.
- Severity: high
- Component: protocol/a2ui
- File: workspace/learning/LRN-049-agui-custom-emit-freely-catalog-gate-wrong.md
- Rationale: SDK repository learning record that the SDK redteam harness enforces for the A2UI/AG-UI catalog gate; a stale rule here would cause the harness to revert a ratified SDK protocol fix.
