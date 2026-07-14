# w033 — GitHub issues 115–117

Sourced from open issues on wailuen/a2a-sdk (surfaced by w032's protocol audit,
blocking the 0.5.42 release gate). All items are independent.
Run in parallel (group:G).
Target: 0.5.42. (w032 shipped as 0.5.41 — see CHANGELOG.md; W033 is the next
release slot, matching pyproject.toml's current bumped version.)

---

- [x] `GH-115` MCP tools/call bypasses generator dispatch ‖ group:G
  - Creates: (modifies `agent_sdk/routes/mcp.py`, adds a regression test alongside `tests/test_gh87_deferred_task.py`'s pattern)
  - Reads: `agent_sdk/routes/mcp.py:371` (unconditional `entry.invoke()`), `agent_sdk/agent/loop.py:441-446` (reference `is_generator` branch), `tests/test_gh87_deferred_task.py` (existing long_running Tier-1 tool test shape)
  - Severity: high
  - Root cause: `_handle_tools_call` always calls `entry.invoke()`, never `entry.invoke_gen()`. Any Tier-1 tool declared `long_running=True` (async-generator body) raises `TypeError` inside `invoke()`, swallowed by a blanket `except Exception` into a generic `isError: true`. `agent/loop.py`'s A2A/AG-UI dispatcher already branches on `entry.decl.is_generator`; `routes/mcp.py` never replicated it — breaks the module's own "Tier 1 surface parity" guarantee.
  - AC: `mcp.py`'s `tools/call` handler branches on `entry.decl.is_generator`, calling `invoke_gen()` for generator tools, mirroring `agent/loop.py:441-446`.
  - AC: new regression test registers a `long_running=True` async-generator Tier-1 tool and asserts MCP `tools/call` returns valid content (not `isError`).
  - AC: existing non-generator tool call behavior is preserved except that it now applies the same per-tool timeout budget as the generator branch and the A2A/AG-UI surfaces (`resolve_tool_timeout`) — intended consistency, not byte-for-byte "unchanged"; a dedicated test asserts the timeout path yields `isError: true` (RT-003, `tests/test_rt003_rt004_mcp_error_mapping.py::test_mcp_tools_call_timeout_is_diagnostic_not_generic`).
  - GH: https://github.com/wailuen/a2a-sdk/issues/115
  - SI: SI-2  # Modifies routes/mcp.py tools/call (MCP transport) but carries no SI: line. The new entry.decl.is_generator branch draining invoke_gen() must preserve the same SI-2-safe error handling as the existing blanket except at mcp.py:378-388 (generic 'tool execution failed'; tool name/args/exception text go to the structured log only, never echoed to the caller). Mirror loop.py's gen-branch error mapping (AgentError.public(), _safe_validation_message, generic fallback) rather than str(exc) on a raised TypeError/ValidationError from the drain.

- [x] `GH-116` A2UI system-prompt teaching surface ignores allowed_components ‖ group:G
  - Creates: (modifies `agent_sdk/a2ui/catalog.py`, `agent_sdk/app.py`, adds a regression test)
  - Reads: `agent_sdk/a2ui/catalog.py:154` (`get_system_prompt_section()`), `agent_sdk/a2ui/catalog.py` (`_filtered_types()`, `supported_catalogs`/`data_types_for_catalog`/`a2ui_extension` for the sibling pattern), `agent_sdk/app.py:546` (`build_app()` call site)
  - Severity: high
  - Root cause: `get_system_prompt_section()` is the one function among its four siblings that doesn't thread `allowed_components` through `_filtered_types()` — it always teaches the LLM the full 14-type Standard Profile catalog. `app.py:546` calls it with zero args. Since `_validate_emits()` only gates tool-declared `emits=` targets (not the LLM's free-form JSON), an agent configured to restrict the catalog (SC-D2) still gets taught schemas for disallowed types.
  - AC: `get_system_prompt_section()` accepts an `allowed_components` parameter and filters via `_filtered_types()`, matching its 3 siblings.
  - AC: `app.py:546` passes `settings.a2ui_allowed_components`.
  - AC: new regression test configures a restricted `a2ui_allowed_components` and asserts the built system prompt omits schemas/few-shot JSON for excluded types.
  - GH: https://github.com/wailuen/a2a-sdk/issues/116

- [x] `GH-117` DESIGN.md MCP-Protocol-Version rule stale post-GH-77 ‖ group:G
  - Creates: (modifies `DESIGN.md`, `REVIEWS.md`)
  - Reads: `DESIGN.md §5.5`, `agent_sdk/routes/mcp.py` module docstring (transport-split behavior, commit bbfe353), `tests/test_mcp_gh77_absent_version_header.py`, `REVIEWS.md` Round-1 disposition table
  - Severity: high
  - Root cause: DESIGN.md §5.5 states one blanket rule ("absent → assume 2025-03-26"); GH-77 split this by transport (Streamable HTTP: absent → 400 on non-init; Legacy SSE: absent → assume 2025-03-26). `mcp.py`'s docstring was corrected in commit bbfe353; DESIGN.md and REVIEWS.md were not — canonical spec doc now contradicts shipped, tested behavior.
  - AC: DESIGN.md §5.5 explicitly distinguishes Streamable HTTP vs Legacy SSE absent-header behavior.
  - AC: REVIEWS.md's Round-1 disposition table updated to match.
  - AC: `grep -n "assume 2025-03-26" DESIGN.md` output shows the transport-split language, not a blanket rule.
  - GH: https://github.com/wailuen/a2a-sdk/issues/117
