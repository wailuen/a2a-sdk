---
id: LRN-509
title: Testing-client tests must use real build_app over ASGI
category: testing
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-237 tests for run_gate output-schema checks used a hand-written `_stub_client`. The version-header test used `httpx.MockTransport` and a leaked `tempfile.mkdtemp()` key file. Real-app paths existed for both failure modes.

## Root cause
Stubs were quicker to write. A stub only proves the stub and hides gate/server contract disagreements (LRN-496).

## Check
Grep `tests/test_gh237_testing_clients.py` for `_stub_client` and `mkdtemp` and confirm no match. `MockTransport` is allowed only in tests that need a shape a real app cannot produce, each with a `# MockTransport:` comment naming why: the scripted AG-UI frame tests (`_driver`, `test_turn_http_error_leaves_messages`, `test_agui_turn_connect_error_leaves_messages_unchanged`, `test_agui_turn_cancel_after_first_frame_leaves_messages_unchanged`), `test_missing_preferred_transport_defaults_to_jsonrpc_and_is_rejected`, the `_card_client` helper (non-object card, failing card fetch, bare `kind=="message"` stream event) `test_mcp_client_rejects_unsupported_negotiated_version`, `test_card_429_then_success_gets_the_real_card`, `test_card_429_failure_reports_http_429` and `test_card_retry_builds_no_new_client`. Any other `MockTransport` use fails the check. Confirm the tests use `build_app()` with `httpx.ASGITransport` and `tmp_path`.

## Prevention
When planning tests for a testing-client feature, require a real `build_app()` over ASGI. Use a tier-1 tool returning None for the absent case and `Out.model_construct(...)` for the mismatch case. Wrap the transport in a recorder for header assertions.
