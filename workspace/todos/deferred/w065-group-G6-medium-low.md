# w065 — group G6 — deferred medium/low findings

- Wave: w065
- Scope: unit:G6
- Date: 2026-10-24
- Source: every redteam round of unit G6, deduped by file + description

> Non-blocking — these did not block w065's archive. Address opportunistically or fold into a future wave.

All items are sdkCandidate: true.

## Medium

### D-01 GH-249 item 3 not fixed in practice: required-ness from serialization schema (RT-001)
- File: agent_sdk/a2ui/catalog.py:111
- Quote: `return frozenset(model.model_json_schema(mode="serialization").get("required", []))`
- Problem: the pydantic serialization-mode schema marks a defaulted field required only when the model sets `json_schema_serialization_defaults_required=True`; ContentModel does not. A TimeSeriesChart probe still gives `x_key?: str, y_key?: str, ... total_count?: int` (the exact output the issue reported). Wrong the other way too: on the opt-in test model `_Nested`, `maybe: str|None = None` shows as required (`maybe: str|null`), but `ContentModel.wire()` drops it (exclude_none=True). The only test (tests/test_gh249_a2ui_gating.py:41) turns the flag on, so the default case is never covered, and it does not assert `maybe?`.
- Fix: decide required-ness from the real wire contract. `wire()` is `model_dump(by_alias=True, exclude_none=True)`, so a field is always written when it has no `exclude` and either `info.is_required()` or its default (`info.get_default(call_default_factory=True)`) is not None. Apply in both `_field_summary` and `_nested_fields`. Add a test on a custom type with default ContentModel config asserting `x_key: str` (default "date") and `maybe?` (default None). Drop the opt-in from the test model, or keep it and assert `maybe?` still shows.
- Codify: to decide whether a field is 'required' in a catalog teaching string, use what wire() actually writes (exclude_none plus defaults), never the pydantic JSON-schema `required` list — that list depends on a per-model config flag.

### D-02 Card drops A2UI extension but runtime still activates/echoes/emits A2UI (RT-002)
- File: agent_sdk/routes/agent_card.py:156
- Quote: `if supported_catalogs(allowed_components, emits):`
- Problem: the card omits the A2UI extension when no tool declares `emits`, but routes/a2a.py:437 still activates A2UI from the X-A2A-Extensions header and `_echo_extensions` echoes it; runner.py `build_artifact` still sends A2UI DataParts for any tool without `emits` returning a ContentModel. Result: (a) server echoes an extension its card does not declare; (b) wrapped `data.messages` A2UI parts go out with no `dataEncoding` hint on the card (LRN-134); (c) `testing/turns.py::_a2ui_advertised` skips the opt-in, so acceptance runs silently fall back to text-only cards.
- Fix: one shared check, e.g. `registry_advertises_a2ui(registry, allowed_components)` in a2ui/catalog.py, called from `build_agent_card` and from routes/a2a.py `_capabilities` / `_echo_extensions`, so with no card extension A2A requests resolve to `tier="none"` and the A2UI URI is never echoed. Route-level test: empty-emits registry + A2UI X-A2A-Extensions header → no A2UI echo, no A2UI DataPart. Alternative: keep runtime emission and document in docs/tools.md and docs/protocols.md that A2UI over A2A requires `emits=`.
- Codify: when an agent-card capability becomes conditional, the route that activates and echoes it must use the same condition, or the card and the wire disagree.

## Low

### D-03 translator.py has no `__all__`; docstring claim and pinning test are vacuous (RT-003)
- File: agent_sdk/a2ui/translator.py:251
- Quote: `"""INTERNAL (GH-249): not part of the public API and not in ``__all__``.`
- Problem: no `__all__` exists, so `from agent_sdk.a2ui.translator import *` still exports SurfaceRegistry and apply_data_model_update. The test at tests/test_gh249_a2ui_gating.py:73 (`assert not hasattr(translator, "__all__") or ...`) passes via the `not hasattr` branch and checks nothing.
- Fix: add an explicit `__all__` listing the public names (A2uiCapabilities, translate, CATALOG_ID and others imported elsewhere), excluding SurfaceRegistry and apply_data_model_update. Test must assert `hasattr(translator, "__all__")`, both names absent from it, and both absent from `agent_sdk.a2ui.__all__`. Alternative: reword both docstrings to "not in `agent_sdk.a2ui.__all__`".

### D-04 Stale required-ness docstrings in catalog.py (RT-004)
- File: agent_sdk/a2ui/catalog.py:69 (and `_field_summary` at :134)
- Quote: ``from ``FieldInfo.is_required()`` only, never from the annotation. A union``
- Problem: `_annotation_str` and `_field_summary` docstrings say required-ness comes from `is_required()` only; GH-249 now also uses the serialization schema (or the wire-written default after D-01).
- Fix: describe the actual rule (required when is_required() or the field is always written to the wire) and state that nested models expand one level.

### D-05 Nested expansion bypasses the 250-character budget (RT-005)
- File: agent_sdk/a2ui/catalog.py:100
- Quote: `return f"{cls_name}{_nested_fields(ann, depth - 1)}", required`
- Problem: the budget loop drops only whole top-level optional fields; optional inner fields of a required nested field are never dropped, so a required nested model with many optional fields yields a system-prompt line far over 250 chars, breaking the `_field_summary` budget promise.
- Fix: track optional inner fields in `_nested_fields` and drop them (append `...`) when over budget; or cap each expanded nested part (required inner fields, plus optional ones under a per-field cap). Test: required nested model with ~20 optional fields → len(summary) bounded.

---
Filed 2026-10-25 by /sdk-autoloop cycle 1: verified still-present mediums (and lows sharing a fix) are in #251–#260. Other lows stay here, unfiled.
