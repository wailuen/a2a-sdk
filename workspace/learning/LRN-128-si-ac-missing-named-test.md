---
id: LRN-128
title: SI-tagged AC landed without its mandated regression test
category: testing
severity: high
source: redteam
date: 2026-07-20
---

## What happened
An SI-2 acceptance criterion required a regression test confirming a
redirect_uri with an embedded control char / injected directive is rejected
before reaching the header. `tests/test_oauth_flow.py` only shipped
`test_valid_redirect_uri_rejects_custom_scheme` (scheme rejection), never
exercising control-char or CSP-directive injection. Had that test existed,
it would have caught RT-002.

## Root cause
The AC's named test was treated as satisfied by an adjacent, differently-scoped
test instead of being independently verified — an unenforced invariant.

## Check
For every AC tagged `[SI-*]` in a wave's todos/plan, grep the referenced test
file for a test whose name/body matches the AC's literal scenario (e.g.
control-char/`;`-injection in redirect_uri), not merely a same-topic test.
`grep -n "def test_" tests/test_oauth_flow.py` and confirm a control-char or
`;`-injected redirect_uri case exists and asserts the CSP has exactly one
`frame-ancestors` directive.

## Prevention
When planning any `[SI-*]`-tagged AC, require the todo to name the exact test
function (not just "add a test") and gate phase-redteam on grep-verifying that
function exists and asserts the literal attack input from the AC — not a
same-topic substitute.
