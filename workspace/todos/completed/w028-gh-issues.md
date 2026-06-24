# w028 — GitHub issues GH-94

Sourced from open issues on wailuen/a2a-sdk. Single item.
Run in parallel (group:G).
Target: 0.5.36.

---

- [x] `GH-94` openai-client: RateLimitError indistinguishable from fatal errors; no retry, no user hint ‖ group:G
  - Creates: (modifies `agent_sdk/agent/openai_client.py`, creates `tests/test_gh94_rate_limit_error.py`)
  - Reads: `agent_sdk/agent/openai_client.py`, `agent_sdk/models/errors.py`
  - Severity: medium
  - Root cause: In `OpenAIModelClient.converse()` (lines 99–107), `openai.RateLimitError` falls through to the bare `except Exception` guard and is re-raised as `AgentError(ErrorCategory.UPSTREAM, "model invocation failed")` — identical to fatal errors such as auth failures and network errors. `ErrorCategory.RATE_LIMITED` already exists in `agent_sdk/models/errors.py` but is not wired to the OpenAI client path.
  - AC: `except openai.RateLimitError as exc` handler inserted after `except ModuleNotFoundError: raise` and before `except Exception`; raises `AgentError(ErrorCategory.RATE_LIMITED, "model rate limit exceeded; retry later", source="openai")`; optionally extracts `Retry-After` from `exc.response.headers` and passes as `detail={"retry_after": n}` when present; tests assert `RateLimitError` → `AgentError` with `category == ErrorCategory.RATE_LIMITED` (not `UPSTREAM`), message distinct from "model invocation failed", and fatal errors (e.g. `openai.APIConnectionError`) still produce `UPSTREAM`; no `unittest.mock`/`MagicMock`/`AsyncMock`
  - GH: https://github.com/wailuen/a2a-sdk/issues/94
