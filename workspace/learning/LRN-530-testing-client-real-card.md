---
id: LRN-530
title: Testing-client ACs need build_app() card, not MockTransport
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-256 AC item 4 was unmet. The A2UI activation and resume tests in tests/test_gh237_testing_clients.py ran on made-up MockTransport cards. The one build_app() test used an app with no A2UI tool, so the card never advertised A2UI.

## Root cause
MockTransport was the easy path; the AC was never proven against the real card over ASGI (LRN-496).

## Check
In tests/test_gh237_testing_clients.py, confirm a build_app() test with an A2UI-emitting tool asserts X-A2A-Extensions, a2uiClientCapabilities and supportedCatalogIds, plus a build_app() resume test sending taskId and contextId.

## Prevention
When an AC names a testing-client behaviour against the agent card, require a build_app() over httpx.ASGITransport test, with A2UI on and off. MockTransport may only add edge cases.
