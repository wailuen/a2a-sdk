# w037 — GitHub issues 126

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: v0.5.44 (or next patch after w036/GH-123 ships, whichever lands first).

---

- [x] `GH-126` a2ui: apply_data_model_update() missing delete-key branch — MISSING sentinel leaves key in place instead of deleting it ‖ group:G
  - Creates: (modifies `agent_sdk/a2ui/translator.py`, `agent_sdk/console/static/a2ui.js`, `tests/test_a2ui_wire.py`, `CHANGELOG.md`, `pyproject.toml`)
  - Reads: `.claude/agents/a2ui-advisor.md`, `workspace/todos/deferred/w015-group-group:A-budget-exhausted.md`
  - Severity: Medium (downgraded from the issue's claimed High — `apply_data_model_update` has zero production callers anywhere in `agent_sdk/`; `translate()`, the SDK's only emit path, always sets an explicit `value` key and never omits it, so this is a correctness bug in an untriggered public utility, not a live wire defect today. Still worth fixing ahead of any future inbound-`updateDataModel` consumer.)
  - Root cause: `apply_data_model_update()` (`agent_sdk/a2ui/translator.py:237-238`) returns immediately when `value is MISSING`, treating it as "leave unchanged" — but A2UI v0.9.1 defines omitting `value` as delete-at-path (confirmed verbatim in `.claude/agents/a2ui-advisor.md:90-93`: "omitting the `value` key deletes it — these are different operations from `value: null`"). The console renderer (`agent_sdk/console/static/a2ui.js:130-138`) already implements the correct delete-on-omit semantic on the same wire message, so server and renderer diverge on identical input. The docstring at `translator.py:224-227` documents the wrong (no-op) behavior as intentional. `MISSING` is imported nowhere in `agent_sdk/` except the one self-pinning test (`tests/test_a2ui_wire.py:381`, `test_apply_data_model_update_missing_is_noop`) that asserts the current no-op behavior — so redefining `MISSING` to mean delete is a safe, non-breaking signature-preserving fix (no new sentinel needed). Note: the issue's cited provenance (`LRN-245`, `LRN-346`) does not correspond to any file in `workspace/learning/` (tops out at LRN-133) — the bug itself is independently confirmed genuine regardless of that fabricated citation trail.
  - AC:
    - `apply_data_model_update()` is reordered so parent-key navigation (tokens/target traversal) runs unconditionally, then branches: `value is MISSING` → `target.pop(leaf, None)` (delete, no-op if absent); else → `target[leaf] = value` (set, including explicit `None` → JSON null) — mirroring `a2ui.js`'s unconditional-traverse-then-branch shape in `pointerSet`.
    - The docstring's *value* semantics section is updated to state `MISSING` means delete-at-path per A2UI v0.9.1, removing the contradicting "leave unchanged" language.
    - `tests/test_a2ui_wire.py::test_apply_data_model_update_missing_is_noop` is rewritten to assert deletion (rename to `test_apply_data_model_update_missing_deletes_key`); add a case deleting a non-existent leaf (must not raise) and a nested-path delete case.
    - `CHANGELOG.md` gets an entry noting the `MISSING`/delete behavior fix, consistent with the existing "a2ui: updateDataModel null-vs-absent semantics" entry (`CHANGELOG.md:579`).
    - Optional bundle (same function, same file — include if low-risk): fix `RT-JSON-POINTER-001` (deferred in `workspace/todos/deferred/w015-group-group:A-budget-exhausted.md:9-14`) — the escape guard checks `/..` on the raw pointer before `~1`/`~0` decoding, missing percent/tilde-escaped traversal.
    - Authorized RT-001 follow-up (renderer, in scope): `agent_sdk/console/static/a2ui.js`'s `pointerTokens()` folds the literal `"/"` path to the empty token list (same as `""`), matching A2UI v0.9.1's `"/"`-means-whole-data-model-replace override — not the RFC-6901-literal single-segment pointer to child key `""` — so `pointerGet`/`pointerSet` in the console renderer agree with `apply_data_model_update()` on `"/"` semantics. This is a protocol-surface (renderer) change, not scope creep: it is required for server/renderer conformance parity and is declared above under Creates/Modifies.
    - Full `tests/` suite green after the change (no other test depends on the old no-op semantics).
  - GH: https://github.com/wailuen/a2a-sdk/issues/126
