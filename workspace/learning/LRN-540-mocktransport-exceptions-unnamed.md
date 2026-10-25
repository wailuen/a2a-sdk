---
id: LRN-540
title: MockTransport exceptions must be named in the check
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
tests/test_gh237_testing_clients.py has 9 `MockTransport` uses, though LRN-509 forbids them. This wave added two (`_card_client` and the unsupported-version test), so the stream-body tests (kind==message, stop-at-final) never ran against a real server.

## Root cause
Convenient canned responses were used, and legitimate exceptions were never recorded in LRN-509's Check, so it fails every wave.

## Check
Run `grep -c MockTransport tests/test_gh237_testing_clients.py` and confirm only the exceptions named in LRN-509 remain (non-object card, unsupported version). Stream tests must use `build_app()` over ASGI.

## Prevention
When planning testing-client tests, require build_app() over ASGI (recording ASGI wrapper for headers). Allow MockTransport only for shapes a real app cannot produce, and name each in LRN-509.
