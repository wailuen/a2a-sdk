# Deferred: w029 group G — RESOLVED

- **Wave ID:** w029
- **Group:** G
- **Date:** 2026-07-10
- **Rounds completed:** 5 (budget exhausted)
- **Resolved:** 2026-07-10
- **Status:** All findings resolved — archive reconciled

---

## Findings (all resolved)

### RT-001 — low — RESOLVED
**File:** `agent_sdk/routes/ag_ui.py`

GH-96's `except Exception` handler yielded `mapper.run_error('internal error')` unconditionally, unguarded by `mapper.terminal_sent`, unlike the safety-net that follows it — risking a second terminal frame if a terminal was already built before the exception fired.

**Fix applied:** The catch-all at `ag_ui.py:443-446` now reads `except Exception: ... if not mapper.terminal_sent: for frame in mapper.run_error("internal error"): yield sse_data(frame)`, matching the guard used by the safety-net at line 451. Verified at `ag_ui.py:443-446`.

---

### RT-002 — low — RESOLVED
**File:** `tests/test_ag_ui.py`

`test_validation_inside_generator` (lines 105-112) predated GH-97's removal of the threadId/runId presence checks; it still exercised the deleted "threadId is required" path by accident, via the unrelated "no user message in input" branch, with no assertion tying the test name to what it now covers.

**Fix applied:** Test updated to explicitly assert `frames[-1]["message"] == "no user message in input"` with a comment noting GH-97 (threadId/runId are synthesized before `_validate` runs, so an empty body now fails via the message-fold branch instead). Dedicated GH-97 coverage lives in `tests/test_gh97_ag_ui_thread_run_id_synthesis.py`. Verified at `tests/test_ag_ui.py:105-120`.

---

### RT-003 — low — RESOLVED
**File:** `agent_sdk/models/content_types.py`

`_assert_finite` recursed into dict/list/tuple/BaseModel with no depth or cycle guard, so a self-referential structure passed to `ChartSection.data`/`TableSection.data` raised an uncaught `RecursionError` instead of a clean `ValidationError`.

**Fix applied:** `_ASSERT_FINITE_MAX_DEPTH = 100` added with a `_depth` counter threaded through every recursive call; exceeding the cap raises `ValueError` (converted to `ValidationError` by pydantic) instead of overflowing the interpreter stack. Verified at `content_types.py:38,41,58,64,67,70`.

---

### RT-004 — low — RESOLVED
**File:** `tests/test_version.py`

`agent_sdk.__version__` resolved to installed metadata `0.5.29` while `pyproject.toml` declared `0.5.37` — an editable-install drift, not a group-G source defect.

**Fix applied:** venv reinstalled/synced; `agent_sdk.__version__` now resolves to `0.5.37`, matching `pyproject.toml`. Verified via `python -c "import agent_sdk; print(agent_sdk.__version__)"` → `0.5.37`.

---

## Reconciliation note (RT-002, this pass)

All 7 GH items in `workspace/todos/active/w029-gh-issues.md` (now archived to
`workspace/todos/archive/w029-gh-issues.md`) were confirmed landed against
code — not just the 4 items touched by the RT findings above — before the
active todo's checkboxes were marked `[x]`:

- GH-95 (finite-float guard): `content_types.py` `_assert_finite`, tests in `tests/test_content_types.py`
- GH-96 (RUN_ERROR fallback / catch-all): `ag_ui.py:443-446`, tests in `tests/test_gh96_ag_ui_terminal_event_coverage.py`
- GH-97 (threadId/runId synthesis): tests in `tests/test_gh97_ag_ui_thread_run_id_synthesis.py`
- GH-98 (TOOL_PROGRESS card/console parity): `agent_card.py`, `chat.js`, tests in `tests/test_card_console.py`
- GH-99 (load_skill SI-2 sanitization): `loop.py:384` via `_sanitize_model_name`, tests in `tests/test_agent_skills.py`
- GH-100 (`exclude_from_catalog`): `app.py`, `agent/skills.py`, tests in `tests/test_skills_catalog.py`
- GH-101 (`_tool`-suffix registration warning): `agent/registry.py`, tests in `tests/test_gh101_tool_suffix_name_warning.py`

Full suite: `.venv/bin/pytest -q tests/` → 949 passed. A resumed `/wave w029`
will find no open work.
