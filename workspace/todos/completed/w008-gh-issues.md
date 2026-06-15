# w008 — GitHub issues #13

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:A).
Target: v0.4.1.

---

- [ ] `GH-13` sdk/build: lifespan sweeper tight-loops to OOM when asyncio.sleep is patched in tests ‖ group:A
  - Modifies: `agent_sdk/app.py`
  - Creates: `tests/test_sweeper_isolation.py`
  - Severity: high
  - Root cause: `_sweeper()` inside `lifespan()` calls `await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)`, which resolves `asyncio.sleep` by name at call-time. Any `unittest.mock.patch('asyncio.sleep', ...)` that leaks past test teardown (e.g. from concurrent coroutines stomping saved values) causes the sweeper to spin in a tight loop, recording calls on the mock's `call_args_list` until OOM. Fix: capture the real `sleep` at module import time via `from asyncio import sleep as _asyncio_sleep` and replace the single call-site.
  - AC:
    - `agent_sdk/app.py` adds `from asyncio import sleep as _asyncio_sleep` at module level (after the existing `import asyncio`)
    - `agent_sdk/app.py` line ~263 uses `await _asyncio_sleep(_SWEEP_INTERVAL_SECONDS)` instead of `await asyncio.sleep(...)`
    - A regression test in `tests/test_sweeper_isolation.py` patches `asyncio.sleep` globally, enters the lifespan, and asserts the sweeper does not spin (i.e. `task_store.sweep()` is called at most once within a short window without the tight-loop symptom)
    - `python -m pytest tests/test_sweeper_isolation.py` passes
  - GH: https://github.com/wailuen/a2a-sdk/issues/13
