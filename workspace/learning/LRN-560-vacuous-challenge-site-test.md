---
id: LRN-560
title: Challenge-site test passes without reaching the branch
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`test_consent_post_rerender_keeps_bare_challenge` in `tests/test_gh260_rate_limit.py` never reached the consent re-render at `oauth.py:967`. It used an unregistered `client_id` ("nope") and the wrong form field (`admin_key`, not `api_key`). The result was a 400 page with no header, and the `wa is None or ...` assert passed anyway.

## Root cause
A guard clause let the assert succeed when the header was absent, so a test that never hit the site looked green.

## Check
grep -n "is None or" tests/test_gh260_rate_limit.py returns no match. The test registers a client via POST /oauth/register, sends field `api_key`, and asserts status 401 and a `www-authenticate` header starting with `Bearer resource_metadata="`.

## Prevention
When planning a test for a challenge or error site, require it to assert status code and header presence before checking header form. Ban `x is None or ...` guards in asserts.
