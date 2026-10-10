---
id: LRN-275
title: Test imports dependency missing from gate extra
category: testing
severity: high
source: redteam
date: 2026-10-09
---

## What happened
tests/test_gh152_oidc_rp.py, test_gh152_idp_authorize_flow.py and test_gh152_idp_no_secret_leak.py import `jwt` at module level. PyJWT is absent from the `[dev]` extra and present locally only via msal (`[obo]`). With jwt blocked, `pytest --co tests/` aborts with 3 collection errors, so no test runs in a clean venv under /sdk-test.

## Root cause
A transitive dependency of a different optional extra masked the missing declaration.

## Check
In a fresh venv run `pip install -e ".[dev]"` then `pytest --co -q tests/` and confirm zero collection errors. Confirm `grep -n "PyJWT" pyproject.toml` shows it in `[dev]`.

## Prevention
When planning tests that import a new third-party module, add it to the `[dev]` extra in the same todo, run `uv lock`, and verify collection in a `.[dev]`-only venv. Never use importorskip on security pinning tests.
