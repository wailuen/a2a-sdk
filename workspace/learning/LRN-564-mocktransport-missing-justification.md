---
id: LRN-564
title: New MockTransport lacks justification comment
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
Three new MockTransport uses in tests/test_gh237_testing_clients.py (card 429 tests) had no "# MockTransport:" comment and were not on the LRN-509 allowlist. This failed the LRN-509, LRN-534 and LRN-540 checks.

## Root cause
New testing-client tests copied the MockTransport pattern without the required justification comment or allowlist entry.

## Check
Every `MockTransport(` in tests/test_gh237_testing_clients.py has a `# MockTransport:` comment on a nearby preceding line, and the test names appear in the LRN-509 allowlist text.

## Prevention
When planning tests for testing clients, prefer build_app or the allowlisted _card_client helper; if MockTransport is unavoidable, require the comment and allowlist update in the same task.
