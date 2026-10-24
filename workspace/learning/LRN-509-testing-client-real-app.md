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
Grep `tests/test_gh237_testing_clients.py` for `_stub_client`, `MockTransport` and `mkdtemp` and confirm no match. Confirm the tests use `build_app()` with `httpx.ASGITransport` and `tmp_path`.

## Prevention
When planning tests for a testing-client feature, require a real `build_app()` over ASGI. Use a tier-1 tool returning None for the absent case and `Out.model_construct(...)` for the mismatch case. Wrap the transport in a recorder for header assertions.
