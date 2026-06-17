# w017 — GitHub issues #47, #51

Sourced from open issues on wailuen/a2a-sdk. Both items are independent files.
Run in parallel (group:G).
Target: v0.5.14.

---

- [x] `GH-51` sdk/loop: A2A multi-turn task continuation does not carry prior conversation history into model context ‖ group:G
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `tests/`)
  - Reads: `agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py`, `agent_sdk/tasks/store.py`
  - Severity: high
  - Root cause: `_resume_or_error` and `message_stream` hard-reject with -32009 / -32001 when `taskId` points to a terminal task (COMPLETED/FAILED/CANCELED). No code path exists to fork a new task that inherits the prior `record.messages` list (Converse-format conversation history). The model starts fresh on Turn 2 — Turn 1 assistant/user messages are absent from its context, causing entity drift (e.g. location resolved to Miami instead of Sydney).
  - AC: Add `_continue_from_terminal(request, params, identity)` to `a2a.py`: look up prior record by `task_id`; assert state in `TERMINAL_STATES`; call `new_task(prior_record.task.context_id)`; create new `TaskRecord` via `task_store.create()`; copy `list(prior_record.messages)` into `new_record.messages`; append Turn 2 user message dict; set `new_task.history = [msg]`; return new record. Wire into `message_send` (before the UnsupportedOperation path) and `message_stream` (replacing the hard terminal-404). Identity binding: `store.get(task_id, identity)` — mismatched identity still returns -32001. Tests assert: Turn 2 from COMPLETED task carries prior messages; new task has distinct `task.id` but same `context_id`; Turn 2 from FAILED task works identically; Turn 2 with non-terminal interrupted `taskId` still routes through `_resume_or_error` unchanged.
  - GH: https://github.com/wailuen/a2a-sdk/issues/51

- [x] `GH-47` protocol/mcp: tool inputSchema missing additionalProperties: false and required array ‖ group:G
  - Creates: (modifies `agent_sdk/agent/registry.py`, `tests/`)
  - Reads: `agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`
  - Severity: low
  - Root cause: `ToolEntry.input_schema()` in `registry.py:170–173` has two gaps: (1) the no-input-model branch returns `{"type": "object", "properties": {}, "additionalProperties": False}` — missing `"required": []`; (2) the Pydantic branch returns `model_json_schema()` verbatim — Pydantic emits `required` for required fields but never adds `additionalProperties: false`, so all typed-input tools are missing that constraint.
  - AC: In `ToolEntry.input_schema()`: add `"required": []` to the no-model literal dict. For the Pydantic branch, after calling `model_json_schema()` call `schema.setdefault("additionalProperties", False)` and `schema.setdefault("required", [])` before returning. Tests assert `input_schema()` output always contains both `"required"` (list) and `"additionalProperties": false` for (a) no input model, (b) all-optional fields model, (c) required-fields model.
  - GH: https://github.com/wailuen/a2a-sdk/issues/47
