# Deferred: w021 group:G — RESOLVED

- **Wave ID:** w021
- **Group:** group:G
- **Date:** 2026-06-15
- **Rounds completed:** 5 (budget exhausted)
- **Resolved:** 2026-06-19
- **Status:** All findings resolved — archive reconciled

---

## Findings (all resolved)

### RT-001 — high — RESOLVED
**File:** `harness/workflows/acceptance-api.js`

`.filter(Boolean)` silently dropped null agent results, causing NaN denominators on all-crash runs.

**Fix applied:** Null results mapped to synthetic failed `SCENARIO_RESULT` records (`passed:false`, `a2aMinScore:1`, `aguiMinScore:1`, `failureClass:'code-bug'`, `failureDetail:'agent returned null (crash or timeout)'`). Length assertion added after map. Summary reduced only when `results.length > 0`. (`code-bug` — not `harness-contamination` — is correct: a null agent result does not satisfy the three-condition contamination gate at `acceptance-api.js:251-254`; it matches the landed value at `acceptance-api.js:299`.)

---

### RT-002 — low — RESOLVED
**File:** `agent_sdk/app.py`

`inspect.get_annotations` collapses `-> None` and no-annotation to the same `None` value, causing the SC-F1 emits/return-type mismatch check to skip explicit `-> None` annotations.

**Fix applied:** `__annotations__` presence check added: skip only when `'return'` is absent from `fn.__annotations__`; fall through when explicit `-> None` contradicts a non-None emits. Test case (h) in `tests/test_emits_return_type.py` validates.

---

### RT-003 — low — RESOLVED
**File:** `agent_sdk/app.py`

`_A2A_CODE` mapped `404 → -32001` (TaskNotFound), mislabelling every unknown `/v1/` route 404 as a task lookup miss.

**Fix applied:** `404` removed from `_A2A_CODE`; the `.get(exc.status_code, -32603)` fallback now applies, emitting `-32603` (generic server error) for unrouted 404s. Task-not-found (-32001) continues to be raised explicitly by task routes. `tests/test_a2a_error_envelope.py::test_unknown_v1_route_404_a2a_envelope` validates.

---

### RT-004 — low — RESOLVED
**File:** `harness/workflows/acceptance-api.js`

`task_id` was only harvested from `kind == 'status-update'` frames, missing the authoritative first `kind == 'task'` frame.

**Fix applied:** Branch added: `if ev.get('kind') == 'task': task_id = task_id or ev.get('id','')` before the status-update branch. Captures task id from the first frame regardless of stream truncation.
