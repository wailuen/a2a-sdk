---
id: LRN-496
title: AC naming real app config tested with a fake
category: testing
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The AC asked for a `run_gate` test on an app with `mcp_skills="tool"`. The test in `tests/test_gh237_testing_clients.py` used a hand-written `_FakeMcp` with a made-up `load_skill` entry. A change to the real `load_skill` name, schema or annotations would never be caught.

## Root cause
A home-made double of a protocol surface replaced the real app, violating the no-mock rule in harness/CLAUDE.md.

## Check
`grep -n "_FakeMcp" tests/test_gh237_testing_clients.py` must return nothing. The test must use `build_app()` over `httpx.ASGITransport` and a real `McpClient`.

## Prevention
When an AC names an app configuration, plan the test against `build_app()` through the ASGI transport (pattern: tests/test_gh209_testing_mcp.py). Forbid hand-written fakes of client or protocol surfaces.
