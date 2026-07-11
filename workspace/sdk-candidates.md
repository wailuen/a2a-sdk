# SDK issue candidates — w029 (2026-07-10)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GH-101's regression test test_tool_suffix_without_name_override_warns (tests/test_gh101_tool_suffix_name_warning.py:37) passes in isolation but fails in the full suite: configure_logging() (agent_sdk/observability/logging.py:46, invoked from build_app() at agent_sdk/app.py:474) sets logging.getLogger('agent_sdk').propagate = False, so once any earlier test builds an app, records from agent_sdk.agent.registry never reach pytest's root caplog handler. This is a false-green in per-file gating that turns RED at full-suite scope.
- Severity: critical
- Component: sdk/build
- File: tests/test_gh101_tool_suffix_name_warning.py:37
- Rationale: Root cause is SDK-internal logging configuration in agent_sdk/observability/logging.py and the build_app() pipeline in agent_sdk/app.py — confirmed live (root.propagate = False at logging.py:46, configure_logging() called from app.py:474). The affected test targets agent_sdk.agent.registry, an SDK internal module, not agent-specific domain code.

## Candidate 2: Pre-existing test test_non_tool_progress_loop_events_dropped_with_warning (tests/test_gh88_tool_interim_emit.py:288) fails at full-suite scope for the identical caplog/propagate=False root cause as the GH-101 test, but targets agent_sdk.agent.loop's drop-non-tool-progress-event warning path. Confirms the propagation anti-pattern is systemic across SDK logging tests, not a one-off.
- Severity: high
- Component: sdk/loop
- File: tests/test_gh88_tool_interim_emit.py:288
- Rationale: The logger under test, agent_sdk.agent.loop, is the SDK's core tool-execution loop (SDK internals per the classification criteria), not agent-domain code — the loop's event-drop/warning behavior is untouched by any specific agent's business logic.

## Candidate 3: RESOLVED — do not file
The 0.4.1 wave-summary table in workspace/todos/plan.md was reported as missing a W29 ledger row. Re-verified 2026-07-10/11 during the /sdk-test Leg 3 pass: the row `| W29 [x] ✅ 2026-07-10 (GH-95–GH-101) | w029-gh-issues.md | G | 7 | — |` is present in plan.md. The wave's own reconciliation pass (workspace/todos/completed/w029-group-G-budget-exhausted.md) already closed this gap. Stale — not filed.

## Candidate 4: RESOLVED — do not file
TimeSeriesDataPoint.value (agent_sdk/models/content_types.py:213) required-but-nullable field dropped by _Wire.wire()'s blanket exclude_none=True — matches LRN-110. Fixed 2026-07-11 (pre-tag) via a `model_serializer(mode="wrap")` on TimeSeriesDataPoint that re-inserts `value: null` when the field is None, without disturbing the Python-level `is None` semantics `TimeSeriesChart.to_plain_text()` relies on. Verified: chart.wire() now emits `{"date": ..., "value": null}`; tests/test_a2ui_wire.py::test_time_series_wire_data_keys_conform_to_profile updated to assert the correct behavior (previously asserted the bug as "spec-conformant"); full suite 949 passed, mypy clean. Not filed — landed directly.
