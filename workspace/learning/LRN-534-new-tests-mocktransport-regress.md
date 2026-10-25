---
id: LRN-534
title: New testing-client tests regress to MockTransport
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-256 added three MockTransport uses in `tests/test_gh237_testing_clients.py` (`_card_client`, the ChatDriver header test, the McpClient version test). Real-app equivalents existed: `_a2ui_app` advertises A2UI and `_fake_tools_app` does not. This broke the LRN-496/LRN-509 rule.

## Root cause
Fakes were quicker to write, and the allowlist in LRN-509 was not applied to the new tests.

## Check
Grep `MockTransport` in `tests/test_gh237_testing_clients.py`. Confirm each hit is on the LRN-509 allowlist and has a `# MockTransport:` comment naming why build_app cannot produce the input.

## Prevention
When planning testing-client tests, require build_app() over ASGI via `_Recorder`. Allow a fake only for inputs the real app cannot produce (non-object card, transport error, bogus version), with a comment saying why.
