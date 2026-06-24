# w027 — GitHub issues GH-92, GH-93

Sourced from open issues on wailuen/a2a-sdk. Both items are independent.
Run in parallel (group:G).
Target: 0.5.35.

---

- [x] `GH-93` openai-client: openai package undeclared; ModuleNotFoundError wraps to cryptic "model invocation failed" ‖ group:G
  - Creates: (modifies `pyproject.toml`, modifies `agent_sdk/app.py`, modifies `agent_sdk/agent/openai_client.py`, creates `tests/test_gh93_openai_missing_package.py`)
  - Reads: `pyproject.toml`, `agent_sdk/app.py`, `agent_sdk/agent/openai_client.py`
  - Severity: high
  - Root cause: `import openai` is deferred inside `_openai_client()` (openai_client.py:64), called from `converse()`. The bare `except Exception` at line 101 catches `ModuleNotFoundError` and re-raises it as generic `AgentError(UPSTREAM, "model invocation failed")`, making it indistinguishable from a real upstream failure. `openai` is entirely absent from `pyproject.toml`. `app.py`'s `_build_model_client()` performs no startup import check. Fix: (a) add `openai = ["openai>=1.0"]` optional extra to `pyproject.toml`; (b) add eager import probe in `_build_model_client()` that raises `ImportError` with clear install instructions when the OpenAI/Azure backend is configured but `openai` is not installed; (c) in `converse()`, add `except ModuleNotFoundError: raise` before the bare `except Exception` so deferred-import failures propagate unmodified.
  - AC: `pip install "agent-sdk[openai]"` installs the `openai` package; `build_app()` with `OPENAI_MODEL` or `AZURE_OPENAI_ENDPOINT` set but `openai` not installed raises `ImportError` with a message mentioning `agent-sdk[openai]`; `ModuleNotFoundError` in `converse()` is never swallowed into `AgentError`; tests cover both the startup-check path and the `converse()` propagation path; no mocks (use `sys.modules` manipulation for the startup-check test)
  - GH: https://github.com/wailuen/a2a-sdk/issues/93

- [x] `GH-92` test: replace MagicMock with real in-memory fakes in test_scheduler.py, test_a2ui_group_d.py, test_azure_commitment_store.py ‖ group:G
  - Creates: (modifies `tests/test_scheduler.py`, modifies `tests/test_a2ui_group_d.py`, modifies `tests/test_azure_commitment_store.py`)
  - Reads: `tests/test_scheduler.py`, `tests/test_a2ui_group_d.py`, `tests/test_azure_commitment_store.py`, `tests/test_azure_subscription_store.py`
  - Severity: low
  - Root cause: Three test files violate the SDK no-mock rule. (1) `test_scheduler.py`: 7 tests use `MagicMock()` as a dummy `app` argument to `sched.lifespan(app)` — the `_lifespan` inner function ignores it entirely. Replace with `types.SimpleNamespace()`. The `patch()` calls for `asyncio.create_task` and `sched_mod._sleep` are stdlib intercepts and acceptable. (2) `test_a2ui_group_d.py`: `MagicMock(spec=ContentModel)` in 2 tests — replace with a minimal `_StubContentModel` concrete subclass. (3) `test_azure_commitment_store.py`: `MagicMock()` used pervasively as fake Azure Table SDK client — replicate the `_FakeTableClient` in-memory approach from `test_azure_subscription_store.py` (dict-backed, ETag-conditional conflict support).
  - AC: zero `MagicMock` / `AsyncMock` / `patch` imports remain in the three files; `test_scheduler.py` uses `types.SimpleNamespace()` for the dummy app argument; `test_a2ui_group_d.py` uses a concrete `_StubContentModel` subclass; `test_azure_commitment_store.py` uses a `_FakeTableClient` in-memory class; all existing tests still pass; no new `unittest.mock` usage introduced
  - GH: https://github.com/wailuen/a2a-sdk/issues/92
