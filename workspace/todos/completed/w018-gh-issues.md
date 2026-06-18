# w018 — GitHub issue #56

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: v0.5.15.

---

- [x] `GH-56` A2UI_UPDATE suppressed for domain catalogs unless consumer declares catalog URN upfront ‖ group:G
  - Modifies: `agent_sdk/a2ui/translator.py`
  - Reads: `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/a2a.py`
  - Severity: medium
  - Root cause: `A2uiCapabilities.allows()` gates domain `ContentModel` types on `model_cls.catalog_id in self.catalogs`. Default `A2uiCapabilities()` only populates the standard catalog URN, so any domain catalog type (e.g. `urn:a2ui-profile:alphageo:v1`) is silently suppressed for consumers that omit `a2uiClientCapabilities`. The AG-UI spec assigns filtering to the consumer — servers must emit CUSTOM events freely; consumers silently drop what they do not understand. The `tier == "none"` guard is the correct and only gate; catalog membership must not suppress emission.
  - AC:
    - `allows()` returns `True` for any domain `ContentModel` subclass when `self.tier != "none"`, regardless of whether `model_cls.catalog_id` appears in `self.catalogs`
    - `allows()` still returns `False` for any type when `self.tier == "none"`
    - Tier gating within the standard catalog (core vs extended) is unaffected
    - A test asserts that `A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])` + a domain `ContentModel` subclass produces a non-None result from `translate()` (i.e., `A2UI_UPDATE` would be emitted)
    - A test asserts that `A2uiCapabilities(tier="none")` still returns `None` from `translate()` for domain types (no regression)
  - GH: https://github.com/wailuen/a2a-sdk/issues/56
