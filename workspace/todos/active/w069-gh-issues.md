# w069 — GitHub issue 275

Sourced from open issues on wailuen/a2a-sdk (deferred-labelled #186 and #224 skipped). One item.
Target: 0.25.1 (patch: the error text gets more detail; no wire shape changes).

Each item adds its own entry to `CHANGELOG.md` under a single `## [Unreleased]` heading (create it once if absent, LRN-494), naming every changed `agent_sdk/` file by full repo path (LRN-491). Tests run against `build_app()` over the ASGI transport where a route is involved (LRN-496). A test that guards a behaviour must fail when that behaviour is removed (LRN-560).

---

## G1 — loop validation errors

- [ ] `GH-275` sdk/loop: enum/Literal input errors do not name the allowed values ‖ group:G1
  - Creates: (modifies `agent_sdk/agent/loop.py`, `tests/test_rt003_tool_input_validation_error_message.py`, a new `tests/test_gh275_allowed_values.py`, `docs/` (only the page that documents tool input-error text, if one does), `CHANGELOG.md`)
  - Reads: `tests/test_gh250_core_hardening.py`, `tests/test_gh230_safe_value_error.py`, `tests/test_admin_try_tool_validation_leak.py` (must stay green unchanged)
  - Severity: medium
  - Root cause: `_VALIDATION_TYPE_PHRASES["literal_error"]` / `["enum"]` (loop.py:1067-1068) is a fixed phrase that never names the choices, so a client (e.g. Claude.ai over MCP) cannot correct its call.
  - AC: For `literal_error` and `enum`, the phrase becomes `must be one of: <values>`. The values come from the **declared schema of `input_model`**, resolved by walking `loc` the same way `_redact_loc` does (reuse its walk, no second walker): the `Literal[...]` args or the `Enum` member values of the field's annotation (unwrapping `Optional`/`Annotated`). They are **not** taken from `err["ctx"]["expected"]`, because a custom validator can raise `PydanticCustomError("literal_error", ..., {"expected": <user input>})`. Each value is rendered with `json.dumps` and cleaned with `safe_line_text`. The list is capped (at most 20 values and 300 characters, then `and N more`). When the values cannot be resolved from the schema (no `input_model`, a dict-key segment, a custom type), the old fixed phrase is kept. The rejected input is never echoed (SI-2). Tests: (1) the issue's repro, `sort: Literal["appointment_date", "-appointment_date"] | None` with `"ceased_desc"` over MCP `tools/call`, gives `isError: true` and text containing `sort — must be one of: "appointment_date", "-appointment_date"` and not `ceased_desc`; (2) an `Enum` field lists the member values; (3) an int Literal renders `1, 2`; (4) a nested model field and a `list[Literal]` item resolve; (5) a 50-value Literal is capped with `and 30 more`; (6) a custom validator raising `PydanticCustomError("literal_error", ..., {"expected": "<marker>"})` does not echo `<marker>`; (7) with no `input_model` the old phrase is kept.
  - GH: https://github.com/wailuen/a2a-sdk/issues/275
