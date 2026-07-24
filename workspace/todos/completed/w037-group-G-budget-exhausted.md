wave: w037
group: G
date: 2026-07-24
round_count: 5
status: budget-exhausted

## Summary

Group G's zero-tolerance redteam loop reached round 5 (the wave-cycle.js exit
round) with 3 findings still open in `agent_sdk/a2ui/translator.py` (RT-001,
RT-002) and `tests/test_a2ui_wire.py` (RT-003). Per the round-5 exit rule,
remaining findings are recorded here rather than looped further.

## Findings

### RT-001
- severity: medium
- file: agent_sdk/a2ui/translator.py
- status: FIXED (2026-07-24)
- description: The new `if pointer == "/": raise ValueError("whole-data-model replace ... which pointerSet implements")` guard (translator.py:271-275), plus the docstring (lines 219-233) and CHANGELOG 0.5.44 RT-003 entry, rest on a factually false claim: the console renderer's pointerSet does NOT treat `/` as whole-model-replace. Empirically pointerSet({}, '/', 'X') returns {'':'X'} (it writes the empty-string key, since pointerTokens('/')==['']); only the bare '' pointer triggers whole-replace (pointerSet({a:1},'','X') -> 'X'). The OLD Python code wrote model['']=value for '/', which AGREED with the renderer. This 'fix' therefore INTRODUCES a server/renderer divergence on '/' (Python now raises where the renderer writes model['']), under a rationale claiming the opposite goal of reconciling divergence. The docstring's assertion that pointerSet 'returns value verbatim for an empty token list' for BOTH '' and '/' is wrong for '/' (its token list is [''], not empty).
- fix: The premise of the original guard was itself the bug, not the fix — mirroring `pointerSet` literally would have relocated the renderer's own non-conformance (`pointerTokens('/')` addressing the ordinary child key `model[""]`, rather than the spec's whole-model-replace override) into the server. Root-fixed in `agent_sdk/a2ui/translator.py`'s "RT-002 (redteam finding, corrects the w037/RT-001 'fix')" docstring section: both `pointerTokens` (`agent_sdk/console/static/a2ui.js`) and `apply_data_model_update` now implement A2UI v0.9.1's literal "omit `path` or use `/` to replace the whole data model" rule directly against the spec text — `""` and `"/"` are handled identically as a genuine whole-model replace (`model.clear(); model.update(value)`), evaluated before the root-relative check, with `ValueError` for a non-`dict` *value* since this is an in-place mutator. CHANGELOG 0.5.44 documents the correction explicitly, including the "an earlier revision of this fix reasoned from the renderer alone ... that premise was itself non-conformant" note. Pinned by `test_apply_data_model_update_empty_pointer_replaces_whole_model`, `..._slash_pointer_replaces_whole_model`, `..._empty_and_slash_pointer_are_symmetric`, and the `..._conforms_to_a2ui_spec_on_*_whole_model_replace` tests.
- codify: A 'reconcile with the renderer' fix must be validated against the renderer's actual output (pointerSet('/') writes model[''], not whole-replace) before asserting parity in docstring/CHANGELOG.
- sdkCandidate: true

### RT-002
- severity: low
- file: agent_sdk/a2ui/translator.py
- status: FIXED (2026-07-24)
- description: The MISSING/delete branch scaffolds empty parent dicts while walking (translator.py:296-302 shared traversal with setdefault(token, {})), so a delete targeting an absent nested path MUTATES the model: apply_data_model_update({}, '/a/b/c', MISSING) yields {'a':{'b':{}}} (pinned by test as intentional). A no-op delete polluting the model with empty containers that then serialize onto the wire is surprising public-API behavior. Separately, the docstring's RT-002 divergence enumeration (lines 254-261) is incomplete: it covers only a pre-existing LIST-valued intermediate node, but for a SCALAR intermediate the renderer destroys data while Python preserves it — pointerSet({a:5},'/a/b/c',undefined) overwrites 5 -> {a:{b:{}}}, whereas Python no-ops leaving {a:5}. That scalar-node divergence from pointerSet is undocumented.
- fix: The docstring now states one reconciliation rule covering every intermediate-node type (absent, dict, list, scalar) — "mirror `pointerSet`'s traverse-then-branch, except never overwrite/destroy a pre-existing non-dict node" — and explicitly documents the scalar-intermediate divergence (CHANGELOG 0.5.44 RT-002b: this helper preserves a pre-existing scalar intermediate, set raises / delete no-ops, where `pointerSet` destructively overwrites it with `{}`/`[]`). Additive scaffolding on a no-op delete for an absent nested path is documented as an intentional, pinned convergence with the renderer (matches `pointerSet({}, "/a/b/c", undefined)` -> `{"a": {"b": {}}}` on both sides), not an accidental mutation. Pinned by `test_apply_data_model_update_missing_scaffolds_absent_intermediate_path`, `..._set_through_scalar_intermediate_raises`, `..._missing_through_scalar_intermediate_preserves_value`.
- codify: When claiming 'server and renderer converge on identical wire input', enumerate every intermediate-node type (dict, list, scalar, absent); a divergence note covering only lists silently ships scalar-node divergence.
- sdkCandidate: true

### RT-003
- severity: low
- file: tests/test_a2ui_wire.py
- status: FIXED (2026-07-24)
- description: Every apply_data_model_update test asserts the Python helper's behavior in ISOLATION; none cross-checks against the actual pointerSet output the docstrings repeatedly claim to 'converge' with. Because no test compares the two implementations, the two real divergences found here ('/' handling and scalar-intermediate delete) shipped with green tests plus false convergence claims in the docstring and CHANGELOG.
- fix: Added convergence/divergence pin tests that cross-check `apply_data_model_update` against an actual `pointerSet` reference: `test_apply_data_model_update_converges_with_pointer_set_reference` (static reference table) and `test_apply_data_model_update_converges_with_live_pointer_set_reference` (live node cross-check), plus explicit divergence pins (`..._diverges_from_(live_)pointer_set_reference_on_scalar_intermediate_delete`, `..._on_whole_model_replace_non_dict`, `..._on_genuine_dotdot_token`) so a future edit to either side that silently drifts them apart fails CI instead of shipping green.
- sdkCandidate: false

## Instruction

All findings resolved and test-covered (full `tests/` suite green, 1276 passed);
no re-run of /wave w037 needed. `GH-126` ticked in
`workspace/todos/completed/w037-gh-issues.md`. Relocated from
`workspace/todos/deferred/` to `workspace/todos/completed/` per LRN-100 (a
budget-exhausted deferred marker must be removed or relocated the moment its
findings land, or it falsely reports the wave as incomplete).
